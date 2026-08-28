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


def apply_device_maintenance(devices, maintenance_hosts, status_field="status"):
    """Marca dispositivos offline quando o IP esta em manutencao direta."""
    result = deepcopy(devices or [])
    hosts_by_ip = {
        normalize_ip(host.get("ip")): host
        for host in maintenance_hosts or []
        if normalize_ip(host.get("ip"))
    }
    for device in result:
        current = str(device.get(status_field) or device.get("status") or "").strip().lower()
        controller = str(
            device.get("status_controladora") if current == MAINTENANCE_STATUS else current
        ).strip().lower()
        host = hosts_by_ip.get(normalize_ip(device.get("ip")))
        if not host or controller != "offline":
            device[status_field] = controller or current
            if status_field != "status" and str(device.get("status") or "").lower() == MAINTENANCE_STATUS:
                device["status"] = controller or current
            device["em_manutencao"] = False
            for field in ("status_controladora", "maintenance_source", "zabbix_hostid", "zabbix_host", "maintenanceid"):
                device.pop(field, None)
            continue
        device["status_controladora"] = controller
        device[status_field] = MAINTENANCE_STATUS
        device["status"] = MAINTENANCE_STATUS
        device["em_manutencao"] = True
        device["maintenance_source"] = "zabbix"
        device["zabbix_hostid"] = host.get("hostid")
        device["zabbix_host"] = host.get("name") or host.get("host")
        device["maintenanceid"] = host.get("maintenanceid")
    return result


def apply_zabbix_maintenance(unifi_data, maintenance_hosts):
    """Sobrepoe o status UniFi quando o IP esta em manutencao no Zabbix."""
    result = deepcopy(unifi_data or {})
    hosts_by_ip = {}
    for host in maintenance_hosts or []:
        host_ip = normalize_ip(host.get("ip"))
        if host_ip:
            hosts_by_ip[host_ip] = host

    aps = apply_device_maintenance(result.get("aps") or [], hosts_by_ip.values())

    result["aps"] = aps
    result["total_aps"] = len(aps)
    result["aps_online"] = sum(1 for ap in aps if str(ap.get("status")).lower() == "online")
    result["aps_offline"] = sum(1 for ap in aps if str(ap.get("status")).lower() == "offline")
    result["aps_maintenance"] = sum(1 for ap in aps if ap.get("em_manutencao"))
    return result
