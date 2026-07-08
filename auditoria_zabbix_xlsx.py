#!/usr/bin/env python3
"""
Auditoria completa: comparar XLSX vs API Zabbix
"""

import json
from gerenciar_switches import GerenciadorSwitches

def auditoria_completa():
    """Auditoria total de regionais e switches"""

    gerenciador = GerenciadorSwitches()

    print("=" * 100)
    print("[AUDITORIA] COMPARACAO: XLSX vs API ZABBIX")
    print("=" * 100)

    if not gerenciador.autenticar():
        print("[ERRO] Falha na autenticacao")
        return

    # =========== DADOS DO XLSX ===========
    print("\n[XLSX] Dados carregados do arquivo...")
    xlsx_regionais = set(gerenciador.regionais.keys())
    xlsx_total_switches = len(gerenciador.switches)

    print(f"[XLSX] Total de regionais: {len(xlsx_regionais)}")
    print(f"[XLSX] Total de switches: {xlsx_total_switches}")
    print(f"\n[XLSX] Regionais carregadas:")
    for regional in sorted(xlsx_regionais)[:15]:
        count = len(gerenciador.regionais[regional])
        print(f"   - {regional}: {count} switches")
    if len(xlsx_regionais) > 15:
        print(f"   ... e mais {len(xlsx_regionais) - 15} regionais")

    # =========== DADOS DA API ===========
    print("\n" + "=" * 100)
    print("[API] Buscando dados do Zabbix...")

    hostgroup_resp = gerenciador._call_api("hostgroup.get", {
        "output": ["groupid", "name"],
        "sortfield": "name"
    })

    hostgroups = hostgroup_resp.get("result", [])
    print(f"[API] Total de host groups no Zabbix: {len(hostgroups)}")

    # =========== MAPEAR HOSTS POR GRUPO ===========
    print("\n[API] Buscando hosts por group...")

    api_data = {}
    total_hosts_api = 0

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
        api_data[group_name] = {
            "groupid": groupid,
            "hosts_count": len(hosts),
            "hosts": [h["name"] for h in hosts]
        }
        total_hosts_api += len(hosts)

    print(f"[API] Total de hosts encontrados: {total_hosts_api}")

    # =========== COMPARACAO ===========
    print("\n" + "=" * 100)
    print("[COMPARACAO] XLSX vs API")
    print("=" * 100)

    print(f"\nRegionais no XLSX: {len(xlsx_regionais)}")
    print(f"Host groups na API: {len(api_data)}")
    print(f"Switches no XLSX: {xlsx_total_switches}")
    print(f"Hosts na API: {total_hosts_api}")

    # =========== GRUPOS FALTANDO ===========
    print("\n[DIFERENCA] Host groups na API que NAO estao no XLSX:")
    grupos_faltando = set(api_data.keys()) - xlsx_regionais
    if grupos_faltando:
        for grupo in sorted(grupos_faltando):
            count = api_data[grupo]["hosts_count"]
            print(f"   - {grupo}: {count} hosts")
    else:
        print("   (Nenhum)")

    print("\n[DIFERENCA] Host groups no XLSX que NAO estao na API:")
    grupos_excel_extra = xlsx_regionais - set(api_data.keys())
    if grupos_excel_extra:
        for grupo in sorted(grupos_excel_extra):
            count = len(gerenciador.regionais[grupo])
            print(f"   - {grupo}: {count} switches")
    else:
        print("   (Nenhum)")

    # =========== DETALHES DOS SWITCHES ===========
    print("\n" + "=" * 100)
    print("[SWITCHES] Comparacao detalhada")
    print("=" * 100)

    print("\nDados dos switches no XLSX (primeiros 10):")
    for i, switch in enumerate(gerenciador.switches[:10]):
        print(f"   {i+1}. {switch['host']} | Regional: {switch['regional']} | IP: {switch['ip']}")

    print("\nDados dos hosts na API (primeiros 10):")
    count = 0
    for group_name in sorted(api_data.keys()):
        for host_name in api_data[group_name]["hosts"]:
            if count < 10:
                print(f"   {count+1}. {host_name} | Group: {group_name}")
                count += 1
            else:
                break
        if count >= 10:
            break

    # =========== RESUMO ===========
    print("\n" + "=" * 100)
    print("[RESUMO]")
    print("=" * 100)
    print(f"""
XLSX:
  - Regionais: {len(xlsx_regionais)}
  - Switches: {xlsx_total_switches}

ZABBIX API:
  - Host groups: {len(api_data)}
  - Hosts: {total_hosts_api}

DIFERENCA:
  - Host groups extras na API: {len(grupos_faltando)}
  - Hosts faltando: {total_hosts_api - xlsx_total_switches}

POSSIVEL CAUSA:
  1. Usuario 'monitor' pode nao ter permissao para ver todos os hosts/grupos
  2. Alguns grupos no XLSX podem nao estar sincronizados com Zabbix
  3. XLSX pode ter dados desatualizados ou duplicados
    """)

    # =========== TESTE DE PERMISSOES ===========
    print("\n" + "=" * 100)
    print("[PERMISSOES] Verificando acesso do usuario...")
    print("=" * 100)

    user_resp = gerenciador._call_api("user.get", {
        "output": ["userid", "username", "name"],
        "selectUserGroups": ["usrgrpid", "name"],
        "selectMediaTypes": ["mediatypeid", "name"]
    })

    if user_resp.get("result"):
        user = user_resp["result"][0]
        print(f"\nUsuario: {user.get('username')} ({user.get('name')})")
        print(f"User ID: {user.get('userid')}")
        print(f"Grupos de usuario:")
        for group in user.get("selectUserGroups", []):
            print(f"   - {group['name']}")
    else:
        print("[AVISO] Nao conseguiu buscar info do usuario")

if __name__ == "__main__":
    auditoria_completa()
