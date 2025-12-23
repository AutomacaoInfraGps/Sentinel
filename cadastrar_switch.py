#!/usr/bin/env python3
"""
Script para cadastrar novos switches no sistema
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
    print("➕ Cadastro de Novo Switch")
    print("=" * 70)
    
    # Arquivo Excel
    arquivo_excel = "switches_zabbix.xlsx"
    
    # Verifica se o arquivo existe
    if not os.path.exists(arquivo_excel):
        print(f"❌ Arquivo Excel não encontrado: {arquivo_excel}")
        return
    
    # Cria o gerenciador de switches
    gerenciador = GerenciadorSwitches(arquivo_excel=arquivo_excel)
    
    # Autentica no Zabbix
    if not gerenciador.autenticar():
        print("❌ Falha na autenticação no Zabbix")
        return
    
    # Solicita informações do novo switch
    print("\n📝 Informe os dados do novo switch:")
    
    # Nome do host
    host_name = input("Nome do Host (ex: V001_REG_PARANA - SWTGPSPR-01): ").strip()
    if not host_name:
        print("❌ Nome do host é obrigatório")
        return
    
    # Verifica se o switch já existe na lista local
    for switch in gerenciador.switches:
        if switch["host"].lower() == host_name.lower():
            print(f"⚠️ Switch já cadastrado localmente: {host_name}")
            print(f"   Regional: {switch['regional']}")
            print(f"   IP: {switch['ip']}")
            print(f"   Modelo: {switch['modelo']}")
            print(f"   Local: {switch['local']}")
            return
    
    # Verifica se o switch já existe no Zabbix
    host_resp = gerenciador._call_api("host.get", {
        "filter": {"name": host_name},
        "output": ["hostid", "name", "status"],
        "selectInterfaces": ["ip"]
    })
    
    ip_zabbix = None
    if host_resp.get("result"):
        host = host_resp["result"][0]
        ip_zabbix = host["interfaces"][0]["ip"] if host["interfaces"] else None
        
        print(f"\n✅ Switch encontrado no Zabbix: {host['name']}")
        print(f"   ID: {host['hostid']}")
        print(f"   Status: {'Ativo' if host['status'] == '0' else 'Inativo'}")
        print(f"   IP: {ip_zabbix}")
        
        # Pergunta se deseja usar o IP do Zabbix
        if ip_zabbix:
            print("\n⚠️ Deseja usar o IP encontrado no Zabbix? (s/n)")
            usar_ip_zabbix = input().strip().lower() == 's'
        else:
            usar_ip_zabbix = False
    else:
        print(f"\n⚠️ Switch não encontrado no Zabbix: {host_name}")
        usar_ip_zabbix = False
    
    # IP do switch
    if usar_ip_zabbix and ip_zabbix:
        ip = ip_zabbix
        print(f"IP: {ip} (obtido do Zabbix)")
    else:
        ip = input("IP (ex: 192.168.1.1): ").strip()
        if not ip:
            print("❌ IP é obrigatório")
            return
    
    # Regional
    print("\nRegionais disponíveis:")
    regionais = gerenciador.listar_regionais()
    for i, regional in enumerate(regionais, 1):
        print(f"{i}. {regional}")
    
    print("\nEscolha a regional (número) ou digite uma nova:")
    regional_input = input().strip()
    
    try:
        regional_idx = int(regional_input) - 1
        if 0 <= regional_idx < len(regionais):
            regional = regionais[regional_idx]
        else:
            regional = regional_input.upper()
    except ValueError:
        regional = regional_input.upper()
    
    if not regional:
        print("❌ Regional é obrigatória")
        return
    
    # Modelo do switch
    modelo = input("Modelo (ex: Cisco Catalyst 2960): ").strip()
    
    # Local do switch
    local = input("Local (ex: Sala de Servidores): ").strip()
    
    # Confirma os dados
    print("\n📋 Confirme os dados do switch:")
    print(f"   Host: {host_name}")
    print(f"   IP: {ip}")
    print(f"   Regional: {regional}")
    print(f"   Modelo: {modelo}")
    print(f"   Local: {local}")
    
    print("\n⚠️ Confirma o cadastro? (s/n)")
    confirma = input().strip().lower() == 's'
    
    if not confirma:
        print("❌ Cadastro cancelado pelo usuário")
        return
    
    # Carrega o arquivo Excel
    try:
        df = pd.read_excel(arquivo_excel, sheet_name='Switches', header=2)
        
        # Cria um novo registro
        novo_switch = {
            "Host": host_name,
            "IP": ip,
            "Regional": regional,
            "Modelo": modelo,
            "Local": local
        }
        
        # Adiciona o novo registro ao DataFrame
        df = pd.concat([df, pd.DataFrame([novo_switch])], ignore_index=True)
        
        # Cria backup do arquivo original
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        arquivo_backup = f"switches_zabbix_backup_{timestamp}.xlsx"
        
        import shutil
        shutil.copy2(arquivo_excel, arquivo_backup)
        print(f"\n✅ Backup criado: {arquivo_backup}")
        
        # Salva o DataFrame atualizado
        with pd.ExcelWriter(arquivo_excel, engine='openpyxl') as writer:
            # Adiciona linhas em branco no início
            empty_df = pd.DataFrame()
            empty_df.to_excel(writer, sheet_name='Switches', index=False)
            
            # Adiciona o DataFrame principal começando da linha 3
            df.to_excel(writer, sheet_name='Switches', startrow=2, index=False)
        
        print(f"\n✅ Switch cadastrado com sucesso no arquivo: {arquivo_excel}")
        
        # Recarrega os switches
        gerenciador._carregar_switches()
        
        # Verifica o novo switch
        print("\n🔍 Verificando o novo switch...")
        resultado = gerenciador.verificar_switch(host_name)
        
        print(f"\n📊 Status do switch: {resultado['status']}")
        
    except Exception as e:
        print(f"\n❌ Erro ao cadastrar switch: {str(e)}")
    
    print("\n" + "=" * 70)

if __name__ == "__main__":
    main()