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


def _firewall_status(firewall):
    if int(firewall.get("licencas_expiradas") or 0) > 0:
        return "expirado"
    if int(firewall.get("licencas_criticas") or 0) > 0:
        return "warning"
    return "ok"


def _admin_status(device):
    if device.get("novos") or device.get("removidos"):
        return "alerta"
    if device.get("offline"):
        return "offline"
    if device.get("sem_permissao"):
        return "sem-permissao"
    return "ok"


def _status_badge(status):
    labels = {
        "ok": "OK", "warning": "A vencer", "expirado": "Expirada",
        "alerta": "Com alerta", "offline": "Offline", "sem-permissao": "Sem permissão",
    }
    css = {
        "ok": "security-ok", "warning": "security-warning", "expirado": "security-danger",
        "alerta": "security-danger", "offline": "security-inactive", "sem-permissao": "security-warning",
    }
    return f'<span class="security-badge {css.get(status, "security-inactive")}">{labels.get(status, status)}</span>'


def _regional_for_device(device_name, regionals):
    normalized = _normalize(device_name)
    best = "CENTRAL"
    best_len = 0
    for regional in regionals:
        token = _normalize(str(regional).removeprefix("REG_"))
        if token and len(token) >= 2 and token in normalized and len(token) > best_len:
            best = regional
            best_len = len(token)
    return best


def build_security_dashboard(project_root):
    firewall_cache = _load(project_root, "firewalls")
    admin_cache = _load(project_root, "admins")

    firewalls_by_regional = firewall_cache.get("firewalls_por_regional") or {}
    firewalls = []
    for regional, entries in firewalls_by_regional.items():
        for firewall in entries or []:
            item = dict(firewall)
            item["regional"] = regional
            item["dashboard_status"] = _firewall_status(item)
            firewalls.append(item)

    fw_counts = {status: sum(1 for item in firewalls if item["dashboard_status"] == status)
                 for status in ("ok", "warning", "expirado")}
    fw_total = len(firewalls)

    regional_fw = []
    for regional, entries in firewalls_by_regional.items():
        statuses = [_firewall_status(item) for item in entries or []]
        status = "expirado" if "expirado" in statuses else "warning" if "warning" in statuses else "ok"
        regional_fw.append((regional, len(entries or []), status))
    fw_reg_counts = {status: sum(1 for _, _, item_status in regional_fw if item_status == status)
                     for status in ("ok", "warning", "expirado")}

    admin_devices = admin_cache.get("dispositivos") or {}
    admins = []
    regional_names = list(firewalls_by_regional)
    for key, device in admin_devices.items():
        item = dict(device)
        item["key"] = key
        item["dashboard_status"] = _admin_status(item)
        item["regional"] = _regional_for_device(item.get("nome") or key, regional_names)
        admins.append(item)
    admin_counts = {status: sum(1 for item in admins if item["dashboard_status"] == status)
                    for status in ("ok", "alerta", "offline", "sem-permissao")}

    regional_admin_map = {}
    for item in admins:
        regional_admin_map.setdefault(item["regional"], []).append(item["dashboard_status"])
    regional_admin = []
    for regional, statuses in regional_admin_map.items():
        status = "alerta" if "alerta" in statuses else "offline" if "offline" in statuses else "sem-permissao" if "sem-permissao" in statuses else "ok"
        regional_admin.append((regional, len(statuses), status))
    admin_reg_counts = {status: sum(1 for _, _, item_status in regional_admin if item_status == status)
                        for status in ("ok", "alerta", "offline", "sem-permissao")}

    firewall_device_kpi = _kpi("Firewalls e Licenças", "fa-shield-alt", "firewalls", [
        ("Total", fw_total, "status-neutral", "total"),
        ("Licenças OK", fw_counts["ok"], "status-online", "ok"),
        ("A vencer", fw_counts["warning"], "status-warning", "warning"),
        ("Expiradas", fw_counts["expirado"], "status-offline", "expirado"),
    ])
    firewall_regional_kpi = _kpi("Firewalls por Regional", "fa-shield-alt", "firewalls", [
        ("Total", len(regional_fw), "status-neutral", "regional-total"),
        ("Sem alerta", fw_reg_counts["ok"], "status-online", "regional-ok"),
        ("A vencer", fw_reg_counts["warning"], "status-warning", "regional-warning"),
        ("Com expirada", fw_reg_counts["expirado"], "status-offline", "regional-expirado"),
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
        license_info = next(iter(item.get("licencas") or []), {})
        days = license_info.get("dias_restantes", "N/A")
        fw_rows.append(
            f'<tr class="security-row" data-status="{item["dashboard_status"]}" data-regional="{_escape(item["regional"])}">'
            f'<td>{_escape(item["regional"])}</td><td><strong>{_escape(item.get("nome"))}</strong></td>'
            f'<td>{_escape(item.get("ip"))}</td><td>{_escape(item.get("model"))}</td><td>{_escape(item.get("serial"))}</td>'
            f'<td>{_escape(license_info.get("status"))}</td><td>{_escape(days)}</td><td>{_status_badge(item["dashboard_status"])}</td></tr>'
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
            f'<td>{_escape(item["regional"])}</td><td>{_escape(item.get("tipo"))}</td>'
            f'<td><strong>{_escape(item.get("nome"))}</strong></td><td>{len(item.get("admins") or [])}</td>'
            f'<td>{_escape("; ".join(changes) or item.get("motivo") or "Sem divergências")}</td>'
            f'<td>{_status_badge(item["dashboard_status"])}</td></tr>'
        )
    admin_detail = _table("Monitor de Admins", "Regional|Tipo|Dispositivo|Admins|Observação|Status", admin_rows, admin_cache)

    return {
        "firewall_device_kpi": firewall_device_kpi,
        "firewall_regional_kpi": firewall_regional_kpi,
        "admin_device_kpi": admin_device_kpi,
        "admin_regional_kpi": admin_regional_kpi,
        "firewall_detail": firewall_detail,
        "admin_detail": admin_detail,
        "firewall_counts": fw_counts,
        "firewall_regional_counts": fw_reg_counts,
        "admin_counts": admin_counts,
        "admin_regional_counts": admin_reg_counts,
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
