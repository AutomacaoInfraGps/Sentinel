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


def detectar_tipo(sys_descr: str, sys_name: str) -> str:
    descr = (sys_descr or "").lower()
    name = (sys_name or "").lower()

    # iLO (HP / HPE)
    if (
        "integrated lights-out" in descr
        or descr.startswith("ilo")
        or name.startswith("ilo")
        or "hewlett-packard" in descr
        or "hpe" in descr
    ):
        return "ilo"

    # iDRAC (Dell)
    if (
        "idrac" in descr
        or "dell" in descr
        or name.startswith("idrac")
    ):
        return "idrac"

    return "desconhecido"


def main():
    if len(sys.argv) < 3:
        print(json.dumps({
            "success": False,
            "message": "Uso: snmp_worker.py <ip> <community>"
        }))
        return

    ip = sys.argv[1]
    community = sys.argv[2]

    OID_SYS_DESCR  = "1.3.6.1.2.1.1.1.0"
    OID_SYS_NAME   = "1.3.6.1.2.1.1.5.0"
    OID_SYS_UPTIME = "1.3.6.1.2.1.1.3.0"

    sys_descr, _ = snmp_get(ip, OID_SYS_DESCR, community)
    sys_name, _ = snmp_get(ip, OID_SYS_NAME, community)
    sys_uptime, _ = snmp_get(ip, OID_SYS_UPTIME, community)

    if not sys_descr:
        print(json.dumps({
            "success": False,
            "message": "SNMP não respondeu"
        }))
        return

    tipo_detectado = detectar_tipo(sys_descr, sys_name)

    temperaturas = []
    ventoinhas = []

    # 🔥 iLO SNMP real
    if tipo_detectado == "ilo":
        temp, _ = snmp_get(ip, "1.3.6.1.4.1.232.6.2.6.1.0", community)

        if temp and temp.isdigit():
            temperaturas.append({
                "sensor": "System",
                "celsius": int(temp),
                "health": "OK"
            })

    hardware = {
        "controlador": {
            "sysName": sys_name or "N/A",
            "sysDescr": sys_descr or "N/A",
            "uptime": sys_uptime or "N/A",
            "tipo_detectado": tipo_detectado
        },
        "memoria_gib": None,  # ❗ não disponível via SNMP iLO 4
        "cpu": {
            "model": "N/A",
            "count": None,
            "health": "N/A"
        },
        "temperaturas": temperaturas,
        "ventoinhas": ventoinhas
    }

    print(json.dumps({
        "success": True,
        "hardware": hardware
    }, ensure_ascii=False))

if __name__ == "__main__":
    main()
