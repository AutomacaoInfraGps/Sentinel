#!/usr/bin/env python3
"""
Script para testar a conexão com o Zabbix
"""

from gerenciar_switches import GerenciadorSwitches

def main():
    """Função principal"""
    print("=" * 50)
    print("🔍 Testando conexão com o Zabbix")
    print("=" * 50)
    
    # Cria o gerenciador de switches
    gerenciador = GerenciadorSwitches()
    
    # Tenta autenticar
    print("\n🔑 Tentando autenticar no Zabbix...")
    if gerenciador.autenticar():
        print("✅ Autenticação bem-sucedida!")
        
        # Testa uma chamada API simples
        print("\n📡 Testando chamada API (host.get)...")
        result = gerenciador._call_api("host.get", {
            "output": ["hostid", "name", "status"],
            "limit": 5
        })
        
        if "result" in result:
            hosts = result["result"]
            print(f"✅ Chamada API bem-sucedida! Encontrados {len(hosts)} hosts:")
            for host in hosts:
                status = "ativo" if host["status"] == "0" else "inativo"
                print(f"   - {host['name']} ({status})")
        else:
            print(f"❌ Erro na chamada API: {result.get('error', 'Desconhecido')}")
    else:
        print("❌ Falha na autenticação!")
    
    print("\n" + "=" * 50)

if __name__ == "__main__":
    main()