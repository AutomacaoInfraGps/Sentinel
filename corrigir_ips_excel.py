#!/usr/bin/env python3
"""
Script para corrigir os IPs no arquivo Excel com os IPs reais do Zabbix
"""

try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    print("⚠️ Pandas não instalado. Funcionalidades limitadas.")
    PANDAS_AVAILABLE = False
    pd = None
import os
from gerenciar_switches import GerenciadorSwitches
from datetime import datetime

def main():
    """Função principal"""
    print("=" * 70)
    print("🔧 Corrigindo IPs no arquivo Excel com dados do Zabbix")
    print("=" * 70)
    
    # Arquivo Excel original
    arquivo_excel = "switches_zabbix.xlsx"
    
    # Cria backup do arquivo original
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    arquivo_backup = f"switches_zabbix_backup_{timestamp}.xlsx"
    
    try:
        # Faz uma cópia do arquivo original
        if os.path.exists(arquivo_excel):
            import shutil
            shutil.copy2(arquivo_excel, arquivo_backup)
            print(f"✅ Backup criado: {arquivo_backup}")
        else:
            print(f"❌ Arquivo original não encontrado: {arquivo_excel}")
            return
        
        # Cria o gerenciador de switches
        gerenciador = GerenciadorSwitches(arquivo_excel=arquivo_excel)
        
        # Autentica no Zabbix
        if not gerenciador.autenticar():
            print("❌ Falha na autenticação no Zabbix")
            return
        
        # Carrega o arquivo Excel
        print(f"📊 Carregando arquivo Excel: {arquivo_excel}")
        df = pd.read_excel(arquivo_excel, sheet_name='Switches', header=2)
        
        # Dicionário para armazenar os IPs corrigidos
        ips_corrigidos = {}
        ips_nao_encontrados = []
        
        # Verifica cada switch no Zabbix
        print("\n🔍 Verificando IPs no Zabbix:")
        print("-" * 70)
        print(f"{'#':<3} {'Nome do Switch':<40} {'IP Atual':<15} {'IP Zabbix':<15} {'Status'}")
        print("-" * 70)
        
        for i, row in df.iterrows():
            host_name = str(row["Host"]).strip()
            ip_atual = str(row["IP"]).strip()
            
            # Busca o switch no Zabbix
            host_resp = gerenciador._call_api("host.get", {
                "filter": {"name": host_name},
                "output": ["hostid", "name", "status"],
                "selectInterfaces": ["ip"]
            })
            
            # Se encontrou o switch no Zabbix
            if host_resp.get("result"):
                host = host_resp["result"][0]
                
                # Obtém o IP real do Zabbix (da primeira interface)
                ip_zabbix = host["interfaces"][0]["ip"] if host["interfaces"] else "N/A"
                
                # Verifica se o IP é diferente
                if ip_atual != ip_zabbix:
                    status = "🔄 ATUALIZAR"
                    ips_corrigidos[i] = ip_zabbix
                else:
                    status = "✅ OK"
                
                print(f"{i:<3} {host_name[:40]:<40} {ip_atual:<15} {ip_zabbix:<15} {status}")
            else:
                print(f"{i:<3} {host_name[:40]:<40} {ip_atual:<15} {'Não encontrado':<15} ⚠️ NÃO ENCONTRADO")
                ips_nao_encontrados.append(host_name)
        
        print("-" * 70)
        print(f"📊 Total de switches: {len(df)}")
        print(f"📊 IPs a serem corrigidos: {len(ips_corrigidos)}")
        print(f"📊 Switches não encontrados: {len(ips_nao_encontrados)}")
        
        # Pergunta se deseja continuar com a atualização
        if len(ips_corrigidos) > 0:
            print("\n⚠️ Deseja atualizar os IPs no arquivo Excel? (s/n)")
            resposta = input().strip().lower()
            
            if resposta == 's':
                # Atualiza os IPs no DataFrame
                for idx, ip_zabbix in ips_corrigidos.items():
                    df.at[idx, "IP"] = ip_zabbix
                
                # Salva o DataFrame atualizado em um novo arquivo
                arquivo_saida = f"switches_zabbix_corrigido_{timestamp}.xlsx"
                
                # Cria um ExcelWriter
                with pd.ExcelWriter(arquivo_saida, engine='openpyxl') as writer:
                    # Adiciona linhas em branco no início
                    empty_df = pd.DataFrame()
                    empty_df.to_excel(writer, sheet_name='Switches', index=False)
                    
                    # Adiciona o DataFrame principal começando da linha 3
                    df.to_excel(writer, sheet_name='Switches', startrow=2, index=False)
                
                print(f"\n✅ Arquivo atualizado salvo como: {arquivo_saida}")
                print(f"⚠️ Verifique o arquivo e renomeie para {arquivo_excel} se estiver correto")
            else:
                print("\n❌ Operação cancelada pelo usuário")
        else:
            print("\n✅ Todos os IPs estão corretos, nenhuma atualização necessária")
        
    except Exception as e:
        print(f"\n❌ Erro: {str(e)}")
    
    print("\n" + "=" * 70)

if __name__ == "__main__":
    main()