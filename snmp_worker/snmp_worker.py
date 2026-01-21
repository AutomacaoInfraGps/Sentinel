import json
import sys
from pysnmp.hlapi import (
    SnmpEngine, CommunityData, UdpTransportTarget,
    ContextData, ObjectType, ObjectIdentity, getCmd
)

def snmp_get(ip: str, oid: str, community: str, timeout: int = 2, retries: int = 1):
    iterator = getCmd(
        SnmpEngine(),
        CommunityData(community, mpModel=1),  # SNMP v2c
        UdpTransportTarget((ip, 161), timeout=timeout, retries=retries),
        ContextData(),
        ObjectType(ObjectIdentity(oid))
    )

    errorIndication, errorStatus, errorIndex, varBinds = next(iterator)

    if errorIndication:
        return None, str(errorIndication)

    if errorStatus:
        return None, f"{errorStatus.prettyPrint()} at {errorIndex}"

    for varBind in varBinds:
        return str(varBind[1]), None

    return None, "Empty response"


def main():
    if len(sys.argv) < 3:
        print(json.dumps({
            "success": False,
            "message": "Uso: snmp_worker.py <ip> <community>"
        }))
        return

    ip = sys.argv[1]
    community = sys.argv[2]

    # OIDs básicos
    OID_SYS_DESCR  = "1.3.6.1.2.1.1.1.0"
    OID_SYS_NAME   = "1.3.6.1.2.1.1.5.0"
    OID_SYS_UPTIME = "1.3.6.1.2.1.1.3.0"

    sys_descr, err1 = snmp_get(ip, OID_SYS_DESCR, community)
    sys_name, err2 = snmp_get(ip, OID_SYS_NAME, community)
    sys_uptime, err3 = snmp_get(ip, OID_SYS_UPTIME, community)

    if not sys_descr and not sys_name:
        print(json.dumps({
            "success": False,
            "message": "SNMP não respondeu (verifique community / SNMP habilitado / firewall porta 161)",
            "details": err1 or err2 or err3
        }))
        return

    # Detecta tipo básico (opcional)
    tipo_detectado = "desconhecido"
    if sys_descr:
        txt = sys_descr.lower()
        if "idrac" in txt or "dell" in txt:
            tipo_detectado = "idrac"
        elif "ilo" in txt or "hp" in txt or "hpe" in txt:
            tipo_detectado = "ilo"

    hardware = {
        "controlador": {
            "sysName": sys_name or "N/A",
            "sysDescr": sys_descr or "N/A",
            "uptime": sys_uptime or "N/A",
            "tipo_detectado": tipo_detectado
        },
        "memoria_gib": None,
        "cpu": {
            "model": "N/A",
            "count": None,
            "health": "N/A"
        },
        "temperaturas": [],
        "ventoinhas": []
    }

    print(json.dumps({
        "success": True,
        "hardware": hardware
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
