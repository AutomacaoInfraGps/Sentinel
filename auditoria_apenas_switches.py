#!/usr/bin/env python3
"""
Auditoria: buscar apenas SWITCHES (filtrar por nome)
"""

from gerenciar_switches import GerenciadorSwitches

def auditoria_switches_apenas():
    """Auditoria apenas de switches da API"""

    gerenciador = GerenciadorSwitches()

    print("=" * 100)
    print("[AUDITORIA] APENAS SWITCHES - XLSX vs API ZABBIX")
    print("=" * 100)

    if not gerenciador.autenticar():
        print("[ERRO] Falha na autenticacao")
        return

    # Dados do XLSX
    print("\n[XLSX] Dados carregados do arquivo...")
    xlsx_total = len(gerenciador.switches)
    print(f"[XLSX] Total de switches: {xlsx_total}")

    # Dados da API - APENAS SWITCHES
    print("\n[API] Buscando APENAS hosts com SWITCH no nome...")

    hostgroup_resp = gerenciador._call_api("hostgroup.get", {
        "output": ["groupid", "name"],
        "sortfield": "name"
    })

    hostgroups = hostgroup_resp.get("result", [])

    api_switches = []
    api_by_group = {}

    for hostgroup in hostgroups:
        groupid = hostgroup["groupid"]
        group_name = hostgroup["name"]

        hosts_resp = gerenciador._call_api("host.get", {
            "groupids": [groupid],
            "output": ["hostid", "name", "status"],
            "selectInterfaces": ["ip"],
            "sortfield": "name"
        })

        hosts = hosts_resp.get("result", [])

        # Filtra APENAS hosts com "SWITCH" no nome
        switches_group = [h for h in hosts if "SWITCH" in h["name"].upper()]

        if switches_group:
            api_by_group[group_name] = {
                "groupid": groupid,
                "switches_count": len(switches_group),
                "switches": switches_group
            }
            api_switches.extend(switches_group)

    print(f"[API] Total de switches encontrados: {len(api_switches)}")
    print(f"[API] Host groups com switches: {len(api_by_group)}")

    # Comparacao
    print("\n" + "=" * 100)
    print("[COMPARACAO]")
    print("=" * 100)

    print(f"\nXLSX switches: {xlsx_total}")
    print(f"API switches: {len(api_switches)}")
    print(f"Diferenca: {len(api_switches) - xlsx_total}")

    # Listar grupos com switches
    print("\n[API] Host groups com switches:")
    for group_name in sorted(api_by_group.keys()):
        count = api_by_group[group_name]["switches_count"]
        print(f"   - {group_name}: {count} switches")

    # Amostra de switches
    print("\n[AMOSTRA] Primeiros 15 switches da API:")
    for i, host in enumerate(api_switches[:15]):
        interfaces = host.get("interfaces", [])
        ip = interfaces[0]["ip"] if interfaces else "N/A"
        status = "Online" if host.get("status") == "0" else "Offline"
        print(f"   {i+1}. {host['name']} | IP: {ip} | Status: {status}")

    # Comparacao de nomes
    print("\n[ANALISE] Comparando nomes XLSX vs API...")

    xlsx_names = set(s["host"] for s in gerenciador.switches)
    api_names = set(h["name"] for h in api_switches)

    switches_so_em_xlsx = xlsx_names - api_names
    switches_so_em_api = api_names - xlsx_names

    if switches_so_em_xlsx:
        print(f"\n[XLSX APENAS] {len(switches_so_em_xlsx)} switches:")
        for switch in list(switches_so_em_xlsx)[:10]:
            print(f"   - {switch}")
        if len(switches_so_em_xlsx) > 10:
            print(f"   ... e mais {len(switches_so_em_xlsx) - 10}")
    else:
        print(f"\n[OK] Todos os switches do XLSX estao na API!")

    if switches_so_em_api:
        print(f"\n[API APENAS] {len(switches_so_em_api)} switches:")
        for switch in list(switches_so_em_api)[:10]:
            print(f"   - {switch}")
        if len(switches_so_em_api) > 10:
            print(f"   ... e mais {len(switches_so_em_api) - 10}")

    # Resumo
    print("\n" + "=" * 100)
    print("[CONCLUSAO]")
    print("=" * 100)
    print(f"""
XLSX tem {xlsx_total} switches
API tem {len(api_switches)} switches (filtrando por 'SWITCH' no nome)
Diferenca: {len(api_switches) - xlsx_total}

Se a diferenca for pequena (< 10):
  -> Os dados estao em sync, pode proceder com a migracao
  -> Usar filtro "SWITCH" no nome para trazer dados da API

Se a diferenca for grande (> 10):
  -> Verificar permissoes do usuario 'monitor'
  -> Verificar se a API retorna todos os hosts esperados
  -> Considerar usar usuario com permissoes adm
    """)

if __name__ == "__main__":
    auditoria_switches_apenas()
