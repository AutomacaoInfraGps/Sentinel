#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Teste das diferentes abordagens de monitoramento de links
para operadoras que bloqueiam ping/IP de conectividade
"""

from gerenciar_fortigate import GerenciadorFortigate
from gerenciar_regionais import GerenciadorRegionais
import json

def testar_abordagens_monitoramento():
    """Testa diferentes abordagens para monitorar links de operadoras"""

    print("🔍 TESTE DE MONITORAMENTO DE LINKS PARA OPERADORAS")
    print("=" * 60)

    # Inicializar gerenciadores
    gf = GerenciadorFortigate()
    gr = GerenciadorRegionais()

    # Autenticar no Fortigate
    print("🔐 Autenticando no Fortigate...")
    if not gf.autenticar():
        print("❌ Falha na autenticação")
        return
    print("✅ Autenticação bem-sucedida\n")

    # Obter link de exemplo
    codigo_regional = 'RG_GLOBAL_SEGURANCA'
    id_link = 'link_rg_global_seguranca_01'

    print(f"📋 Obtendo link {id_link} da regional {codigo_regional}...")
    link = gr.obter_link(codigo_regional, id_link)
    if not link:
        print("❌ Link não encontrado")
        return

    print(f"Link encontrado: {link['nome']} - IP: {link['ip']} - Provedor: {link['provedor']}\n")

    # Mapeamento da interface (simulando a lógica da API)
    link_nome = link.get("nome", "").upper()
    mapeamento_interfaces = {
        "WAN_CONNECT_01": "wan1",
        "WAN_CONNECT_02": "wan2",
        "WAN1": "wan1",
        "WAN2": "wan2",
    }

    interface_name = None
    for chave, interface in mapeamento_interfaces.items():
        if chave in link_nome:
            interface_name = interface
            break

    if not interface_name:
        print("❌ Não foi possível mapear a interface")
        return

    print(f"🔗 Interface mapeada: {interface_name}\n")

    # ==========================================
    # TESTE 1: Monitoramento Físico (Recomendado para operadoras)
    # ==========================================
    print("🧪 TESTE 1: MONITORAMENTO FÍSICO (Recomendado para operadoras)")
    print("-" * 50)

    resultado_fisico = gf.testar_link_fisico(interface_name, link['ip'])

    print("📊 Resultado:")
    print(json.dumps(resultado_fisico, indent=2, ensure_ascii=False))
    print()

    # ==========================================
    # TESTE 2: Monitoramento SLA (Ping para IP acessível)
    # ==========================================
    print("🧪 TESTE 2: MONITORAMENTO SLA (Ping para IP acessível)")
    print("-" * 50)

    # Testa SLA com Google DNS (IP acessível)
    resultado_sla = gf.testar_link_sla(interface_name, "8.8.8.8")

    print("📊 Resultado:")
    print(json.dumps(resultado_sla, indent=2, ensure_ascii=False))
    print()

    # ==========================================
    # TESTE 3: Monitoramento Completo (Tradicional - falha para operadoras)
    # ==========================================
    print("🧪 TESTE 3: MONITORAMENTO COMPLETO (Tradicional)")
    print("-" * 50)

    resultado_completo = gf.testar_link(interface_name, link['ip'])

    print("📊 Resultado:")
    print(json.dumps(resultado_completo, indent=2, ensure_ascii=False))
    print()

    # ==========================================
    # ANÁLISE COMPARATIVA
    # ==========================================
    print("📈 ANÁLISE COMPARATIVA DOS MÉTODOS")
    print("=" * 50)

    metodos = [
        ("Físico", resultado_fisico),
        ("SLA", resultado_sla),
        ("Completo", resultado_completo)
    ]

    for nome, resultado in metodos:
        if resultado["success"]:
            status = resultado["status"]
            tipo_teste = resultado.get("tipo_teste", "desconhecido")
            print(f"{nome:10} | Status: {status:8} | Tipo: {tipo_teste}")
        else:
            print(f"{nome:10} | Status: ERROR    | Tipo: falhou")

    print()
    print("💡 RECOMENDAÇÕES:")
    print("- Para operadoras que bloqueiam IP/ping: Use MONITORAMENTO FÍSICO")
    print("- Para validar qualidade da conexão: Use MONITORAMENTO SLA")
    print("- Para links locais/acessíveis: Use MONITORAMENTO COMPLETO")
    print()
    print("🔧 A API web agora detecta automaticamente links de operadoras")
    print("   e usa o método apropriado (físico) para evitar falsos positivos!")

if __name__ == "__main__":
    testar_abordagens_monitoramento()