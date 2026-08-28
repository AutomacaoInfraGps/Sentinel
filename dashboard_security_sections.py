import html
import json
import re
import unicodedata
from pathlib import Path


def _escape(value):
    return html.escape(str(value if value not in (None, "") else "N/A"))


def _normalize(value):
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^A-Z0-9]", "", text.upper())


def _load(root, name):
    path = Path(root) / "output" / f"dashboard_{name}_cache.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


_CENTRAL_ADMIN_TYPES = {"fortimanager", "fortianalyzer"}
_LICENSE_WARNING_DAYS = 60

_REGIONAL_DEVICE_OVERRIDE = {
    "REG_GLOBAL_SEGURANCA": ["FTG_GLOBALSEG"],
    "REG_GALAXIA": ["FTG_GLX_100F_MATRIZ"],
    "REG_ALAGOAS": ["FTG_REGALAGOAS"],
    "REG_PARA": ["FGT_REGPARA"],
    "REG_ORMEC_PARA": ["FTG_ORMEC_PARA"],
    "REG_SAO_LEOPOLDO": ["FGT_REGSAOLEOPOLDO"],
    "REG_SULZER": ["FTG_REGSULZERTRIUNFO"],
    "REG_SJC": ["FGT_REGSAOJOSEDOSCAMPOS"],
    "REG_LC": ["FGT_GRSA_MACAE"],
}

_REGIONAL_ALIAS = {
    "REG_GALAXIA": ["GLX"],
    "REG_GLOBAL_SEGURANCA": ["GLOBALSEG"],
    "REG_SJC": ["REGSAOJOSEDOSCAMPOS", "SAOJOSEDOSCAMPOS"],
}


def _load_regional_info(root):
    path = Path(root) / "estrutura_regionais.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        regionais = data.get("regionais") or {}
        return regionais if isinstance(regionais, dict) else {}
    except Exception:
        return {}


def _resolve_regional_code(candidate, regionals):
    wanted = _normalize(candidate)
    for regional in regionals:
        if _normalize(regional) == wanted:
            return regional
    return candidate


def _regional_alias_tokens(value):
    raw = str(value or "")
    candidates = [raw]
    words_clean = re.sub(r"\b(REG|REGIONAL|DE|DA|DO|DAS|DOS)\b", " ", raw, flags=re.IGNORECASE)
    candidates.append(words_clean)
    for prefix in ("REG_", "REGIONAL "):
        if raw.upper().startswith(prefix):
            candidates.append(raw[len(prefix):])
    normalized_raw = _normalize(raw)
    if normalized_raw.startswith("REGIONAL"):
        candidates.append(normalized_raw[len("REGIONAL"):])
    if normalized_raw.startswith("REG"):
        without_reg = normalized_raw[len("REG"):]
        candidates.append(without_reg)
        if without_reg.startswith("REGIONAL"):
            candidates.append(without_reg[len("REGIONAL"):])
    return candidates


def _build_regional_matchers(root, firewalls_by_regional):
    regional_info = _load_regional_info(root)
    regional_codes = []
    for code in list(regional_info) + list(firewalls_by_regional):
        if code not in regional_codes:
            regional_codes.append(code)

    matchers = []
    for code in regional_codes:
        info = regional_info.get(code) or {}
        aliases = []
        aliases.extend(_regional_alias_tokens(code))
        if isinstance(info, dict):
            aliases.extend(_regional_alias_tokens(info.get("nome")))
            aliases.extend(_regional_alias_tokens(info.get("descricao")))
        aliases.extend(_REGIONAL_ALIAS.get(_resolve_regional_code(code, regional_codes), []))
        for alias in aliases:
            token = _normalize(alias)
            if token and len(token) >= 2:
                matchers.append((code, token))

    for code, device_names in _REGIONAL_DEVICE_OVERRIDE.items():
        resolved = _resolve_regional_code(code, regional_codes)
        for device_name in device_names:
            token = _normalize(device_name)
            if token:
                matchers.append((resolved, token))
    return regional_codes, matchers


def _kpi(title, icon, target, items):
    cells = "".join(
        f'<div class="kpi-combo-item {css} nav-detail-trigger" data-detail-target="{target}-{action}" '
        f'role="button" tabindex="0"><span>{_escape(label)}</span><strong>{value}</strong></div>'
        for label, value, css, action in items
    )
    return f"""
    <div class="kpi nav-detail-trigger" data-detail-target="{target}" role="button" tabindex="0">
        <div class="kpi-header"><div class="kpi-icon info"><i class="fas {icon}"></i></div><h3>{_escape(title)}</h3></div>
        <div class="kpi-groups"><div class="kpi-group"><div class="kpi-group-title">Monitoramento</div>
        <div class="kpi-group-grid">{cells}</div></div></div>
    </div>"""


def _firewall_availability_status(firewall):
    if str(firewall.get("status_disponibilidade") or firewall.get("status") or "").lower() == "maintenance":
        return "online"
    if str(firewall.get("status_disponibilidade") or "").lower() in {"offline", "inativo", "sem-sinal", "down", "error", "erro"}:
        return "offline"
    if str(firewall.get("status_disponibilidade") or "").lower() in {"online", "ok", "ready", "active", "up"}:
        return "online"

    licencas = firewall.get("licencas") or []
    if any(str(lic.get("status") or "").lower() == "offline" for lic in licencas if isinstance(lic, dict)):
        return "offline"
    return "online"


def _firewall_licence_status(firewall):
    licencas = firewall.get("licencas") or []
    if any(
        isinstance(lic, dict)
        and (
            bool(lic.get("notificacao_expirada"))
            or str(lic.get("status") or "").lower() in {"expired", "no_license"}
        )
        and str(lic.get("status") or "").lower() != "offline"
        for lic in licencas
    ):
        return "expirado"
    if any(
        isinstance(lic, dict)
        and bool(lic.get("notificacao_critica"))
        and not bool(lic.get("notificacao_expirada"))
        and str(lic.get("status") or "").lower() != "offline"
        for lic in licencas
    ):
        return "warning"
    if int(firewall.get("licencas_expiradas") or 0) > 0:
        return "expirado"
    if int(firewall.get("licencas_criticas") or 0) > 0:
        return "warning"
    if any(
        isinstance(lic, dict)
        and isinstance(lic.get("dias_restantes"), (int, float))
        and 0 < lic["dias_restantes"] <= _LICENSE_WARNING_DAYS
        and str(lic.get("status") or "").lower() != "offline"
        for lic in licencas
    ):
        return "warning"
    return "ok"


def _licence_status(licence):
    if not isinstance(licence, dict):
        return "ok"
    if str(licence.get("status") or "").lower() == "offline":
        return "indisponivel"
    status = str(licence.get("status") or "").lower()
    if licence.get("notificacao_expirada") or status in {"expired", "no_license"}:
        return "expirado"
    days = licence.get("dias_restantes")
    if licence.get("notificacao_critica") or (
        isinstance(days, (int, float)) and 0 < days <= _LICENSE_WARNING_DAYS
    ):
        return "warning"
    return "ok"


def _firewall_status(firewall):
    availability_status = _firewall_availability_status(firewall)
    if availability_status == "offline":
        return "sem-sinal"
    return _firewall_licence_status(firewall)


def _admin_status(device):
    if device.get("novos") or device.get("removidos"):
        return "alerta"
    if device.get("sem_permissao"):
        return "sem-permissao"
    # No checklist, o Monitor de Admins deve refletir divergencias de baseline.
    # Falha temporaria ao consultar admins de um FortiGate nao deve aparecer como
    # disponibilidade da regional; isso pertence ao bloco de Firewalls.
    if device.get("offline") and _normalize(device.get("tipo")).lower() in _CENTRAL_ADMIN_TYPES:
        return "offline"
    return "ok"


def _status_badge(status):
    labels = {
        "ok": "OK", "warning": "A vencer", "expirado": "Expirada", "sem-sinal": "Offline",
        "alerta": "Com alerta", "offline": "Offline", "sem-permissao": "Sem permissão",
    }
    css = {
        "ok": "security-ok", "warning": "security-warning", "expirado": "security-danger", "sem-sinal": "security-inactive",
        "alerta": "security-danger", "offline": "security-inactive", "sem-permissao": "security-warning",
    }
    return f'<span class="security-badge {css.get(status, "security-inactive")}">{labels.get(status, status)}</span>'


def _regional_for_device(device_name, device_type, regional_codes, regional_matchers):
    normalized_type = _normalize(device_type).lower()
    if normalized_type == "fortimanager":
        return "FortiManager"
    if normalized_type == "fortianalyzer":
        return "FortiAnalyzer"

    normalized = _normalize(device_name)
    best = "CENTRAL"
    best_len = 0
    for regional, token in regional_matchers:
        if token and len(token) >= 2 and token in normalized and len(token) > best_len:
            best = regional
            best_len = len(token)
    if best != "CENTRAL":
        return _resolve_regional_code(best, regional_codes)
    return best


def _is_central_admin_regional(regional):
    return _normalize(regional).lower() in _CENTRAL_ADMIN_TYPES


def build_security_dashboard(project_root):
    firewall_cache = _load(project_root, "firewalls")
    admin_cache = _load(project_root, "admins")
    active_regionals = set(_load_regional_info(project_root).keys())

    raw_firewalls_by_regional = firewall_cache.get("firewalls_por_regional") or {}
    firewalls_by_regional = {
        regional: entries
        for regional, entries in raw_firewalls_by_regional.items()
        if not active_regionals or regional in active_regionals
    }
    firewalls = []
    for regional, entries in firewalls_by_regional.items():
        for firewall in entries or []:
            item = dict(firewall)
            item["regional"] = regional
            item["dashboard_status"] = _firewall_status(item)
            item["dashboard_availability_status"] = _firewall_availability_status(item)
            item["dashboard_licence_status"] = _firewall_licence_status(item)
            firewalls.append(item)

    fw_counts = {status: sum(1 for item in firewalls if item["dashboard_licence_status"] == status)
                 for status in ("ok", "warning", "expirado")}
    fw_availability_counts = {status: sum(1 for item in firewalls if item["dashboard_availability_status"] == status)
                             for status in ("online", "offline", "maintenance")}
    fw_total = len(firewalls)

    regional_fw = []
    for regional, entries in firewalls_by_regional.items():
        availability_statuses = [_firewall_availability_status(item) for item in entries or []]
        licence_statuses = [_firewall_licence_status(item) for item in entries or []]
        status = "expirado" if "expirado" in licence_statuses else "warning" if "warning" in licence_statuses else "ok"
        regional_fw.append((regional, len(entries or []), status, "offline" if "offline" in availability_statuses else "online"))
    fw_reg_counts = {status: sum(1 for _, _, item_status, _ in regional_fw if item_status == status)
                     for status in ("ok", "warning", "expirado")}
    fw_reg_availability_counts = {status: sum(1 for _, _, _, item_status in regional_fw if item_status == status)
                                 for status in ("online", "offline")}

    admin_devices = admin_cache.get("dispositivos") or {}
    admins = []
    regional_codes, regional_matchers = _build_regional_matchers(project_root, firewalls_by_regional)
    for key, device in admin_devices.items():
        item = dict(device)
        item["key"] = key
        item["dashboard_status"] = _admin_status(item)
        item["regional"] = _regional_for_device(
            item.get("nome") or key,
            item.get("tipo"),
            regional_codes,
            regional_matchers,
        )
        if (
            active_regionals
            and not _is_central_admin_regional(item.get("regional"))
            and item.get("regional") not in active_regionals
        ):
            continue
        admins.append(item)
    admin_counts = {status: sum(1 for item in admins if item["dashboard_status"] == status)
                    for status in ("ok", "alerta", "offline", "sem-permissao")}

    regional_admin_map = {}
    for item in admins:
        if _is_central_admin_regional(item.get("regional")):
            continue
        regional_admin_map.setdefault(item["regional"], []).append(item["dashboard_status"])
    regional_admin = []
    for regional, statuses in regional_admin_map.items():
        status = "alerta" if "alerta" in statuses else "offline" if "offline" in statuses else "sem-permissao" if "sem-permissao" in statuses else "ok"
        regional_admin.append((regional, len(statuses), status))
    admin_reg_counts = {status: sum(1 for _, _, item_status in regional_admin if item_status == status)
                        for status in ("ok", "alerta", "offline", "sem-permissao")}

    firewall_device_kpi = _kpi("Firewalls", "fa-shield-alt", "firewalls", [
        ("Total", fw_total, "status-neutral", "total"),
        ("Online", fw_availability_counts.get("online", 0), "status-online", "fw-online"),
        ("Offline", fw_availability_counts.get("offline", 0), "status-offline", "fw-offline"),
    ])
    firewall_licence_kpi = _kpi("Licenças de Firewalls", "fa-shield-alt", "firewalls", [
        ("Total", fw_total, "status-neutral", "licence-total"),
        ("OK", fw_counts.get("ok", 0), "status-online", "licence-ok"),
        ("A vencer", fw_counts.get("warning", 0), "status-warning", "licence-warning"),
        ("Expiradas", fw_counts.get("expirado", 0), "status-inactive", "licence-expirado"),
    ])
    firewall_regional_kpi = _kpi("Firewalls por Regional", "fa-shield-alt", "firewalls", [
        ("Total", len(regional_fw), "status-neutral", "regional-total"),
        ("Sem alerta", fw_reg_counts["ok"], "status-online", "regional-ok"),
        ("A vencer", fw_reg_counts["warning"], "status-warning", "regional-warning"),
        ("Com expirada", fw_reg_counts["expirado"], "status-inactive", "regional-expirado"),
        ("Com offline", fw_reg_availability_counts.get("offline", 0), "status-offline", "regional-fw-offline"),
    ])
    admin_device_kpi = _kpi("Monitor de Admins", "fa-user-shield", "admin-monitor", [
        ("Total", len(admins), "status-neutral", "total"),
        ("OK", admin_counts["ok"], "status-online", "ok"),
        ("Com alertas", admin_counts["alerta"], "status-offline", "alerta"),
        ("Offline", admin_counts["offline"], "status-inactive", "offline"),
    ])
    admin_regional_kpi = _kpi("Admins por Regional", "fa-user-shield", "admin-monitor", [
        ("Total", len(regional_admin), "status-neutral", "regional-total"),
        ("Sem alerta", admin_reg_counts["ok"], "status-online", "regional-ok"),
        ("Com alerta", admin_reg_counts["alerta"], "status-offline", "regional-alerta"),
        ("Offline", admin_reg_counts["offline"], "status-inactive", "regional-offline"),
    ])

    fw_rows = []
    for item in sorted(firewalls, key=lambda row: (row["regional"], row.get("nome", ""))):
        licenses = item.get("licencas") or [{}]
        for license_info in licenses:
            licence_status = _licence_status(license_info)
            display_status = (
                "sem-sinal"
                if item["dashboard_availability_status"] == "offline"
                else item["dashboard_licence_status"] if not license_info else licence_status
            )
            days = license_info.get("dias_restantes", "N/A")
            license_name = license_info.get("nome") or license_info.get("tipo") or "N/A"
            license_value = license_info.get("status") or "N/A"
            fw_rows.append(
                f'<tr class="security-row" data-status="{display_status}" '
                f'data-fw-status="{item["dashboard_availability_status"]}" data-regional="{_escape(item["regional"])}">'
                f'<td>{_escape(item["regional"])}</td><td><strong>{_escape(item.get("nome"))}</strong></td>'
                f'<td>{_escape(item.get("ip"))}</td><td>{_escape(item.get("model"))}</td><td>{_escape(item.get("serial"))}</td>'
                f'<td>{_escape(license_name)}: {_escape(license_value)}</td><td>{_escape(days)}</td>'
                f'<td>{_status_badge(display_status)}</td></tr>'
            )
    firewall_detail = _table("Firewalls e Licenças", "Regional|Firewall|IP|Modelo|Serial|Licença|Dias restantes|Status", fw_rows, firewall_cache)

    admin_rows = []
    for item in sorted(admins, key=lambda row: (row["regional"], row.get("nome", ""))):
        changes = []
        if item.get("novos"):
            changes.append("Novos: " + ", ".join(map(str, item["novos"])))
        if item.get("removidos"):
            changes.append("Removidos: " + ", ".join(map(str, item["removidos"])))
        admin_rows.append(
            f'<tr class="security-row" data-status="{item["dashboard_status"]}" data-regional="{_escape(item["regional"])}">'
            f'<td>{_escape(item["regional"])}</td><td><strong>{_escape(item.get("nome"))}</strong></td>'
            f'<td>{len(item.get("admins") or [])}</td>'
            f'<td>{_escape("; ".join(changes) or item.get("motivo") or "Sem divergências")}</td>'
            f'<td>{_status_badge(item["dashboard_status"])}</td></tr>'
        )
    admin_detail = _table("Monitor de Admins", "Regional|Dispositivo|Admins|Observação|Status", admin_rows, admin_cache)

    return {
        "firewall_device_kpi": firewall_device_kpi,
        "firewall_licence_kpi": firewall_licence_kpi,
        "firewall_regional_kpi": firewall_regional_kpi,
        "admin_device_kpi": admin_device_kpi,
        "admin_regional_kpi": admin_regional_kpi,
        "firewall_detail": firewall_detail,
        "admin_detail": admin_detail,
        "firewall_counts": fw_counts,
        "firewall_availability_counts": fw_availability_counts,
        "firewall_regional_counts": fw_reg_counts,
        "firewall_regional_availability_counts": fw_reg_availability_counts,
        "admin_counts": admin_counts,
        "admin_regional_counts": admin_reg_counts,
        "firewall_regional_summary": {
            regional: {"total": total, "status": status, "availability": availability_status}
            for regional, total, status, availability_status in regional_fw
        },
        "admin_regional_summary": {
            regional: {"total": total, "status": status}
            for regional, total, status in regional_admin
        },
    }


def _table(title, columns, rows, cache):
    header = "".join(f"<th>{_escape(column)}</th>" for column in columns.split("|"))
    body = "".join(rows) if rows else f'<tr><td colspan="{len(columns.split("|"))}" class="security-empty">Cache ainda não disponível. Atualize a tela correspondente no Sentinel.</td></tr>'
    updated = _escape(cache.get("atualizado_em") or "cache indisponível")
    return f"""
    <div class="security-table-block">
        <div class="security-table-title"><strong>{_escape(title)}</strong><span>Atualizado em: {updated}</span></div>
        <div class="security-table-scroll"><table class="security-table"><thead><tr>{header}</tr></thead><tbody>{body}</tbody></table></div>
        <div class="security-filter-empty" hidden>Nenhum item corresponde ao filtro selecionado.</div>
    </div>"""
