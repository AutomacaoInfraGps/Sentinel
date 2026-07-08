from collections import Counter
from datetime import datetime
from pathlib import Path
import html as html_lib
import json
import re
import subprocess
import unicodedata

from gerenciar_switches import GerenciadorSwitches
from dashboard_security_sections import build_security_dashboard


PROJECT_ROOT = Path(__file__).resolve().parent
SOURCE_DASHBOARD = PROJECT_ROOT / "output" / "dashboard_final.html"
PREVIEW_DASHBOARD = PROJECT_ROOT / "output" / "dashboard_preview_switches.html"


def _friendly_date(value):
    if not value:
        return "N/A"

    text = str(value).strip()
    if not text:
        return "N/A"

    for date_format in (
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%d/%m/%Y %H:%M:%S",
    ):
        try:
            return datetime.strptime(text[:26], date_format).strftime("%d/%m/%Y %H:%M:%S")
        except ValueError:
            pass

    return text.replace("T", " ")[:19]


def _normalize_key(value):
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def _load_current_servers_by_name():
    path = PROJECT_ROOT / "estrutura_regionais.json"
    if not path.exists():
        return {}

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}

    servers = {}
    for regional_code, regional in (data.get("regionais") or {}).items():
        for server in regional.get("servidores", []) or []:
            name = str(server.get("nome") or "").strip()
            if not name:
                continue
            servers[_normalize_key(name)] = {
                "nome": name,
                "ip": str(server.get("ip") or "").strip(),
                "funcao": str(server.get("funcao") or "Servidor Virtual").strip(),
                "regional": str(regional_code or "").strip(),
            }
    return servers


def _ping_responds(ip):
    if not ip:
        return False
    try:
        result = subprocess.run(
            ["ping", "-n", "1", "-w", "3000", ip],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return False

    output = (result.stdout or "").lower()
    if (
        "destination host unreachable" in output
        or "host de destino inacess" in output
        or "request timed out" in output
        or "esgotado o tempo" in output
    ):
        return False
    return "ttl=" in output or "ttl " in output


def _sync_cached_server_cards(html):
    servers = _load_current_servers_by_name()
    if not servers:
        return html

    pattern = re.compile(r'<article class="regional-server-card[^"]*"[^>]*>.*?</article>', re.S | re.I)

    def repl(match):
        card = match.group(0)
        title_match = re.search(r'<div class="regional-server-card-title">(.*?)</div>', card, re.S | re.I)
        if not title_match:
            return card

        title = re.sub(r"<.*?>", "", title_match.group(1)).strip()
        server = servers.get(_normalize_key(title))
        if not server:
            return card

        current_subtitle = re.search(r'<div class="regional-server-card-subtitle">(.*?)</div>', card, re.S | re.I)
        old_ip = ""
        if current_subtitle:
            old_text = re.sub(r"<.*?>", "", current_subtitle.group(1)).strip()
            old_ip_match = re.search(r'(\d{1,3}(?:\.\d{1,3}){3})', old_text)
            old_ip = old_ip_match.group(1) if old_ip_match else ""

        subtitle = f'{html_lib.escape(server["funcao"] or "Servidor Virtual")} - {html_lib.escape(server["ip"] or "N/A")}'
        card = re.sub(
            r'<div class="regional-server-card-subtitle">.*?</div>',
            f'<div class="regional-server-card-subtitle">{subtitle}</div>',
            card,
            count=1,
            flags=re.S | re.I,
        )

        is_cached_offline = "regional-server-card-danger" in card and "Servidor virtual" in card
        ip_changed = bool(old_ip and server["ip"] and old_ip != server["ip"])
        if is_cached_offline and _ping_responds(server["ip"]):
            card = card.replace("regional-server-card-danger", "regional-server-card-warning", 1)
            card = re.sub(r'data-status="[^"]*"', 'data-status="warning"', card, count=1)
            card = card.replace('status-badge danger">OFFLINE', 'status-badge warning">ONLINE', 1)
            cache_message = (
                "[WARN] Cache antigo apontava outro IP; IP atual responde ao ping."
                if ip_changed
                else "[WARN] Cache antigo marcava offline; IP atual responde ao ping."
            )
            card = re.sub(
                r'<div class="regional-server-alert">.*?</div>',
                f'<div class="regional-server-alert">{cache_message}</div>',
                card,
                count=1,
                flags=re.S | re.I,
            )

        return card

    return pattern.sub(repl, html)


def _status_counts(switches):
    counts = Counter((switch.get("status") or "desconhecido").strip().lower() for switch in switches)
    return {
        "online": counts.get("online", 0),
        "offline": sum(counts.get(status, 0) for status in ("offline", "não encontrado", "nao encontrado", "erro")),
        "warning": counts.get("warning", 0),
        "inativo": counts.get("inativo", 0),
    }


def _regional_counts(manager):
    regionais = {}
    for regional, switches in manager.regionais.items():
        counts = _status_counts(switches)
        regionais[regional] = counts

    return {
        "sem_alerta": sum(
            1
            for counts in regionais.values()
            if counts["offline"] == 0 and counts["warning"] == 0 and counts["inativo"] == 0
        ),
        "com_offline": sum(1 for counts in regionais.values() if counts["offline"] > 0),
        "com_warning": sum(1 for counts in regionais.values() if counts["warning"] > 0),
        "com_inativo": sum(1 for counts in regionais.values() if counts["inativo"] > 0),
    }


def _matching_div_end(text, start):
    depth = 0
    for match in re.finditer(r"<div\b|</div>", text[start:], re.IGNORECASE):
        token = match.group(0).lower()
        if token.startswith("<div"):
            depth += 1
        else:
            depth -= 1
            if depth == 0:
                return start + match.end()
    return -1


def _matching_details_end(text, start):
    depth = 0
    for match in re.finditer(r"<details\b|</details>", text[start:], re.IGNORECASE):
        token = match.group(0).lower()
        if token.startswith("<details"):
            depth += 1
        else:
            depth -= 1
            if depth == 0:
                return start + match.end()
    return -1


def _find_card_block(html, title):
    title_pos = html.find(f"<h3>{title}</h3>")
    if title_pos < 0:
        return ""

    card_start = html.rfind('<div class="kpi nav-detail-trigger"', 0, title_pos)
    if card_start < 0:
        return ""

    card_end = _matching_div_end(html, card_start)
    if card_end < 0:
        return ""

    return html[card_start:card_end]


def _value_from_card(card, label, default=0):
    pattern = re.compile(
        rf"<span>\s*{re.escape(label)}\s*</span>\s*<strong>\s*([^<]+)\s*</strong>",
        re.IGNORECASE,
    )
    match = pattern.search(card or "")
    if not match:
        return default

    value = re.sub(r"\D+", "", match.group(1))
    return int(value) if value else default


def _cached_regional_metrics(html, switch_regionais):
    servidores_card = (
        _find_card_block(html, "Regionais com Problema no Servidor")
        or _find_card_block(html, "Servidores")
    )
    aps_card = _find_card_block(html, "APs (Regionais)") or _find_card_block(html, "APs")
    replicacao_card = _find_card_block(html, "Replicação AD") or _find_card_block(html, "Replicação AD por Regional")
    links_card = _find_card_block(html, "Links (Regionais)") or _find_card_block(html, "Links")
    vpn_card = _find_card_block(html, "VPNs IPSEC") or _find_card_block(html, "VPNs por Regional")

    return {
        "servidores_sem_offline": _value_from_card(servidores_card, "Sem offline"),
        "servidores_com_offline": _value_from_card(servidores_card, "Com offline"),
        "servidores_com_warning": _value_from_card(servidores_card, "Com warning"),
        "aps_sem_offline": _value_from_card(aps_card, "Sem AP Offline"),
        "aps_com_offline": _value_from_card(aps_card, "Com AP Offline"),
        "rep_total": _value_from_card(replicacao_card, "Total"),
        "rep_com_falha": _value_from_card(replicacao_card, "Com falha"),
        "rep_sem_falha": _value_from_card(replicacao_card, "Sem falha"),
        "switches_sem_alerta": switch_regionais["sem_alerta"],
        "switches_com_offline": switch_regionais["com_offline"],
        "switches_com_warning": switch_regionais["com_warning"],
        "switches_com_inativo": switch_regionais["com_inativo"],
        "links_sem_offline": _value_from_card(links_card, "Sem offline"),
        "links_com_offline": _value_from_card(links_card, "Com offline"),
        "vpn_sem_offline": _value_from_card(vpn_card, "Sem offline"),
        "vpn_com_offline": _value_from_card(vpn_card, "Com offline"),
    }


def _regional_kpis_html(metrics):
    return f"""
        <div class="kpi-container">
            <div class="kpi nav-detail-trigger" data-detail-target="regionais" role="button" tabindex="0">
                <div class="kpi-header"><div class="kpi-icon error"><i class="fas fa-times-circle"></i></div><h3>Servidores por Regional</h3></div>
                <div class="kpi-groups"><div class="kpi-group"><div class="kpi-group-title">Regionais</div><div class="kpi-group-grid">
                    <div class="kpi-combo-item status-neutral nav-detail-trigger" data-detail-target="regionais" role="button" tabindex="0"><span>Total</span><strong>{metrics["servidores_sem_offline"] + metrics["servidores_com_offline"]}</strong></div>
                    <div class="kpi-combo-item status-online nav-detail-trigger" data-detail-target="regionais-online" role="button" tabindex="0"><span>Sem offline</span><strong>{metrics["servidores_sem_offline"]}</strong></div>
                    <div class="kpi-combo-item status-offline nav-detail-trigger" data-detail-target="regionais-offline" role="button" tabindex="0"><span>Com offline</span><strong>{metrics["servidores_com_offline"]}</strong></div>
                </div></div></div>
            </div>
            <div class="kpi nav-detail-trigger" data-detail-target="unifi" role="button" tabindex="0">
                <div class="kpi-header"><div class="kpi-icon info"><i class="fas fa-wifi"></i></div><h3>APs por Regional</h3></div>
                <div class="kpi-groups"><div class="kpi-group"><div class="kpi-group-title">Regionais</div><div class="kpi-group-grid">
                    <div class="kpi-combo-item status-neutral nav-detail-trigger" data-detail-target="unifi" role="button" tabindex="0"><span>Total</span><strong>{metrics["aps_sem_offline"] + metrics["aps_com_offline"]}</strong></div>
                    <div class="kpi-combo-item status-online nav-detail-trigger" data-detail-target="unifi-online" role="button" tabindex="0"><span>Sem AP Offline</span><strong>{metrics["aps_sem_offline"]}</strong></div>
                    <div class="kpi-combo-item status-offline nav-detail-trigger" data-detail-target="unifi-offline" role="button" tabindex="0"><span>Com AP Offline</span><strong>{metrics["aps_com_offline"]}</strong></div>
                </div></div></div>
            </div>
            <div class="kpi nav-detail-trigger" data-detail-target="replicacao" role="button" tabindex="0">
                <div class="kpi-header"><div class="kpi-icon info"><i class="fas fa-sync-alt"></i></div><h3>Replicação AD por Regional</h3></div>
                <div class="kpi-groups"><div class="kpi-group"><div class="kpi-group-title">Regionais</div><div class="kpi-group-grid">
                    <div class="kpi-combo-item status-neutral nav-detail-trigger" data-detail-target="replicacao" role="button" tabindex="0"><span>Total</span><strong>{metrics["rep_total"]}</strong></div>
                    <div class="kpi-combo-item status-offline nav-detail-trigger" data-detail-target="replicacao" role="button" tabindex="0"><span>Com falha</span><strong>{metrics["rep_com_falha"]}</strong></div>
                    <div class="kpi-combo-item status-online nav-detail-trigger" data-detail-target="replicacao" role="button" tabindex="0"><span>Sem falha</span><strong>{metrics["rep_sem_falha"]}</strong></div>
                </div></div></div>
            </div>
            <div class="kpi nav-detail-trigger" data-detail-target="switches" role="button" tabindex="0">
                <div class="kpi-header"><div class="kpi-icon success"><i class="fas fa-network-wired"></i></div><h3>Switches por Regional</h3></div>
                <div class="kpi-groups"><div class="kpi-group"><div class="kpi-group-title">Regionais</div><div class="kpi-group-grid">
                    <div class="kpi-combo-item status-online nav-detail-trigger" data-detail-target="switches-online" role="button" tabindex="0"><span>Sem alerta</span><strong>{metrics["switches_sem_alerta"]}</strong></div>
                    <div class="kpi-combo-item status-offline nav-detail-trigger" data-detail-target="switches-offline" role="button" tabindex="0"><span>Com offline</span><strong>{metrics["switches_com_offline"]}</strong></div>
                    <div class="kpi-combo-item status-warning nav-detail-trigger" data-detail-target="switches-warning" role="button" tabindex="0"><span>Com warning</span><strong>{metrics["switches_com_warning"]}</strong></div>
                    <div class="kpi-combo-item status-inactive nav-detail-trigger" data-detail-target="switches-inativo" role="button" tabindex="0"><span>Com inativo</span><strong>{metrics["switches_com_inativo"]}</strong></div>
                </div></div></div>
            </div>
            <div class="kpi nav-detail-trigger" data-detail-target="links" role="button" tabindex="0">
                <div class="kpi-header"><div class="kpi-icon info"><i class="fas fa-globe"></i></div><h3>Links por Regional</h3></div>
                <div class="kpi-groups"><div class="kpi-group"><div class="kpi-group-title">Cobertura Regional</div><div class="kpi-group-grid">
                    <div class="kpi-combo-item status-neutral nav-detail-trigger" data-detail-target="links" role="button" tabindex="0"><span>Total</span><strong>{metrics["links_sem_offline"] + metrics["links_com_offline"]}</strong></div>
                    <div class="kpi-combo-item status-online nav-detail-trigger" data-detail-target="links-online" role="button" tabindex="0"><span>Sem offline</span><strong>{metrics["links_sem_offline"]}</strong></div>
                    <div class="kpi-combo-item status-offline nav-detail-trigger" data-detail-target="links-offline" role="button" tabindex="0"><span>Com offline</span><strong>{metrics["links_com_offline"]}</strong></div>
                </div></div></div>
            </div>
            <div class="kpi nav-detail-trigger" data-detail-target="vpn-details" role="button" tabindex="0">
                <div class="kpi-header"><div class="kpi-icon info"><i class="fas fa-shield-alt"></i></div><h3>VPNs por Regional</h3></div>
                <div class="kpi-groups"><div class="kpi-group"><div class="kpi-group-title">Regionais</div><div class="kpi-group-grid">
                    <div class="kpi-combo-item status-neutral nav-detail-trigger" data-detail-target="vpn-details" role="button" tabindex="0"><span>Total</span><strong>{metrics["vpn_sem_offline"] + metrics["vpn_com_offline"]}</strong></div>
                    <div class="kpi-combo-item status-online nav-detail-trigger" data-detail-target="vpn-details-online" role="button" tabindex="0"><span>Sem offline</span><strong>{metrics["vpn_sem_offline"]}</strong></div>
                    <div class="kpi-combo-item status-offline nav-detail-trigger" data-detail-target="vpn-details-offline" role="button" tabindex="0"><span>Com offline</span><strong>{metrics["vpn_com_offline"]}</strong></div>
                </div></div></div>
            </div>
        </div>
"""


def _switches_kpi_html(counts, regionais):
    return f"""
            <div class="kpi nav-detail-trigger" data-detail-target="switches" role="button" tabindex="0">
                <div class="kpi-header">
                    <div class="kpi-icon success">
                        <i class="fas fa-network-wired"></i>
                    </div>
                    <h3>Switches</h3>
                </div>
                <div class="kpi-groups">
                    <div class="kpi-group">
                        <div class="kpi-group-title">Dispositivos</div>
                        <div class="kpi-group-grid">
                            <div class="kpi-combo-item status-online nav-detail-trigger" data-detail-target="switches-online" role="button" tabindex="0"><span>Switches Online</span><strong>{counts["online"]}</strong></div>
                            <div class="kpi-combo-item status-offline nav-detail-trigger" data-detail-target="switches-offline" role="button" tabindex="0"><span>Switches Offline</span><strong>{counts["offline"]}</strong></div>
                            <div class="kpi-combo-item status-warning nav-detail-trigger" data-detail-target="switches-warning" role="button" tabindex="0"><span>Switches Warning</span><strong>{counts["warning"]}</strong></div>
                            <div class="kpi-combo-item status-inactive nav-detail-trigger" data-detail-target="switches-inativo" role="button" tabindex="0"><span>Switches Inativos</span><strong>{counts["inativo"]}</strong></div>
                        </div>
                    </div>
                </div>
            </div>"""


def _ensure_preview_css(html):
    html = html.replace(
        """        .kpi-combo-item.status-inactive {
            background: #edf2f7;
            border-color: #718096;
            box-shadow: inset 0 0 0 1px rgba(74, 85, 104, 0.12);
        }""",
        """        .kpi-combo-item.status-inactive {
            background: #edf2f7;
            border-color: #cbd5e0;
        }""",
    )

    if ".switch-observation" not in html:
        switch_table_css = """
        .links-region-table-counts .warn {
            color: #b7791f;
        }

        .switches-table-header,
        .links-table-header {
            background: linear-gradient(135deg, #012E40 0%, #0A4A63 55%, #0F6C8C 100%);
            color: #ffffff;
        }

        .switches-table-header:hover,
        .links-table-header:hover {
            background: linear-gradient(135deg, #012E40 0%, #0A4A63 55%, #0F6C8C 100%);
        }

        .switches-table-header .links-region-table-title,
        .switches-table-header .links-region-table-count,
        .switches-table-header .links-region-table-counts,
        .links-table-header .links-region-table-title,
        .links-table-header .links-region-table-count,
        .links-table-header .links-region-table-counts {
            color: #ffffff;
        }

        .links-region-table-counts .counter-online,
        .links-region-table-counts .counter-offline,
        .links-region-table-counts .counter-warning,
        .links-region-table-counts .counter-neutral {
            display: inline-flex;
            align-items: center;
            border-radius: 999px;
            padding: 3px 8px;
            font-size: 0.8rem;
            font-weight: 800;
            line-height: 1;
            background: rgba(255, 255, 255, 0.92);
        }

        .links-region-table-counts .counter-online {
            color: #2f855a;
        }

        .links-region-table-counts .counter-offline {
            color: #c53030;
        }

        .links-region-table-counts .counter-warning {
            color: #b7791f;
        }

        .links-region-table-counts .counter-neutral {
            color: #4a5568;
        }

        .switch-observation {
            min-width: 260px;
            max-width: 520px;
            color: #4a5568;
        }

        .status-pill.warning {
            background: #d69e2e;
            color: #1a202c;
        }

        .status-pill.neutral {
            background: #718096;
        }
"""
        html = html.replace("</style>", switch_table_css + "\n</style>", 1)

    if ".kpi-combo-item.status-warning" not in html:
        html = html.replace(
            "        .kpi-combo-item.status-neutral {{",
            """        .kpi-combo-item.status-warning {
            background: #fffbeb;
            border-color: #fbd38d;
        }

        .kpi-combo-item.status-neutral {{""",
        )
    if ".kpi-combo-item.status-inactive" not in html:
        html = html.replace(
            "        .kpi-combo-item.status-neutral {",
            """        .kpi-combo-item.status-inactive {
            background: #edf2f7;
            border-color: #cbd5e0;
        }

        .kpi-combo-item.status-neutral {""",
            1,
        )
    if ".dashboard-view-tabs" not in html:
        html = html.replace(
            "        .kpi-container {",
            """        .dashboard-view-tabs {
            display: inline-flex;
            gap: 6px;
            align-items: center;
            padding: 6px;
            margin: 0 auto 24px;
            border: 1px solid rgba(255, 255, 255, 0.28);
            border-radius: 999px;
            background: rgba(255, 255, 255, 0.22);
            box-shadow: 0 12px 28px rgba(1, 46, 64, 0.18);
        }

        .dashboard-view-tabs-wrap {
            display: flex;
            justify-content: center;
        }

        .dashboard-view-tab {
            border: 0;
            border-radius: 999px;
            padding: 9px 18px;
            background: transparent;
            color: rgba(255, 255, 255, 0.78);
            font-weight: 800;
            font-size: 0.9rem;
            cursor: pointer;
            transition: background 0.2s ease, color 0.2s ease, transform 0.2s ease;
        }

        .dashboard-view-tab:hover {
            color: #ffffff;
            transform: translateY(-1px);
        }

        .dashboard-view-tab.active {
            background: rgba(255, 255, 255, 0.95);
            color: #0A4A63;
            box-shadow: 0 8px 18px rgba(1, 46, 64, 0.16);
        }

        .dashboard-view {
            display: none;
        }

        .dashboard-view.active {
            display: block;
        }

        .kpi-container {""",
        )
    if "#regional-view .kpi-container" not in html:
        regional_css = """        #regional-view .kpi-container {
            grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
            gap: 12px;
            margin-bottom: 22px;
            align-items: stretch;
        }

        #regional-view .kpi {
            min-height: 214px;
            height: 100%;
            box-sizing: border-box;
            border-radius: 10px;
            padding: 14px 16px;
            gap: 8px;
            border: 1px solid rgba(203, 213, 225, 0.78);
            border-top: 3px solid #38a169;
            box-shadow: 0 10px 22px rgba(1, 46, 64, 0.14);
        }

        #regional-view .kpi::before {
            display: none;
        }

        #regional-view .kpi:hover {
            transform: translateY(-3px);
            box-shadow: 0 14px 26px rgba(1, 46, 64, 0.18);
        }

        #regional-view .kpi-header {
            min-height: 32px;
            margin-bottom: 8px;
            gap: 8px;
        }

        #regional-view .kpi-icon {
            display: none;
        }

        #regional-view .kpi-header h3 {
            font-size: 0.74rem;
            font-weight: 800;
            letter-spacing: 0.08em;
            color: #475569;
        }

        #regional-view .kpi-groups {
            gap: 0;
        }

        #regional-view .kpi-group {
            border: 0;
            padding: 0;
            background: transparent;
        }

        #regional-view .kpi-group-title {
            display: none;
        }

        #regional-view .kpi-group-grid,
        #regional-view .kpi-combo-grid {
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 7px;
        }

        #regional-view .kpi-combo-item {
            min-height: 58px;
            border-radius: 7px;
            padding: 8px 9px;
            align-content: center;
        }

        #regional-view .kpi-combo-item span {
            font-size: 0.64rem;
            text-transform: uppercase;
            letter-spacing: 0.04em;
        }

        #regional-view .kpi-combo-item strong {
            font-size: 1.28rem;
            line-height: 1;
        }

"""
        if "        .regionais-parent {" in html:
            html = html.replace("        .regionais-parent {", regional_css + "        .regionais-parent {", 1)
        else:
            html = html.replace("        .kpi-combo-item strong {", regional_css + "        .kpi-combo-item strong {", 1)
    uniform_regional_kpis_css = """
        #regional-view .kpi-container {
            align-items: stretch !important;
        }

        #regional-view .kpi {
            min-height: 214px !important;
            height: 100% !important;
            box-sizing: border-box;
        }

        #regional-view .kpi-header {
            min-height: 32px;
        }
    """
    if uniform_regional_kpis_css.strip() not in html:
        html = html.replace("</style>", uniform_regional_kpis_css + "\n</style>", 1)
    return html


def _ensure_dashboard_views(html, regional_metrics):
    if 'id="device-view"' in html and 'id="regional-view"' in html:
        return html

    parent_marker = '        <div class="regionais-parent'
    kpi_marker = '        <div class="kpi-container"'
    regional_detail_marker = '        <details id="regionais"'
    first_device_detail_marker = '        <details id="gps"'
    main_close_marker = '    </div>\n\n<script>'

    parent_start = html.find(parent_marker)
    kpi_start = html.find(kpi_marker, parent_start)
    regional_detail_start = html.find(regional_detail_marker)
    first_device_detail_start = html.find(first_device_detail_marker, regional_detail_start)

    if min(parent_start, kpi_start, regional_detail_start, first_device_detail_start) < 0:
        raise RuntimeError("Não consegui localizar blocos do dashboard para montar as abas de preview.")

    parent_block = html[parent_start:kpi_start]
    regional_detail_block = html[regional_detail_start:first_device_detail_start]

    html = html[:regional_detail_start] + html[first_device_detail_start:]
    html = html[:parent_start] + html[kpi_start:]

    tabs_html = f"""
        <div class="dashboard-view-tabs-wrap">
            <div class="dashboard-view-tabs" role="tablist" aria-label="Modo de visualização do dashboard">
                <button type="button" class="dashboard-view-tab active" data-dashboard-view-target="device-view" role="tab" aria-selected="true">
                    <i class="fas fa-server"></i> Por dispositivo
                </button>
                <button type="button" class="dashboard-view-tab" data-dashboard-view-target="regional-view" role="tab" aria-selected="false">
                    <i class="fas fa-map-marker-alt"></i> Por regional
                </button>
            </div>
        </div>

        <section id="regional-view" class="dashboard-view" data-dashboard-view="regional">
{parent_block.rstrip()}
{_regional_kpis_html(regional_metrics).rstrip()}
        </section>

        <section id="device-view" class="dashboard-view active" data-dashboard-view="device">
"""

    kpi_start = html.find(kpi_marker)
    if kpi_start < 0:
        raise RuntimeError("Não consegui localizar o bloco KPI depois de preparar as abas.")
    html = html[:kpi_start] + tabs_html + html[kpi_start:]

    main_close = html.find(main_close_marker)
    if main_close < 0:
        raise RuntimeError("Não consegui localizar o fechamento principal do dashboard.")
    html = html[:main_close] + "        </section>\n" + html[main_close:]

    return html


def _remove_kpi_group_by_title(section, title):
    marker = f'<div class="kpi-group-title">{title}</div>'
    while marker in section:
        title_pos = section.find(marker)
        group_start = section.rfind('<div class="kpi-group">', 0, title_pos)
        if group_start < 0:
            break
        group_end = _matching_div_end(section, group_start)
        if group_end < 0:
            break
        section = section[:group_start] + section[group_end:]
    return section


def _remove_card_by_title(section, title):
    title_pos = section.find(f"<h3>{title}</h3>")
    if title_pos < 0:
        return section
    card_start = section.rfind('<div class="kpi nav-detail-trigger"', 0, title_pos)
    if card_start < 0:
        return section
    card_end = _matching_div_end(section, card_start)
    if card_end < 0:
        return section
    return section[:card_start] + section[card_end:]


def _replicacao_device_kpi_html(metrics):
    return f"""
            <div class="kpi nav-detail-trigger" data-detail-target="replicacao" role="button" tabindex="0">
                <div class="kpi-header">
                    <div class="kpi-icon info">
                        <i class="fas fa-sync-alt"></i>
                    </div>
                    <h3>Replicação AD</h3>
                </div>
                <div class="kpi-groups">
                    <div class="kpi-group">
                        <div class="kpi-group-title">Dispositivos</div>
                        <div class="kpi-group-grid">
                            <div class="kpi-combo-item status-neutral nav-detail-trigger" data-detail-target="replicacao" role="button" tabindex="0"><span>Total</span><strong>{metrics["rep_total"]}</strong></div>
                            <div class="kpi-combo-item status-online nav-detail-trigger" data-detail-target="replicacao" role="button" tabindex="0"><span>Servidores OK</span><strong>{metrics["rep_sem_falha"]}</strong></div>
                            <div class="kpi-combo-item status-offline nav-detail-trigger" data-detail-target="replicacao" role="button" tabindex="0"><span>Com falha</span><strong>{metrics["rep_com_falha"]}</strong></div>
                        </div>
                    </div>
                </div>
            </div>
"""


def _clean_device_kpis(html, regional_metrics):
    device_start = html.find('<section id="device-view"')
    charts_start = html.find('<div class="charts-section"', device_start)
    if min(device_start, charts_start) < 0:
        return html

    device_kpis = html[device_start:charts_start]
    device_kpis = _remove_kpi_group_by_title(device_kpis, "Regionais")
    device_kpis = _remove_kpi_group_by_title(device_kpis, "Cobertura Regional")
    device_kpis = device_kpis.replace("<h3>Regionais com Problema no Servidor</h3>", "<h3>Servidores</h3>")
    device_kpis = device_kpis.replace("<h3>APs (Regionais)</h3>", "<h3>APs</h3>")
    device_kpis = device_kpis.replace("<h3>Links (Regionais)</h3>", "<h3>Links</h3>")
    device_kpis = device_kpis.replace("<h3>Switches (Regionais)</h3>", "<h3>Switches</h3>")
    if "<h3>Replicação AD</h3>" not in device_kpis:
        switch_card = '<div class="kpi nav-detail-trigger" data-detail-target="switches"'
        switch_pos = device_kpis.find(switch_card)
        if switch_pos >= 0:
            device_kpis = device_kpis[:switch_pos] + _replicacao_device_kpi_html(regional_metrics) + device_kpis[switch_pos:]

    return html[:device_start] + device_kpis + html[charts_start:]


def _extract_details_block(html, detail_id):
    start = html.find(f'<details id="{detail_id}"')
    if start < 0:
        return html, ""
    end = _matching_details_end(html, start)
    if end < 0:
        return html, ""
    return html[:start] + html[end:], html[start:end]


def _make_details_common(html):
    details_order = [
        "regionais",
        "gps",
        "print-rede",
        "appgate",
        "unifi-clientes",
        "replicacao",
        "unifi",
        "switches",
        "links",
        "vpn-details",
    ]

    blocks = []
    for detail_id in details_order:
        html, block = _extract_details_block(html, detail_id)
        if block:
            if detail_id == "regionais":
                block = re.sub(
                    r"<summary>.*?</summary>",
                    "<summary>[SERVER] Status dos Servidores</summary>",
                    block,
                    count=1,
                    flags=re.DOTALL,
                )
            blocks.append(block.strip())

    if not blocks:
        return html

    html = html.replace('        <hr class="divider">\n\n', "", 1)
    details_html = "\n\n        <hr class=\"divider\">\n\n        " + "\n\n        ".join(blocks) + "\n"
    main_close = html.find("    </div>\n\n<script>")
    if main_close < 0:
        return html + details_html
    return html[:main_close] + details_html + html[main_close:]


def _ensure_dashboard_view_js(html):
    if "function setDashboardView" in html:
        return html.replace("    setDashboardView(dashboardViewForDetail(detailId));\n", "")

    chart_defaults = (
        "Chart.defaults.responsive = true;\n"
        "Chart.defaults.maintainAspectRatio = false; // Important to allow the container to control the aspect ratio\n"
    )
    view_js = """Chart.defaults.responsive = true;
Chart.defaults.maintainAspectRatio = false; // Important to allow the container to control the aspect ratio

function setDashboardView(viewId) {
    const targetId = viewId || 'device-view';
    document.querySelectorAll('.dashboard-view').forEach((view) => {
        view.classList.toggle('active', view.id === targetId);
    });
    document.querySelectorAll('.dashboard-view-tab').forEach((tab) => {
        const active = tab.dataset.dashboardViewTarget === targetId;
        tab.classList.toggle('active', active);
        tab.setAttribute('aria-selected', active ? 'true' : 'false');
    });
}

function dashboardViewForDetail(detailId) {
    return detailId === 'regionais' ? 'regional-view' : 'device-view';
}
"""
    html = html.replace(chart_defaults, view_js, 1)
    html = html.replace(
        "document.querySelectorAll('[data-detail-target]').forEach((elemento) => {",
        """document.querySelectorAll('.dashboard-view-tab').forEach((tab) => {
    tab.addEventListener('click', () => {
        setDashboardView(tab.dataset.dashboardViewTarget);
    });
});

document.querySelectorAll('[data-detail-target]').forEach((elemento) => {""",
        1,
    )
    return html


def _replace_switches_kpi(html, counts, regionais):
    replacement = _switches_kpi_html(counts, regionais)
    device_start = html.find('<section id="device-view"')
    charts_start = html.find('<div class="charts-section"', device_start)
    if min(device_start, charts_start) < 0:
        raise RuntimeError("Não consegui localizar a área de KPIs da aba de dispositivos.")

    prefix = html[:device_start]
    device_kpis = html[device_start:charts_start]
    suffix = html[charts_start:]

    pattern = re.compile(
        r'\s*<div class="kpi nav-detail-trigger" data-detail-target="switches" role="button" tabindex="0">.*?'
        r'(?=\s*<div class="kpi nav-detail-trigger" data-detail-target="links" role="button" tabindex="0">)',
        re.DOTALL,
    )
    device_kpis, replaced = pattern.subn("\n" + replacement + "\n", device_kpis, count=1)
    if not replaced:
        raise RuntimeError("Não encontrei o bloco KPI de Switches no dashboard base.")
    return prefix + device_kpis + suffix


def _replace_switches_chart(html, regionais):
    pattern = re.compile(
        r"new Chart\(document\.getElementById\('chartSwitches'\), \{\s*"
        r"type: 'doughnut',\s*data: \{.*?\},\s*options:",
        re.DOTALL,
    )
    replacement = f"""new Chart(document.getElementById('chartSwitches'), {{
    type: 'doughnut',
    data: {{
        labels: ['Regionais sem alerta', 'Com switch offline', 'Com switch warning', 'Com switch inativo'],
        datasets: [{{
            data: [{regionais["sem_alerta"]}, {regionais["com_offline"]}, {regionais["com_warning"]}, {regionais["com_inativo"]}],
            backgroundColor: ['#0F6C8C', '#e53e3e', '#d69e2e', '#718096'],
            borderColor: '#ffffff',
            borderWidth: 2
        }}]
    }},
    options:"""
    html, replaced = pattern.subn(replacement, html, count=1)
    if not replaced:
        raise RuntimeError("Não encontrei o gráfico chartSwitches no dashboard base.")
    return html


def _split_dashboard_charts(html, regional_metrics):
    security_metrics = build_security_dashboard(PROJECT_ROOT)
    html = html.replace("[DATA] Visão Geral em Gráficos", "Visão Geral em Gráficos")
    html = html.replace("[DATA] VisÃ£o Geral em GrÃ¡ficos", "VisÃ£o Geral em GrÃ¡ficos")

    def card_in_view(view_id, title):
        view_start = html.find(f'<section id="{view_id}"')
        if view_start < 0:
            return ""
        next_view = html.find('<section id="', view_start + 20)
        view_end = next_view if next_view >= 0 else len(html)
        return _find_card_block(html[view_start:view_end], title)

    server_card = card_in_view("device-view", "Servidores")
    ap_card = card_in_view("device-view", "APs")
    replication_card = card_in_view("device-view", "ReplicaÃ§Ã£o AD") or card_in_view("device-view", "Replicação AD")
    switch_card = card_in_view("device-view", "Switches")
    links_card = card_in_view("device-view", "Links")
    vpn_card = card_in_view("device-view", "VPNs IPSEC")
    firewall_card = card_in_view("device-view", "Firewalls e Licenças")
    admin_card = card_in_view("device-view", "Monitor de Admins")
    regional_server_card = card_in_view("regional-view", "Servidores por Regional")
    regional_ap_card = card_in_view("regional-view", "APs por Regional")
    regional_replication_card = card_in_view("regional-view", "ReplicaÃ§Ã£o AD por Regional") or card_in_view("regional-view", "Replicação AD por Regional")
    regional_links_card = card_in_view("regional-view", "Links por Regional")
    regional_vpn_card = card_in_view("regional-view", "VPNs por Regional")
    regional_firewall_card = card_in_view("regional-view", "Firewalls por Regional")
    regional_admin_card = card_in_view("regional-view", "Admins por Regional")

    regional_servers_ok = _value_from_card(regional_server_card, "Sem alerta", _value_from_card(regional_server_card, "Sem offline", regional_metrics["servidores_sem_offline"]))
    regional_servers_offline = _value_from_card(regional_server_card, "Com offline", regional_metrics["servidores_com_offline"])
    regional_servers_warning = _value_from_card(regional_server_card, "Com warning", regional_metrics.get("servidores_com_warning", 0))
    regional_aps_ok = _value_from_card(regional_ap_card, "Sem AP Offline", regional_metrics["aps_sem_offline"])
    regional_aps_offline = _value_from_card(regional_ap_card, "Com AP Offline", regional_metrics["aps_com_offline"])
    regional_replication_ok = _value_from_card(regional_replication_card, "Sem falha", regional_metrics["rep_sem_falha"])
    regional_replication_fail = _value_from_card(regional_replication_card, "Com falha", regional_metrics["rep_com_falha"])
    regional_links_ok = _value_from_card(regional_links_card, "Sem alerta", _value_from_card(regional_links_card, "Sem offline", regional_metrics["links_sem_offline"]))
    regional_links_offline = _value_from_card(regional_links_card, "Com offline", regional_metrics["links_com_offline"])
    regional_links_inactive = _value_from_card(regional_links_card, "Com inativo", regional_metrics.get("links_com_inativo", 0))
    regional_vpn_ok = _value_from_card(regional_vpn_card, "Sem offline", regional_metrics["vpn_sem_offline"])
    regional_vpn_offline = _value_from_card(regional_vpn_card, "Com offline", regional_metrics["vpn_com_offline"])

    device_specs = [
        ("chartDeviceServers", "Servidores", ["Online", "Offline", "Warning"], [_value_from_card(server_card, "Online"), _value_from_card(server_card, "Offline"), _value_from_card(server_card, "Warning")], ["#2f855a", "#e53e3e", "#d69e2e"], ["regionais-online", "regionais-offline", "regionais-warning"], "regionais"),
        ("chartDeviceUnifi", "APs", ["Online", "Offline"], [_value_from_card(ap_card, "APs Online"), _value_from_card(ap_card, "APs Offline")], ["#2f855a", "#e53e3e"], ["unifi-online", "unifi-offline"], "unifi"),
        ("chartDeviceReplicacao", "Replicação AD", ["OK", "Com falha"], [_value_from_card(replication_card, "Servidores OK", regional_metrics["rep_sem_falha"]), _value_from_card(replication_card, "Com falha", regional_metrics["rep_com_falha"])], ["#2f855a", "#e53e3e"], ["replicacao", "replicacao"], "replicacao"),
        ("chartDeviceSwitches", "Switches", ["Online", "Offline", "Warning", "Inativos"], [_value_from_card(switch_card, "Switches Online"), _value_from_card(switch_card, "Switches Offline"), _value_from_card(switch_card, "Switches Warning"), _value_from_card(switch_card, "Switches Inativos")], ["#2f855a", "#e53e3e", "#d69e2e", "#718096"], ["switches-online", "switches-offline", "switches-warning", "switches-inativo"], "switches"),
        ("chartDeviceLinks", "Links de Internet", ["Online", "Offline", "Inativos"], [_value_from_card(links_card, "Online"), _value_from_card(links_card, "Offline"), _value_from_card(links_card, "Inativos")], ["#2f855a", "#e53e3e", "#718096"], ["links-online", "links-offline", "links-inativo"], "links"),
        ("chartDeviceVpn", "Túneis VPN", ["Online", "Offline"], [_value_from_card(vpn_card, "Túneis online"), _value_from_card(vpn_card, "Túneis offline")], ["#2f855a", "#e53e3e"], ["vpn-details-online", "vpn-details-offline"], "vpn-details"),
        ("chartDeviceFirewalls", "Firewalls e Licenças", ["Licenças OK", "A vencer", "Expiradas"], [_value_from_card(firewall_card, "Licenças OK"), _value_from_card(firewall_card, "A vencer"), _value_from_card(firewall_card, "Expiradas")], ["#2f855a", "#d69e2e", "#e53e3e"], ["firewalls-ok", "firewalls-warning", "firewalls-expirado"], "firewalls"),
        ("chartDeviceAdmins", "Monitor de Admins", ["OK", "Com alerta", "Offline", "Visibilidade limitada"], [security_metrics["admin_counts"]["ok"], security_metrics["admin_counts"]["alerta"], security_metrics["admin_counts"]["offline"], security_metrics["admin_counts"]["sem-permissao"]], ["#2f855a", "#e53e3e", "#718096", "#805ad5"], ["admin-monitor-ok", "admin-monitor-alerta", "admin-monitor-offline", "admin-monitor-sem-permissao"], "admin-monitor"),
    ]

    regional_specs = [
        ("chartRegionalServers", "Servidores por Regional", ["Sem alerta", "Com offline", "Com warning"], [regional_servers_ok, regional_servers_offline, regional_servers_warning], ["#2f855a", "#e53e3e", "#d69e2e"], ["regionais-online", "regionais-offline", "regionais-warning"], "regionais"),
        ("chartRegionalUnifi", "APs por Regional", ["Sem AP offline", "Com AP offline"], [regional_aps_ok, regional_aps_offline], ["#2f855a", "#e53e3e"], ["unifi-online", "unifi-offline"], "unifi"),
        ("chartRegionalReplicacao", "Replicação AD por Regional", ["Sem falha", "Com falha"], [regional_replication_ok, regional_replication_fail], ["#2f855a", "#e53e3e"], ["replicacao", "replicacao"], "replicacao"),
        ("chartRegionalSwitches", "Switches por Regional", ["Sem alerta", "Com offline", "Com warning", "Com inativo"], [regional_metrics["switches_sem_alerta"], regional_metrics["switches_com_offline"], regional_metrics["switches_com_warning"], regional_metrics["switches_com_inativo"]], ["#2f855a", "#e53e3e", "#d69e2e", "#718096"], ["switches-online", "switches-offline", "switches-warning", "switches-inativo"], "switches"),
        ("chartRegionalLinks", "Links por Regional", ["Sem alerta", "Com offline", "Com inativo"], [regional_links_ok, regional_links_offline, regional_links_inactive], ["#2f855a", "#e53e3e", "#718096"], ["links-regional-online", "links-regional-offline", "links-regional-inativo"], "links"),
        ("chartRegionalVpn", "VPNs por Regional", ["Sem offline", "Com offline"], [regional_vpn_ok, regional_vpn_offline], ["#2f855a", "#e53e3e"], ["vpn-details-online", "vpn-details-offline"], "vpn-details"),
        ("chartRegionalFirewalls", "Firewalls por Regional", ["Sem alerta", "A vencer", "Com expirada"], [_value_from_card(regional_firewall_card, "Sem alerta"), _value_from_card(regional_firewall_card, "A vencer"), _value_from_card(regional_firewall_card, "Com expirada")], ["#2f855a", "#d69e2e", "#e53e3e"], ["firewalls-regional-ok", "firewalls-regional-warning", "firewalls-regional-expirado"], "firewalls"),
        ("chartRegionalAdmins", "Admins por Regional", ["Sem alerta", "Com alerta", "Offline", "Visibilidade limitada"], [security_metrics["admin_regional_counts"]["ok"], security_metrics["admin_regional_counts"]["alerta"], security_metrics["admin_regional_counts"]["offline"], security_metrics["admin_regional_counts"]["sem-permissao"]], ["#2f855a", "#e53e3e", "#718096", "#805ad5"], ["admin-monitor-regional-ok", "admin-monitor-regional-alerta", "admin-monitor-regional-offline", "admin-monitor-regional-sem-permissao"], "admin-monitor"),
    ]

    def chart_section(specs, extra_class):
        canvases = "\n".join(f'                <div class="chart-wrapper"><canvas id="{spec[0]}"></canvas></div>' for spec in specs)
        return f'''        <div class="charts-section {extra_class}">
            <h2 class="section-title" style="background:none!important;color:#ffffff!important;padding:0!important;border-radius:0!important;cursor:default!important">Visão Geral em Gráficos</h2>
            <div class="charts-grid">
{canvases}
            </div>
        </div>'''

    device_start = html.find('<section id="device-view"')
    device_chart_start = html.find('<div class="charts-section', device_start)
    if device_chart_start >= 0:
        device_chart_end = _matching_div_end(html, device_chart_start)
        html = html[:device_chart_start] + chart_section(device_specs, "charts-section-device") + html[device_chart_end:]

    regional_start = html.find('<section id="regional-view"')
    device_start = html.find('<section id="device-view"', regional_start)
    regional_slice = html[regional_start:device_start]
    regional_chart_start = regional_slice.find('<div class="charts-section')
    if regional_chart_start >= 0:
        absolute_start = regional_start + regional_chart_start
        absolute_end = _matching_div_end(html, absolute_start)
        html = html[:absolute_start] + chart_section(regional_specs, "charts-section-regional") + html[absolute_end:]
    else:
        regional_close = html.rfind('</section>', regional_start, device_start)
        html = html[:regional_close] + chart_section(regional_specs, "charts-section-regional") + "\n\n        " + html[regional_close:]

    first_chart_candidates = [
        html.find("new Chart(document.getElementById('chartRegionais')"),
        html.find("new Chart(document.getElementById('chartDeviceServers')"),
        html.find("const dashboardChartConfigs ="),
    ]
    chart_js_start = min(pos for pos in first_chart_candidates if pos >= 0)
    back_to_top_start = html.find("const backToTopBtn", chart_js_start)
    configs = []
    for spec in regional_specs + device_specs:
        configs.append({"id": spec[0], "title": spec[1], "labels": spec[2], "data": spec[3], "colors": spec[4], "routes": spec[5], "detail": spec[6]})
    chart_js = "const dashboardChartConfigs = " + json.dumps(configs, ensure_ascii=False) + ";\n" + r'''
dashboardChartConfigs.forEach((config) => {
    const canvas = document.getElementById(config.id);
    if (!canvas) return;
    new Chart(canvas, {
        type: 'doughnut',
        data: { labels: config.labels, datasets: [{ data: config.data, backgroundColor: config.colors, borderColor: '#ffffff', borderWidth: 2 }] },
        options: {
            onClick: function(_event, elements) {
                if (elements && elements.length > 0) abrirEIrParaDetalhe(config.routes[elements[0].index] || config.detail);
                else abrirEIrParaDetalhe(config.detail);
            },
            plugins: {
                title: { display: true, text: config.title, font: { size: 16 }, color: '#333' },
                legend: { position: 'bottom', labels: { font: { size: 14 }, color: '#555' } }
            }
        }
    });
});

'''
    if chart_js_start >= 0 and back_to_top_start >= 0:
        html = html[:chart_js_start] + chart_js + html[back_to_top_start:]

    if "Object.values(Chart.instances" not in html:
        html = html.replace(
            "        tab.setAttribute('aria-selected', active ? 'true' : 'false');\n    });\n}",
            "        tab.setAttribute('aria-selected', active ? 'true' : 'false');\n    });\n    setTimeout(() => Object.values(Chart.instances || {}).forEach((chart) => chart.resize()), 0);\n}",
            1,
        )
    return html


def _normalized_switch_status(switch):
    status = str(switch.get("status") or "offline").strip().lower()
    if status in {"não encontrado", "nao encontrado", "erro"}:
        return "offline"
    return status


def _switches_details_html(manager, counts):
    regionais_resumo = {}
    for switch in manager.switches:
        regional = switch.get("regional") or "N/A"
        if regional not in regionais_resumo:
            regionais_resumo[regional] = {"online": 0, "offline": 0, "warning": 0, "inativo": 0, "total": 0}
        status = _normalized_switch_status(switch)
        regionais_resumo[regional]["total"] += 1
        if status in regionais_resumo[regional]:
            regionais_resumo[regional][status] += 1
        else:
            regionais_resumo[regional]["offline"] += 1

    resumo_linhas = ""
    for regional, dados in sorted(regionais_resumo.items()):
        taxa = (dados["online"] / dados["total"] * 100) if dados["total"] else 0
        regional_status = "offline" if dados["offline"] else "warning" if dados["warning"] else "inativo" if dados["inativo"] else "online"
        regional_label = "Com offline" if dados["offline"] else "Com warning" if dados["warning"] else "Com inativo" if dados["inativo"] else "Sem alerta"
        pill_class = {"online": "success", "warning": "warning", "inativo": "neutral"}.get(regional_status, "danger")
        resumo_linhas += f"""
                <tr class="switch-regional-row" data-status="{regional_status}">
                    <td class="lt-nome">{html_lib.escape(str(regional))}</td>
                    <td>{dados["total"]}</td>
                    <td>{dados["online"]}</td>
                    <td>{dados["offline"]}</td>
                    <td>{dados["warning"]}</td>
                    <td>{dados["inativo"]}</td>
                    <td>{taxa:.0f}%</td>
                    <td><span class="status-pill {pill_class}">{regional_label}</span></td>
                </tr>
"""

    linhas = ""
    for switch in sorted(manager.switches, key=lambda item: (str(item.get("regional") or ""), str(item.get("host") or ""))):
        status = _normalized_switch_status(switch)
        pill_class = {"online": "success", "warning": "warning", "inativo": "neutral"}.get(status, "danger")
        warning_lista = switch.get("warning_problemas") or []
        observacao = (
            switch.get("warning_resumo")
            or (warning_lista[0] if warning_lista else "")
            or switch.get("status_reason")
            or "OK"
        )
        if switch.get("status_details") and status in {"offline", "inativo"}:
            observacao = f"{observacao} | {switch.get('status_details')}"

        linhas += f"""
                <tr class="switch-item" data-status="{html_lib.escape(str(status))}" data-regional="{html_lib.escape(str(switch.get('regional') or 'N/A'))}">
                    <td class="lt-nome">{html_lib.escape(str(switch.get("host") or "N/A"))}</td>
                    <td>{html_lib.escape(str(switch.get("regional") or "N/A"))}</td>
                    <td class="lt-ip"><code>{html_lib.escape(str(switch.get("ip") or "N/A"))}</code></td>
                    <td>{html_lib.escape(str(switch.get("zabbix_hostid") or switch.get("hostid") or "N/A"))}</td>
                    <td><span class="status-pill {pill_class}">{html_lib.escape(str(status).title())}</span></td>
                    <td class="lt-check">{html_lib.escape(_friendly_date(switch.get("ultima_verificacao") or ""))}</td>
                    <td class="switch-observation">{html_lib.escape(str(observacao))}</td>
                </tr>
"""

    return f"""
        <details id="switches" class="details-section">
            <summary>Status dos Switches</summary>
            <div class="details-content">
                <div class="switches-container">
                    <div class="links-region-table-block">
                        <div class="links-region-table-header switches-table-header">
                            <span class="links-region-table-title">Resumo geral dos switches</span>
                            <span class="links-region-table-counts">
                                <span class="counter-online">{counts["online"]} online</span>
                                <span class="sep">&nbsp;|&nbsp;</span>
                                <span class="counter-offline">{counts["offline"]} offline</span>
                                <span class="sep">&nbsp;|&nbsp;</span>
                                <span class="counter-warning">{counts["warning"]} warning</span>
                                <span class="sep">&nbsp;|&nbsp;</span>
                                <span class="counter-neutral">{counts["inativo"]} inativos</span>
                            </span>
                        </div>
                        <div class="links-region-table-body" id="switches-offline-regionais">
                            <table class="links-table switches-table">
                                <thead>
                                    <tr>
                                        <th>Regional</th>
                                        <th>Total</th>
                                        <th>Online</th>
                                        <th>Offline</th>
                                        <th>Warning</th>
                                        <th>Inativos</th>
                                        <th>Disponibilidade</th>
                                        <th>Status</th>
                                    </tr>
                                </thead>
                                <tbody>{resumo_linhas}</tbody>
                            </table>
                        </div>
                    </div>

                    <div class="links-region-table-block">
                        <div class="links-region-table-header switches-table-header">
                            <span class="links-region-table-title">Relatório completo dos switches <span class="links-region-table-count">({len(manager.switches)} switches)</span></span>
                        </div>
                        <div class="links-region-table-body">
                            <table class="links-table switches-table">
                                <thead>
                                    <tr>
                                        <th>Switch</th>
                                        <th>Regional</th>
                                        <th>IP</th>
                                        <th>ID Zabbix</th>
                                        <th>Status</th>
                                        <th>Última Verif.</th>
                                        <th>Observação</th>
                                    </tr>
                                </thead>
                                <tbody>{linhas}</tbody>
                            </table>
                        </div>
                    </div>
                </div>
            </div>
        </details>
"""


def _replace_switches_details(html, manager, counts):
    html, _old_block = _extract_details_block(html, "switches")
    replacement = _switches_details_html(manager, counts)
    links_start = html.find('        <details id="links"')
    if links_start >= 0:
        return html[:links_start] + replacement + "\n" + html[links_start:]

    main_close = html.find("    </div>\n\n<script>")
    if main_close >= 0:
        return html[:main_close] + replacement + "\n" + html[main_close:]
    return html + replacement


def _ensure_switches_filter_js(html):
    html = html.replace("display:none'><table", "display:block'><table")
    html = html.replace("display: none'><table", "display:block'><table")
    html = html.replace(
        "next.style.display = 'none';\n            next.querySelectorAll('tr').forEach((tr) => { tr.style.display = ''; });",
        "next.style.display = 'block';\n            next.querySelectorAll('tr').forEach((tr) => { tr.style.display = ''; });",
    )
    html = html.replace(
        "// \"Online\" = regional sem AP offline (somente APs online)\n            showSection = hasOnline && !hasOffline;",
        "showSection = hasOnline;",
    )
    html = html.replace(
        "if (showSection && action === 'offline') {",
        "if (showSection && (action === 'offline' || action === 'online')) {",
    )
    html = html.replace(
        "const isOfflineRow = !!tr.querySelector('.ap-offline');\n                tr.style.display = isOfflineRow ? '' : 'none';",
        "const isHeaderRow = !!tr.querySelector('th');\n                const isMatchingRow = action === 'offline'\n                    ? !!tr.querySelector('.ap-offline')\n                    : !!tr.querySelector('.ap-online');\n                tr.style.display = (isHeaderRow || isMatchingRow) ? '' : 'none';",
    )
    html = html.replace(
        "if (action === 'offline' || action === 'online') {\n            regionalItems.forEach",
        "if (action === 'offline' || action === 'online' || action === 'warning') {\n            regionalItems.forEach",
    )
    if "item.querySelectorAll('.regional-server-card').forEach((card)" not in html:
        html = html.replace(
            """function resetRegionaisSection(detail) {
    detail.querySelectorAll('.regional-item').forEach((item) => {
        item.style.display = '';
    });
}""",
            """function resetRegionaisSection(detail) {
    detail.querySelectorAll('.regional-item').forEach((item) => {
        item.style.display = '';
        item.querySelectorAll('.regional-server-card').forEach((card) => {
            card.style.display = '';
        });
    });
}""",
            1,
        )
        html = html.replace(
            """    if (detailId === 'regionais') {
        const regionalItems = detail.querySelectorAll('.regional-item');
        if (action === 'offline' || action === 'online' || action === 'warning') {
            regionalItems.forEach((item) => {
                const match = item.dataset.status === action;
                item.style.display = match ? '' : 'none';
                item.open = match;
            });
        } else {
            resetRegionaisSection(detail);
        }
    }""",
            """    if (detailId === 'regionais') {
        const regionalItems = detail.querySelectorAll('.regional-item');
        if (action === 'offline' || action === 'online' || action === 'warning') {
            regionalItems.forEach((item) => {
                const serverCards = item.querySelectorAll('.regional-server-card');
                let hasMatchingServer = false;

                if (serverCards.length) {
                    serverCards.forEach((card) => {
                        const cardStatus = card.dataset.status || (
                            card.classList.contains('regional-server-card-danger') ? 'offline' :
                            card.classList.contains('regional-server-card-warning') ? 'warning' :
                            'online'
                        );
                        const matchCard = cardStatus === action;
                        card.style.display = matchCard ? '' : 'none';
                        hasMatchingServer = hasMatchingServer || matchCard;
                    });
                } else {
                    hasMatchingServer = item.dataset.status === action;
                }

                const match = hasMatchingServer || item.dataset.status === action;
                item.style.display = match ? '' : 'none';
                item.open = match;
            });
        } else {
            resetRegionaisSection(detail);
        }
    }""",
            1,
        )
    if "detail.querySelectorAll('.switch-regional-row')" not in html:
        html = html.replace(
            """function resetSwitchesSection(detail) {
    detail.querySelectorAll('.switch-item').forEach((item) => {
        item.style.display = '';
    });
}""",
            """function resetSwitchesSection(detail) {
    detail.querySelectorAll('.switch-item').forEach((item) => {
        item.style.display = '';
    });
    detail.querySelectorAll('.switch-regional-row').forEach((item) => {
        item.style.display = '';
    });
    detail.querySelectorAll('.links-region-table-block').forEach((block) => {
        block.style.display = '';
    });
}""",
            1,
        )
        html = html.replace(
            """    if (detailId === 'switches') {
        const switchItems = detail.querySelectorAll('.switch-item');
        if (['offline', 'online', 'warning', 'inativo'].includes(action)) {
            switchItems.forEach((item) => {
                item.style.display = item.dataset.status === action ? '' : 'none';
            });
        } else {
            resetSwitchesSection(detail);
        }""",
            """    if (detailId === 'switches') {
        const switchItems = detail.querySelectorAll('.switch-item');
        const switchRegionalRows = detail.querySelectorAll('.switch-regional-row');
        if (['offline', 'online', 'warning', 'inativo'].includes(action)) {
            switchItems.forEach((item) => {
                item.style.display = item.dataset.status === action ? '' : 'none';
            });
            switchRegionalRows.forEach((item) => {
                item.style.display = item.dataset.status === action ? '' : 'none';
            });
        } else {
            resetSwitchesSection(detail);
        }""",
            1,
        )
    if "const hasMatch = Array.from(block.querySelectorAll('.link-item')).some" not in html:
        html = html.replace(
            """function resetLinksSection(detail) {
    detail.querySelectorAll('.link-item').forEach((item) => {
        item.style.display = '';
    });
}""",
            """function resetLinksSection(detail) {
    detail.querySelectorAll('.link-item').forEach((item) => {
        item.style.display = '';
    });
    detail.querySelectorAll('.links-region-table-block').forEach((block) => {
        block.style.display = '';
    });
}""",
            1,
        )
        html = html.replace(
            """    if (detailId === 'links') {
        const linkItems = detail.querySelectorAll('.link-item');
        if (action === 'offline' || action === 'online') {
            linkItems.forEach((item) => {
                item.style.display = item.dataset.status === action ? '' : 'none';
            });
        } else {
            resetLinksSection(detail);
        }
    }""",
            """    if (detailId === 'links') {
        const linkItems = detail.querySelectorAll('.link-item');
        if (action === 'offline' || action === 'online') {
            linkItems.forEach((item) => {
                item.style.display = item.dataset.status === action ? '' : 'none';
            });
            detail.querySelectorAll('.links-region-table-block').forEach((block) => {
                const hasMatch = Array.from(block.querySelectorAll('.link-item')).some((item) => item.dataset.status === action);
                block.style.display = hasMatch ? '' : 'none';
            });
        } else {
            resetLinksSection(detail);
        }
    }""",
            1,
        )
    if "detail.querySelectorAll('.vpn-tunnel-row')" not in html:
        html = html.replace(
            """function resetVpnSection(detail) {
    detail.querySelectorAll('.vpn-tunnel-card').forEach((card) => {
        card.style.display = '';
    });
}""",
            """function resetVpnSection(detail) {
    detail.querySelectorAll('.vpn-tunnel-card').forEach((card) => {
        card.style.display = '';
    });
    detail.querySelectorAll('.vpn-tunnel-row').forEach((row) => {
        row.style.display = '';
    });
    detail.querySelectorAll('.vpn-regional-row').forEach((row) => {
        row.style.display = '';
    });
}""",
            1,
        )
        html = html.replace(
            """    if (detailId === 'vpn-details') {
        const tunnelCards = detail.querySelectorAll('.vpn-tunnel-card');
        if (action === 'offline' || action === 'online') {
            tunnelCards.forEach((card) => {
                card.style.display = card.dataset.status === action ? '' : 'none';
            });
        } else {
            resetVpnSection(detail);
        }""",
            """    if (detailId === 'vpn-details') {
        const tunnelCards = detail.querySelectorAll('.vpn-tunnel-card');
        const tunnelRows = detail.querySelectorAll('.vpn-tunnel-row');
        const regionalRows = detail.querySelectorAll('.vpn-regional-row');
        if (action === 'offline' || action === 'online') {
            tunnelCards.forEach((card) => {
                card.style.display = card.dataset.status === action ? '' : 'none';
            });
            tunnelRows.forEach((row) => {
                row.style.display = row.dataset.status === action ? '' : 'none';
            });
            regionalRows.forEach((row) => {
                row.style.display = row.dataset.status === action ? '' : 'none';
            });
        } else {
            resetVpnSection(detail);
        }""",
            1,
        )
    return html


def _style_links_tables(html):
    html = html.replace(
        'class="links-region-table-header" onclick=',
        'class="links-region-table-header links-table-header" onclick=',
    )
    html = html.replace('<tr data-status="online">', '<tr class="link-item" data-status="online">')
    html = html.replace('<tr data-status="offline">', '<tr class="link-item" data-status="offline">')
    html = re.sub(
        r'<span class="ok">(&#x2714; [^<]*? online)</span>',
        r'<span class="counter-online">\1</span>',
        html,
    )
    html = re.sub(
        r'<span class="alert">(&#x2716; [^<]*? offline)</span>',
        r'<span class="counter-offline">\1</span>',
        html,
    )
    return html


def _sync_inactive_links(html):
    detail_start = html.find('<details id="links"')
    if detail_start < 0:
        return html, {"online": 0, "offline": 0, "inativo": 0, "total": 0, "regionais_total": 0, "regionais_sem_alerta": 0, "regionais_com_offline": 0, "regionais_com_inativo": 0}
    detail_end = _matching_details_end(html, detail_start)
    block = html[detail_start:detail_end]

    def classify_row(match):
        row = match.group(0)
        if 'lt-sla-badge inactive' not in row.lower():
            return row
        row = row.replace('data-status="offline"', 'data-status="inativo"', 1)
        row = row.replace('status-pill danger">Offline', 'status-pill neutral">Inativo', 1)
        return row

    block = re.sub(
        r'<tr class="link-item" data-status="offline">.*?</tr>',
        classify_row,
        block,
        flags=re.DOTALL | re.IGNORECASE,
    )

    region_counts = []
    cursor = 0
    while True:
        region_start = block.find('<div class="links-region-table-block"', cursor)
        if region_start < 0:
            break
        region_end = _matching_div_end(block, region_start)
        if region_end < 0:
            break
        region_block = block[region_start:region_end]
        statuses = re.findall(r'class="link-item" data-status="(online|offline|inativo)"', region_block, re.IGNORECASE)
        if statuses:
            counts = Counter(status.lower() for status in statuses)
            region_counts.append(counts)
            header_counts = (
                f'<span class="links-region-table-counts">'
                f'<span class="counter-online">&#x2714; {counts["online"]} online</span>'
                f'<span class="sep">&nbsp;|&nbsp;</span>'
                f'<span class="counter-offline">&#x2716; {counts["offline"]} offline</span>'
                f'<span class="sep">&nbsp;|&nbsp;</span>'
                f'<span class="counter-neutral">{counts["inativo"]} inativo</span>'
                f'</span>'
            )
            region_block = re.sub(
                r'<span class="links-region-table-counts">.*?</span>\s*(?=</div>)',
                header_counts,
                region_block,
                count=1,
                flags=re.DOTALL,
            )
            block = block[:region_start] + region_block + block[region_end:]
            cursor = region_start + len(region_block)
        else:
            cursor = region_end

    all_statuses = re.findall(r'class="link-item" data-status="(online|offline|inativo)"', block, re.IGNORECASE)
    totals = Counter(status.lower() for status in all_statuses)
    counts = {
        "online": totals["online"],
        "offline": totals["offline"],
        "inativo": totals["inativo"],
        "total": len(all_statuses),
        "regionais_total": len(region_counts),
        "regionais_sem_alerta": sum(1 for item in region_counts if item["offline"] == 0 and item["inativo"] == 0),
        "regionais_com_offline": sum(1 for item in region_counts if item["offline"] > 0),
        "regionais_com_inativo": sum(1 for item in region_counts if item["inativo"] > 0),
    }
    return html[:detail_start] + block + html[detail_end:], counts


def _replace_links_kpis(html, counts):
    def replace_grid(card, items):
        grid_start = card.find('<div class="kpi-group-grid">')
        grid_end = _matching_div_end(card, grid_start)
        if grid_start < 0 or grid_end < 0:
            return card
        prefix = card[:grid_start + len('<div class="kpi-group-grid">')]
        suffix = card[grid_end - len('</div>'):]
        return prefix + items + suffix

    device_items = (
        _server_kpi_item("Total", counts["total"], "status-neutral", "links")
        + _server_kpi_item("Online", counts["online"], "status-online", "links-online")
        + _server_kpi_item("Offline", counts["offline"], "status-offline", "links-offline")
        + _server_kpi_item("Inativos", counts["inativo"], "status-inactive", "links-inativo")
    )
    regional_items = (
        _server_kpi_item("Total", counts["regionais_total"], "status-neutral", "links")
        + _server_kpi_item("Sem alerta", counts["regionais_sem_alerta"], "status-online", "links-regional-online")
        + _server_kpi_item("Com offline", counts["regionais_com_offline"], "status-offline", "links-regional-offline")
        + _server_kpi_item("Com inativo", counts["regionais_com_inativo"], "status-inactive", "links-regional-inativo")
    )

    for view_id, title, items in (("device-view", "Links", device_items), ("regional-view", "Links por Regional", regional_items)):
        view_start = html.find(f'<section id="{view_id}"')
        view_end = html.find('<section id="', view_start + 20)
        if view_start < 0:
            continue
        if view_end < 0:
            view_end = len(html)
        section = html[view_start:view_end]
        title_pos = section.find(f'<h3>{title}</h3>')
        if title_pos < 0:
            continue
        card_start = section.rfind('<div class="kpi nav-detail-trigger"', 0, title_pos)
        card_end = _matching_div_end(section, card_start)
        card = section[card_start:card_end]
        section = section[:card_start] + replace_grid(card, items) + section[card_end:]
        html = html[:view_start] + section + html[view_end:]
    return html


def _ensure_inactive_links_filter_js(html):
    start = html.find("    if (detailId === 'links') {")
    end = html.find("    if (detailId === 'vpn-details') {", start)
    if start < 0 or end < 0:
        return html
    replacement = r'''    if (detailId === 'links') {
        const linkItems = detail.querySelectorAll('.link-item');
        if (action.startsWith('regional-')) {
            const regionalStatus = action.replace('regional-', '');
            detail.querySelectorAll('.links-region-table-block').forEach((block) => {
                const rows = Array.from(block.querySelectorAll('.link-item'));
                const hasOffline = rows.some((item) => item.dataset.status === 'offline');
                const hasInactive = rows.some((item) => item.dataset.status === 'inativo');
                const match = regionalStatus === 'offline' ? hasOffline : regionalStatus === 'inativo' ? hasInactive : !hasOffline && !hasInactive;
                block.style.display = match ? '' : 'none';
                rows.forEach((item) => { item.style.display = ''; });
            });
        } else if (action === 'offline' || action === 'online' || action === 'inativo') {
            linkItems.forEach((item) => { item.style.display = item.dataset.status === action ? '' : 'none'; });
            detail.querySelectorAll('.links-region-table-block').forEach((block) => {
                const hasMatch = Array.from(block.querySelectorAll('.link-item')).some((item) => item.dataset.status === action);
                block.style.display = hasMatch ? '' : 'none';
            });
        } else {
            resetLinksSection(detail);
        }
    }

'''
    return html[:start] + replacement + html[end:]


def _server_status_from_block(block):
    lowered = (block or "").lower()
    if "regional-server-card-danger" in lowered or "error-container" in lowered or "[error]" in lowered:
        return "offline"
    if (
        "regional-server-card-warning" in lowered
        or "regional-server-security-warning" in lowered
        or "[warn]" in lowered
        or "bitdefender" in lowered and ("indispon" in lowered or "sem confirma" in lowered)
        or "rpc server is unavailable" in lowered
    ):
        return "warning"
    return "online"


def _server_status_from_card(card):
    lowered = (card or "").lower()
    if "regional-server-card-danger" in lowered or "[error]" in lowered:
        return "offline"
    if (
        "regional-server-card-warning" in lowered
        or "regional-server-security-warning" in lowered
        or "[warn]" in lowered
        or "bitdefender" in lowered and ("indispon" in lowered or "sem confirma" in lowered)
        or "rpc server is unavailable" in lowered
    ):
        return "warning"
    return "online"


def _ensure_server_card_status_attrs(item):
    pattern = re.compile(r'<article class="regional-server-card[^"]*"(?![^>]*data-status=)[^>]*>.*?</article>', re.S | re.I)

    def repl(match):
        card = match.group(0)
        status = _server_status_from_card(card)
        insert_at = card.find(">")
        if insert_at < 0:
            return card
        return card[:insert_at] + f' data-status="{status}"' + card[insert_at:]

    return pattern.sub(repl, item)


def _replace_kpi_card_block(html, title, transform):
    title_pos = html.find(f"<h3>{title}</h3>")
    if title_pos < 0:
        return html
    card_start = html.rfind('<div class="kpi nav-detail-trigger"', 0, title_pos)
    if card_start < 0:
        return html
    card_end = _matching_div_end(html, card_start)
    if card_end < 0:
        return html
    card = html[card_start:card_end]
    return html[:card_start] + transform(card) + html[card_end:]


def _server_kpi_item(label, value, status_class, target):
    return f'<div class="kpi-combo-item {status_class} nav-detail-trigger" data-detail-target="{target}" role="button" tabindex="0"><span>{label}</span><strong>{value}</strong></div>'


def _fix_server_warning_preview(html):
    start = html.find('<details id="regionais"')
    if start < 0:
        return html
    end = _matching_details_end(html, start)
    if end < 0:
        return html

    block = html[start:end]
    server_online = server_offline = server_warning = 0
    regional_online = regional_offline = regional_warning = 0

    rebuilt = []
    cursor = 0
    marker = '<details class="regional-item"'
    while True:
        item_start = block.find(marker, cursor)
        if item_start < 0:
            rebuilt.append(block[cursor:])
            break
        item_end = _matching_details_end(block, item_start)
        if item_end < 0:
            rebuilt.append(block[cursor:])
            break

        rebuilt.append(block[cursor:item_start])
        item = block[item_start:item_end]
        item = _ensure_server_card_status_attrs(item)
        item_server_counts = {
            "online": len(re.findall(r'<article class="regional-server-card[^"]*"[^>]*data-status="online"', item, re.I)),
            "offline": len(re.findall(r'<article class="regional-server-card[^"]*"[^>]*data-status="offline"', item, re.I)),
            "warning": len(re.findall(r'<article class="regional-server-card[^"]*"[^>]*data-status="warning"', item, re.I)),
        }
        server_online += item_server_counts["online"]
        server_offline += item_server_counts["offline"]
        server_warning += item_server_counts["warning"]

        status = _server_status_from_block(item)
        if status == "offline":
            regional_offline += 1
        elif status == "warning":
            regional_warning += 1
        else:
            regional_online += 1
        rebuilt.append(re.sub(r'data-status="[^"]*"', f'data-status="{status}"', item, count=1))
        cursor = item_end

    block = "".join(rebuilt)
    html = html[:start] + block + html[end:]

    def transform_device(card):
        grid_start = card.find('<div class="kpi-group-grid">')
        grid_end = _matching_div_end(card, grid_start)
        if grid_start < 0 or grid_end < 0:
            return card
        prefix = card[:grid_start + len('<div class="kpi-group-grid">')]
        suffix = card[grid_end - len('</div>'):]
        items = (
            _server_kpi_item("Total", server_online + server_offline + server_warning, "status-neutral", "regionais")
            + _server_kpi_item("Online", server_online, "status-online", "regionais-online")
            + _server_kpi_item("Offline", server_offline, "status-offline", "regionais-offline")
            + _server_kpi_item("Warning", server_warning, "status-warning", "regionais-warning")
        )
        return prefix + items + suffix

    def transform_regional(card):
        total = regional_online + regional_offline + regional_warning
        sem_alerta = regional_online
        com_offline = regional_offline
        com_warning = regional_warning
        grid_start = card.find('<div class="kpi-group-grid">')
        grid_end = _matching_div_end(card, grid_start)
        if grid_start < 0 or grid_end < 0:
            return card
        prefix = card[:grid_start + len('<div class="kpi-group-grid">')]
        suffix = card[grid_end - len('</div>'):]
        items = (
            _server_kpi_item("Total", total, "status-neutral", "regionais")
            + _server_kpi_item("Sem alerta", sem_alerta, "status-online", "regionais-online")
            + _server_kpi_item("Com offline", com_offline, "status-offline", "regionais-offline")
            + _server_kpi_item("Com warning", com_warning, "status-warning", "regionais-warning")
        )
        return prefix + items + suffix

    html = _replace_kpi_card_block(html, "Servidores", transform_device)
    html = _replace_kpi_card_block(html, "Servidores por Regional", transform_regional)
    return html


def _ensure_total_item_for_card(html, title, target, total):
    def transform(card):
        grid_start = card.find('<div class="kpi-group-grid">')
        grid_end = _matching_div_end(card, grid_start)
        if grid_start < 0 or grid_end < 0:
            return card

        grid = card[grid_start:grid_end]
        if "<span>Total</span>" in grid:
            return card

        insert_at = grid_start + len('<div class="kpi-group-grid">')
        total_item = _server_kpi_item("Total", total, "status-neutral", target)
        return card[:insert_at] + total_item + card[insert_at:]

    return _replace_kpi_card_block(html, title, transform)


def _ensure_device_total_kpis(html):
    aps_regional_card = _find_card_block(html, "APs por Regional")
    aps_regional_total = _value_from_card(aps_regional_card, "Sem AP Offline") + _value_from_card(aps_regional_card, "Com AP Offline")
    html = _ensure_total_item_for_card(html, "APs por Regional", "unifi", aps_regional_total)

    links_regional_card = _find_card_block(html, "Links por Regional")
    links_regional_total = _value_from_card(links_regional_card, "Sem offline") + _value_from_card(links_regional_card, "Com offline")
    html = _ensure_total_item_for_card(html, "Links por Regional", "links", links_regional_total)

    vpn_regional_card = _find_card_block(html, "VPNs por Regional")
    vpn_regional_total = _value_from_card(vpn_regional_card, "Sem offline") + _value_from_card(vpn_regional_card, "Com offline")
    html = _ensure_total_item_for_card(html, "VPNs por Regional", "vpn-details", vpn_regional_total)

    aps_card = _find_card_block(html, "APs")
    aps_total = _value_from_card(aps_card, "APs Online") + _value_from_card(aps_card, "APs Offline")
    html = _ensure_total_item_for_card(html, "APs", "unifi", aps_total)

    links_card = _find_card_block(html, "Links")
    links_total = _value_from_card(links_card, "Online") + _value_from_card(links_card, "Offline")
    html = _ensure_total_item_for_card(html, "Links", "links", links_total)

    vpn_card = _find_card_block(html, "VPNs IPSEC")
    vpn_total = _value_from_card(vpn_card, "Túneis online") + _value_from_card(vpn_card, "Túneis offline")
    if vpn_total == 0:
        vpn_total = _value_from_card(vpn_card, "Tuneis online") + _value_from_card(vpn_card, "Tuneis offline")
    html = _ensure_total_item_for_card(html, "VPNs IPSEC", "vpn-details", vpn_total)

    return html


def _normalize_switch_inactive_kpi_class(html):
    return re.sub(
        r'class="kpi-combo-item status-neutral nav-detail-trigger"([^>]*data-detail-target="switches-inativo")',
        r'class="kpi-combo-item status-inactive nav-detail-trigger"\1',
        html,
    )


def _normalize_replication_kpi_order(html):
    def transform(card):
        total = _value_from_card(card, "Total")
        ok = _value_from_card(card, "Servidores OK", _value_from_card(card, "Sem falha"))
        fail = _value_from_card(card, "Com falha")

        grid_start = card.find('<div class="kpi-group-grid">')
        grid_end = _matching_div_end(card, grid_start)
        if grid_start < 0 or grid_end < 0:
            return card

        prefix = card[:grid_start + len('<div class="kpi-group-grid">')]
        suffix = card[grid_end - len('</div>'):]
        items = (
            _server_kpi_item("Total", total, "status-neutral", "replicacao")
            + _server_kpi_item("Servidores OK", ok, "status-online", "replicacao")
            + _server_kpi_item("Com falha", fail, "status-offline", "replicacao")
        )
        return prefix + items + suffix

    for title in ("Replicação AD", "ReplicaÃ§Ã£o AD"):
        html = _replace_kpi_card_block(html, title, transform)
    return html


def _vpn_details_to_table(html):
    current_start = html.find('<details id="vpn-details"')
    if current_start >= 0:
        current_end = _matching_details_end(html, current_start)
        if current_end >= 0:
            current_block = html[current_start:current_end]
            if "vpn-tunnel-row" in current_block and "vpn-regional-row" in current_block:
                return html

    html, old_block = _extract_details_block(html, "vpn-details")
    if not old_block:
        return html

    total = _text_number(re.search(r"Total de t[^<]*?</strong>\s*([0-9]+)", old_block, re.IGNORECASE))
    online = _text_number(re.search(r"Online:</strong>\s*([0-9]+)", old_block, re.IGNORECASE))
    offline = _text_number(re.search(r"Offline:</strong>\s*([0-9]+)", old_block, re.IGNORECASE))
    regionais_offline = _text_number(re.search(r"Regionais com VPN offline:</strong>\s*([0-9]+)", old_block, re.IGNORECASE))

    resumo_linhas = ""
    for match in re.finditer(
        r'<div class="vpn-regional-badge[^"]*">.*?<strong>(.*?)</strong><br>\s*(?:<small>(.*?)</small><br>)?\s*<span class="ok">Online:\s*([0-9]+)</span>\s*\|\s*<span class="alert">Offline:\s*([0-9]+)</span>',
        old_block,
        re.IGNORECASE | re.DOTALL,
    ):
        regional = re.sub(r"<.*?>", "", match.group(1)).strip()
        reg_online = int(match.group(3))
        reg_offline = int(match.group(4))
        reg_total = reg_online + reg_offline
        taxa = (reg_online / reg_total * 100) if reg_total else 0
        status = "offline" if reg_offline else "online"
        label = "Com offline" if reg_offline else "Sem offline"
        resumo_linhas += f"""
                <tr class="vpn-regional-row" data-status="{status}">
                    <td class="lt-nome">{html_lib.escape(regional)}</td>
                    <td>{reg_total}</td>
                    <td>{reg_online}</td>
                    <td>{reg_offline}</td>
                    <td>{taxa:.0f}%</td>
                    <td><span class="status-pill {'danger' if status == 'offline' else 'success'}">{label}</span></td>
                </tr>
"""

    tuneis_linhas = ""
    for group_match in re.finditer(r'<div class="vpn-regional-group">\s*<h4>(.*?)</h4>(.*?)</div>\s*(?=<div class="vpn-regional-group">|</div>\s*</div>\s*</details>)', old_block, re.IGNORECASE | re.DOTALL):
        regional = re.sub(r"<.*?>", "", group_match.group(1)).strip()
        group_body = group_match.group(2)
        for tunnel_match in re.finditer(
            r'<div class="vpn-tunnel-card vpn-(online|offline)"[^>]*>\s*<strong>(.*?)</strong>\s*<span[^>]*>(.*?)</span>',
            group_body,
            re.IGNORECASE | re.DOTALL,
        ):
            status = tunnel_match.group(1).lower()
            tunnel = re.sub(r"<.*?>", "", tunnel_match.group(2)).strip()
            tuneis_linhas += f"""
                <tr class="vpn-tunnel-row" data-status="{status}">
                    <td class="lt-nome">{html_lib.escape(tunnel)}</td>
                    <td>{html_lib.escape(regional)}</td>
                    <td><span class="status-pill {'success' if status == 'online' else 'danger'}">{status.upper()}</span></td>
                </tr>
"""

    replacement = f"""
        <details id="vpn-details" class="details-section">
            <summary>[FORTIGATE] Status VPNs IPSEC</summary>
            <div class="details-content">
                <div class="vpn-container">
                    <div class="links-region-table-block">
                        <div class="links-region-table-header links-table-header">
                            <span class="links-region-table-title">Resumo geral das VPNs IPSEC</span>
                            <span class="links-region-table-counts">
                                <span class="counter-online">{online} online</span>
                                <span class="sep">&nbsp;|&nbsp;</span>
                                <span class="counter-offline">{offline} offline</span>
                                <span class="sep">&nbsp;|&nbsp;</span>
                                <span class="counter-neutral">{regionais_offline} regionais com offline</span>
                            </span>
                        </div>
                        <div class="links-region-table-body" id="vpn-offline-regionais">
                            <table class="links-table vpn-table">
                                <thead><tr><th>Regional</th><th>Total</th><th>Online</th><th>Offline</th><th>Disponibilidade</th><th>Status</th></tr></thead>
                                <tbody>{resumo_linhas}</tbody>
                            </table>
                        </div>
                    </div>
                    <div class="links-region-table-block">
                        <div class="links-region-table-header links-table-header">
                            <span class="links-region-table-title">Relatório completo das VPNs IPSEC <span class="links-region-table-count">({total} túneis)</span></span>
                        </div>
                        <div class="links-region-table-body">
                            <table class="links-table vpn-table">
                                <thead><tr><th>Túnel</th><th>Regional</th><th>Status</th></tr></thead>
                                <tbody>{tuneis_linhas}</tbody>
                            </table>
                        </div>
                    </div>
                </div>
            </div>
        </details>
"""
    links_pos = html.find('        <details id="vpn-details"')
    if links_pos >= 0:
        return html[:links_pos] + replacement + html[links_pos:]
    main_close = html.find("    </div>\n\n<script>")
    return html[:main_close] + replacement + html[main_close:] if main_close >= 0 else html + replacement


def _text_number(match):
    if not match:
        return 0
    value = re.sub(r"\D+", "", match.group(1))
    return int(value) if value else 0


def _inject_security_dashboard(html):
    blocks = build_security_dashboard(PROJECT_ROOT)
    if 'id="firewalls"' in html or 'id="admin-monitor"' in html:
        replacements = {
            "firewalls": ("Firewalls e Licenças", blocks["firewall_detail"]),
            "admin-monitor": ("Monitor de Admins", blocks["admin_detail"]),
        }
        for detail_id, (title, content) in replacements.items():
            replacement = (
                f'<details id="{detail_id}" class="details-section"><summary>{title}</summary>'
                f'<div class="details-content">{content}</div></details>'
            )
            html = re.sub(
                rf'<details id="{re.escape(detail_id)}" class="details-section">.*?</details>',
                replacement,
                html,
                count=1,
                flags=re.DOTALL,
            )

        for title, replacement in (
            ("Firewalls e Licenças", blocks["firewall_device_kpi"]),
            ("Monitor de Admins", blocks["admin_device_kpi"]),
            ("Firewalls por Regional", blocks["firewall_regional_kpi"]),
            ("Admins por Regional", blocks["admin_regional_kpi"]),
        ):
            html = _replace_security_kpi(html, title, replacement)
        return html

    markers = [
        ('<div class="charts-section charts-section-regional">', blocks["firewall_regional_kpi"] + blocks["admin_regional_kpi"]),
        ('<div class="charts-section">', blocks["firewall_device_kpi"] + blocks["admin_device_kpi"]),
    ]
    for marker, content in markers:
        marker_pos = html.find(marker)
        if marker_pos < 0:
            continue
        container_close = html.rfind("</div>", 0, marker_pos)
        if container_close >= 0:
            html = html[:container_close] + content + "\n" + html[container_close:]

    details = f"""
    <details id="firewalls" class="details-section"><summary>Firewalls e Licenças</summary>
    <div class="details-content">{blocks['firewall_detail']}</div></details>
    <details id="admin-monitor" class="details-section"><summary>Monitor de Admins</summary>
    <div class="details-content">{blocks['admin_detail']}</div></details>
    """
    main_close = html.find("    </div>\n\n<script>")
    if main_close >= 0:
        html = html[:main_close] + details + html[main_close:]

    css = """
    <style>
    .security-table-block{overflow:hidden;border:1px solid #cbd5e1;border-radius:7px;background:#fff}.security-table-title{display:flex;justify-content:space-between;gap:16px;padding:14px 16px;background:#084a61;color:#fff}.security-table-title span{font-size:.78rem;opacity:.85}.security-table-scroll{overflow-x:auto}.security-table{width:100%;border-collapse:collapse;font-size:.84rem}.security-table th{padding:10px 12px;text-align:left;color:#475569;background:#f1f5f9;text-transform:uppercase;font-size:.72rem}.security-table td{padding:10px 12px;border-top:1px solid #dbe2ea;color:#334155}.security-badge{display:inline-block;border-radius:999px;padding:4px 9px;font-size:.7rem;font-weight:800;text-transform:uppercase}.security-ok{color:#166534;background:#dcfce7}.security-warning{color:#854d0e;background:#fef3c7}.security-danger{color:#991b1b;background:#fee2e2}.security-inactive{color:#334155;background:#e2e8f0}.security-empty,.security-filter-empty{padding:28px;text-align:center;color:#64748b}
    </style>
    """
    html = html.replace("</head>", css + "</head>", 1)

    js = """
    <script>
    function filterPreviewSecurity(detail, action){
      const rows=Array.from(detail.querySelectorAll('.security-row')); let visible=0;
      if(!action||action==='total'||action==='regional-total'){rows.forEach(r=>r.style.display='');visible=rows.length;}
      else if(action.startsWith('regional-')){
        const expected=action.replace('regional-',''), groups={};
        rows.forEach(r=>(groups[r.dataset.regional||'CENTRAL']??=[]).push(r));
        Object.values(groups).forEach(group=>{const s=group.map(r=>r.dataset.status);const status=s.includes('expirado')?'expirado':s.includes('warning')?'warning':s.includes('alerta')?'alerta':s.includes('offline')?'offline':s.includes('sem-permissao')?'sem-permissao':'ok';const show=status===expected;group.forEach(r=>r.style.display=show?'':'none');if(show)visible+=group.length;});
      } else rows.forEach(r=>{const show=r.dataset.status===action;r.style.display=show?'':'none';if(show)visible++;});
      const empty=detail.querySelector('.security-filter-empty');if(empty)empty.hidden=visible>0;
    }
    document.querySelectorAll('[data-detail-target^="firewalls"],[data-detail-target^="admin-monitor"]').forEach(control=>control.addEventListener('click',()=>{const target=control.dataset.detailTarget;const id=target.startsWith('admin-monitor')?'admin-monitor':'firewalls';const detail=document.getElementById(id);if(!detail)return;const action=target.slice(id.length).replace(/^-/,'');detail.open=true;filterPreviewSecurity(detail,action);}));
    </script>
    """
    return html.replace("</body>", js + "</body>", 1)


def _replace_security_kpi(html, title, replacement):
    heading_pos = html.find(f"<h3>{title}</h3>")
    if heading_pos < 0:
        return html
    start = html.rfind('<div class="kpi ', 0, heading_pos)
    if start < 0:
        return html

    depth = 0
    for match in re.finditer(r"<div\b|</div>", html[start:]):
        token = match.group(0)
        depth += 1 if token.startswith("<div") else -1
        if depth == 0:
            end = start + match.end()
            return html[:start] + replacement + html[end:]
    return html


def _move_security_details_to_end(html):
    """Mantem os relatorios de seguranca depois do bloco de VPNs."""
    security_blocks = []

    for detail_id in ("firewalls", "admin-monitor"):
        start = html.find(f'<details id="{detail_id}"')
        if start < 0:
            continue

        depth = 0
        end = None
        for match in re.finditer(r"<details\b|</details>", html[start:]):
            depth += 1 if match.group(0).startswith("<details") else -1
            if depth == 0:
                end = start + match.end()
                break

        if end is not None:
            security_blocks.append(html[start:end])
            html = html[:start] + html[end:]

    if not security_blocks:
        return html

    vpn_start = html.find('<details id="vpn-details"')
    if vpn_start < 0:
        return html

    depth = 0
    vpn_end = None
    for match in re.finditer(r"<details\b|</details>", html[vpn_start:]):
        depth += 1 if match.group(0).startswith("<details") else -1
        if depth == 0:
            vpn_end = vpn_start + match.end()
            break

    if vpn_end is None:
        return html

    ordered_blocks = "\n" + "\n".join(security_blocks)
    return html[:vpn_end] + ordered_blocks + html[vpn_end:]


def main():
    if not SOURCE_DASHBOARD.exists():
        raise FileNotFoundError(f"Dashboard base não encontrado: {SOURCE_DASHBOARD}")

    manager = GerenciadorSwitches()
    counts = _status_counts(manager.switches)
    regionais = _regional_counts(manager)

    html = SOURCE_DASHBOARD.read_text(encoding="utf-8", errors="ignore")
    html, link_counts = _sync_inactive_links(html)
    regional_metrics = _cached_regional_metrics(html, regionais)
    regional_metrics.update({
        "links_sem_offline": link_counts["regionais_sem_alerta"],
        "links_com_offline": link_counts["regionais_com_offline"],
        "links_com_inativo": link_counts["regionais_com_inativo"],
    })
    html = _ensure_preview_css(html)
    html = _ensure_dashboard_views(html, regional_metrics)
    html = _ensure_dashboard_view_js(html)
    html = _clean_device_kpis(html, regional_metrics)
    html = _replace_links_kpis(html, link_counts)
    html = _replace_switches_kpi(html, counts, regionais)
    html = _replace_switches_details(html, manager, counts)
    html = _make_details_common(html)
    html = _sync_cached_server_cards(html)
    html = _fix_server_warning_preview(html)
    html = _ensure_device_total_kpis(html)
    html = _normalize_replication_kpi_order(html)
    html = _normalize_switch_inactive_kpi_class(html)
    html = _inject_security_dashboard(html)
    html = _vpn_details_to_table(html)
    html = _move_security_details_to_end(html)
    if "chartSwitches" in html:
        html = _replace_switches_chart(html, regionais)
    html = _split_dashboard_charts(html, regional_metrics)
    html = _ensure_switches_filter_js(html)
    html = _ensure_inactive_links_filter_js(html)
    html = _style_links_tables(html)
    html = html.replace("<summary>[WEB] Status dos Links de Internet</summary>", "<summary>Status dos Links de Internet</summary>")
    html = html.replace("</body>", "<!-- Preview rapido de switches gerado sem executar todas as coletas. -->\n</body>")

    PREVIEW_DASHBOARD.write_text(html, encoding="utf-8")

    print(f"Preview gerado: {PREVIEW_DASHBOARD}")
    print(f"Switches: online={counts['online']} offline={counts['offline']} warning={counts['warning']} inativos={counts['inativo']}")
    print(
        "Regionais: "
        f"sem_alerta={regionais['sem_alerta']} "
        f"com_offline={regionais['com_offline']} "
        f"com_warning={regionais['com_warning']} "
        f"com_inativo={regionais['com_inativo']}"
    )


if __name__ == "__main__":
    main()
