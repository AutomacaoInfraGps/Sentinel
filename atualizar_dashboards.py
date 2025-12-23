"""
Script de Atualização de Dashboards
Migra para a nova estrutura hierárquica Regional → Servidores
"""

import os
import shutil
from pathlib import Path
from datetime import datetime
import webbrowser

def backup_dashboards_antigos():
    """Faz backup dos dashboards antigos"""
    
    backup_dir = Path("backup_dashboards_antigos")
    backup_dir.mkdir(exist_ok=True)
    
    arquivos_antigos = [
        "gerar_status_html.py",
        "executar_tudo.py",
        "output/dashboard_final.html"
    ]
    
    print("📦 Fazendo backup dos dashboards antigos...")
    
    for arquivo in arquivos_antigos:
        arquivo_path = Path(arquivo)
        if arquivo_path.exists():
            backup_path = backup_dir / arquivo_path.name
            shutil.copy2(arquivo_path, backup_path)
            print(f"   ✅ Backup: {arquivo} → {backup_path}")
    
    print(f"📁 Backup salvo em: {backup_dir}")

def atualizar_sistema():
    """Atualiza o sistema para a nova estrutura"""
    
    print("🔄 Atualizando sistema para estrutura hierárquica...")
    
    # 1. Backup
    backup_dashboards_antigos()
    
    # 2. Atualiza arquivo principal
    executar_antigo = Path("executar_tudo.py")
    executar_novo = Path("executar_tudo_v2.py")
    
    if executar_novo.exists():
        if executar_antigo.exists():
            shutil.move(executar_antigo, "backup_dashboards_antigos/executar_tudo_original.py")
        
        shutil.copy2(executar_novo, executar_antigo)
        print("   ✅ executar_tudo.py atualizado")
    
    # 3. Cria links de compatibilidade
    criar_links_compatibilidade()
    
    print("✅ Sistema atualizado com sucesso!")

def criar_links_compatibilidade():
    """Cria links para manter compatibilidade"""
    
    # Cria script de compatibilidade para gerar_status_html.py
    compatibilidade_html = """
# Compatibilidade - Redirecionamento para novo sistema
from dashboard_hierarquico import DashboardHierarquico
import webbrowser

print("⚠️  AVISO: Este script foi atualizado!")
print("🔄 Redirecionando para o novo dashboard hierárquico...")

dashboard = DashboardHierarquico()
arquivo = dashboard.abrir_dashboard()

print(f"✅ Dashboard gerado: {arquivo}")
"""
    
    with open("gerar_status_html_compatibilidade.py", 'w', encoding='utf-8') as f:
        f.write(compatibilidade_html)
    
    print("   ✅ Script de compatibilidade criado")

def demonstrar_nova_estrutura():
    """Demonstra a nova estrutura"""
    
    print("\n🏗️ NOVA ESTRUTURA HIERÁRQUICA:")
    print("=" * 50)
    
    from gerenciar_regionais import GerenciadorRegionais
    
    gerenciador = GerenciadorRegionais()
    regionais = gerenciador.listar_regionais()
    
    print(f"📍 Total de Regionais: {len(regionais)}")
    
    for regional in regionais:
        info = gerenciador.obter_regional(regional)
        servidores = info.get("servidores", [])
        
        print(f"\n🏢 {info.get('nome', regional)}")
        print(f"   Código: {regional}")
        print(f"   Servidores: {len(servidores)}")
        
        for servidor in servidores:
            tipo_icon = "🔧" if servidor.get("tipo") == "idrac" else "⚙️"
            print(f"     {tipo_icon} {servidor.get('nome')} ({servidor.get('ip')})")

def testar_novo_sistema():
    """Testa o novo sistema"""
    
    print("\n🧪 Testando novo sistema...")
    
    try:
        from dashboard_hierarquico import DashboardHierarquico
        
        dashboard = DashboardHierarquico()
        dados = dashboard.coletar_dados_completos()
        
        print("✅ Coleta de dados: OK")
        print(f"   Regionais: {dados['estatisticas_gerais']['total_regionais']}")
        print(f"   Servidores: {dados['estatisticas_gerais']['total_servidores']}")
        print(f"   Online: {dados['estatisticas_gerais']['servidores_online']}")
        print(f"   Offline: {dados['estatisticas_gerais']['servidores_offline']}")
        
        # Gera dashboard de teste
        arquivo_teste = dashboard.gerar_todos_dashboards()
        print(f"✅ Dashboard gerado: {arquivo_teste}")
        
        return True
        
    except Exception as e:
        print(f"❌ Erro no teste: {e}")
        return False

def main():
    """Função principal"""
    
    print("🔄 ATUALIZAÇÃO DE DASHBOARDS")
    print("Migração para Estrutura Hierárquica Regional → Servidores")
    print("=" * 60)
    
    while True:
        print("\n📋 MENU DE ATUALIZAÇÃO:")
        print("1. Fazer backup dos dashboards antigos")
        print("2. Atualizar sistema completo")
        print("3. Demonstrar nova estrutura")
        print("4. Testar novo sistema")
        print("5. Gerar novo dashboard")
        print("6. Abrir dashboard hierárquico")
        print("0. Sair")
        
        opcao = input("\nEscolha uma opção: ")
        
        if opcao == "1":
            backup_dashboards_antigos()
        
        elif opcao == "2":
            resposta = input("⚠️  Confirma a atualização do sistema? (s/n): ")
            if resposta.lower() == 's':
                atualizar_sistema()
            else:
                print("❌ Atualização cancelada")
        
        elif opcao == "3":
            demonstrar_nova_estrutura()
        
        elif opcao == "4":
            if testar_novo_sistema():
                print("✅ Sistema funcionando corretamente!")
            else:
                print("❌ Problemas encontrados no sistema")
        
        elif opcao == "5":
            try:
                from dashboard_hierarquico import DashboardHierarquico
                dashboard = DashboardHierarquico()
                arquivo = dashboard.gerar_todos_dashboards()
                print(f"✅ Dashboard gerado: {arquivo}")
            except Exception as e:
                print(f"❌ Erro: {e}")
        
        elif opcao == "6":
            try:
                from dashboard_hierarquico import DashboardHierarquico
                dashboard = DashboardHierarquico()
                arquivo = dashboard.abrir_dashboard()
                print(f"🌐 Dashboard aberto: {arquivo}")
            except Exception as e:
                print(f"❌ Erro: {e}")
        
        elif opcao == "0":
            break
        
        else:
            print("❌ Opção inválida")
    
    print("\n✅ Atualização concluída!")
    print("💡 Use 'python dashboard_hierarquico.py' para o novo sistema")
    print("💡 Use 'python executar_tudo_v2.py' para execução completa")

if __name__ == "__main__":
    main()