"""Regras de conciliacao de status entre controladoras e o Zabbix."""

from copy import deepcopy
import ipaddress


MAINTENANCE_STATUS = "maintenance"


def normalize_ip(value):
    """Retorna a representacao canonica de um IP ou uma string vazia."""
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        return str(ipaddress.ip_address(text))
    except ValueError:
        return ""


def apply_zabbix_maintenance(unifi_data, maintenance_hosts):
    """Sobrepoe o status UniFi quando o IP esta em manutencao no Zabbix."""
    result = deepcopy(unifi_data or {})
    hosts_by_ip = {}
    for host in maintenance_hosts or []:
        host_ip = normalize_ip(host.get("ip"))
        if host_ip:
            hosts_by_ip[host_ip] = host

    aps = result.get("aps") or []
    for ap in aps:
        current_status = str(ap.get("status") or "").strip().lower()
        controller_status = str(
            ap.get("status_controladora") if current_status == MAINTENANCE_STATUS else current_status
        ).strip().lower()
        ap_ip = normalize_ip(ap.get("ip"))
        zabbix_host = hosts_by_ip.get(ap_ip)
        if not zabbix_host or controller_status != "offline":
            ap["status"] = controller_status or current_status
            ap["em_manutencao"] = False
            for field in (
                "status_controladora", "maintenance_source", "zabbix_hostid",
                "zabbix_host", "maintenanceid",
            ):
                ap.pop(field, None)
            continue

        ap["status_controladora"] = controller_status
        ap["status"] = MAINTENANCE_STATUS
        ap["em_manutencao"] = True
        ap["maintenance_source"] = "zabbix"
        ap["zabbix_hostid"] = zabbix_host.get("hostid")
        ap["zabbix_host"] = zabbix_host.get("name") or zabbix_host.get("host")
        ap["maintenanceid"] = zabbix_host.get("maintenanceid")

    result["aps"] = aps
    result["total_aps"] = len(aps)
    result["aps_online"] = sum(1 for ap in aps if str(ap.get("status")).lower() == "online")
    result["aps_offline"] = sum(1 for ap in aps if str(ap.get("status")).lower() == "offline")
    result["aps_maintenance"] = sum(1 for ap in aps if ap.get("em_manutencao"))
    return result
