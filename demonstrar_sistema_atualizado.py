"""
Demonstração do Sistema Atualizado
Mostra todas as funcionalidades da nova estrutura hierárquica integrada
"""

import webbrowser
import time
from pathlib import Path
import json

def mostrar_estrutura_atual():
    """Mostra a estrutura atual do sistema"""
    
    print("🏗️ ESTRUTURA ATUAL DO SISTEMA")
    print("=" * 50)
    
    try:
        from gerenciar_regionais import GerenciadorRegionais
        
        gerenciador = GerenciadorRegionais()
        regionais = gerenciador.listar_regionais()
        
        print(f"📊 Total de Regionais: {len(regionais)}")
        print()
        
        for codigo_regional in regionais:
            regional_info = gerenciador.obter_regional(codigo_regional)
            if regional_info:
                servidores = regional_info.get('servidores', [])
                print(f"🏢 {regional_info.get('nome', codigo_regional)}")
                print(f"   📋 Código: {codigo_regional}")
                print(f"   🖥️ Servidores: {len(servidores)}")
                
                for servidor in servidores:
                    tipo_icon = "🔧" if servidor.get('tipo') == 'idrac' else "🖥️"
                    print(f"      {tipo_icon} {servidor.get('nome')} ({servidor.get('ip')})")
                print()
        
        return True
        
    except Exception as e:
        print(f"❌ Erro ao carregar estrutura: {e}")
        return False

def mostrar_funcionalidades_web():
    """Mostra as funcionalidades disponíveis na interface web"""
    
    print("🌐 FUNCIONALIDADES DA INTERFACE WEB")
    print("=" * 50)
    
    funcionalidades = [
        {
            "categoria": "Dashboard Principal",
            "itens": [
                "✅ Dashboard hierárquico com visão geral das regionais",
                "✅ Estatísticas em tempo real (online/offline)",
                "✅ Cards interativos para cada regional",
                "✅ Migração automática do sistema legado"
            ]
        },
        {
            "categoria": "Gerenciamento de Regionais",
            "itens": [
                "✅ Listar todas as regionais cadastradas",
                "✅ Criar nova regional",
                "✅ Editar regional existente",
                "✅ Visualizar detalhes de cada regional"
            ]
        },
        {
            "categoria": "Gerenciamento de Servidores",
            "itens": [
                "✅ Adicionar servidores a regionais específicas",
                "✅ Verificar status de conectividade",
                "✅ Editar configurações de servidores",
                "✅ Suporte a iDRAC e iLO"
            ]
        },
        {
            "categoria": "Execução e Dashboards",
            "itens": [
                "✅ Execução completa do sistema V2",
                "✅ Dashboard hierárquico integrado",
                "✅ Relatórios por regional",
                "✅ Dashboard final consolidado"
            ]
        },
        {
            "categoria": "Sistema Legado",
            "itens": [
                "✅ Compatibilidade com servidores antigos",
                "✅ Migração automática de dados",
                "✅ Execução de scripts legados",
                "✅ Backup e restauração"
            ]
        }
    ]
    
    for func in funcionalidades:
        print(f"📂 {func['categoria']}:")
        for item in func['itens']:
            print(f"   {item}")
        print()

def mostrar_urls_importantes():
    """Mostra as URLs importantes do sistema"""
    
    print("🔗 URLS IMPORTANTES")
    print("=" * 50)
    
    urls = [
        ("🏠 Dashboard Principal", "http://localhost:5000/"),
        ("🏢 Gerenciar Regionais", "http://localhost:5000/regionais"),
        ("➕ Nova Regional", "http://localhost:5000/regional/nova"),
        ("🖥️ Servidores Legados", "http://localhost:5000/servidores"),
        ("⚙️ Configurações", "http://localhost:5000/configuracoes"),
        ("🚀 Execução Completa", "http://localhost:5000/executar/completo"),
        ("📊 Dashboard Hierárquico", "http://localhost:5000/dashboard/hierarquico"),
        ("💾 Backup", "http://localhost:5000/backup")
    ]
    
    for nome, url in urls:
        print(f"{nome}: {url}")
    
    print()

def verificar_arquivos_gerados():
    """Verifica os arquivos gerados pelo sistema"""
    
    print("📁 ARQUIVOS DO SISTEMA")
    print("=" * 50)
    
    arquivos_importantes = [
        ("estrutura_regionais.json", "Estrutura hierárquica das regionais"),
        ("servidores.json", "Servidores do sistema legado"),
        ("environment.json", "Configurações do ambiente"),
        ("relatorio_atualizacao.json", "Relatório da última atualização"),
        ("output/dashboard_hierarquico.html", "Dashboard hierárquico"),
        ("output/dashboard_final_integrado.html", "Dashboard final"),
        ("logs/", "Diretório de logs do sistema")
    ]
    
    for arquivo, descricao in arquivos_importantes:
        arquivo_path = Path(arquivo)
        status = "✅" if arquivo_path.exists() else "❌"
        print(f"{status} {arquivo} - {descricao}")
    
    print()

def demonstrar_api_endpoints():
    """Mostra os endpoints da API disponíveis"""
    
    print("🔌 ENDPOINTS DA API")
    print("=" * 50)
    
    endpoints = [
        ("GET /api/dashboard/hierarquico", "Dados do dashboard hierárquico"),
        ("GET /api/regional/<codigo>/verificar", "Verificar status de uma regional"),
        ("POST /api/regional", "Criar/editar regional"),
        ("POST /api/regional/<codigo>/servidor", "Adicionar servidor à regional"),
        ("POST /api/executar/completo", "Executar sistema completo"),
        ("GET /api/servidores/testar-todos", "Testar todos os servidores"),
        ("GET /api/servidores/status-real", "Status real dos servidores")
    ]
    
    for endpoint, descricao in endpoints:
        print(f"🔗 {endpoint}")
        print(f"   📝 {descricao}")
        print()

def abrir_sistema_no_navegador():
    """Abre o sistema no navegador"""
    
    print("🌐 ABRINDO SISTEMA NO NAVEGADOR")
    print("=" * 50)
    
    try:
        print("🚀 Abrindo dashboard principal...")
        webbrowser.open('http://localhost:5000/')
        time.sleep(2)
        
        print("🏢 Abrindo gerenciamento de regionais...")
        webbrowser.open('http://localhost:5000/regionais')
        time.sleep(2)
        
        print("📊 Abrindo dashboard hierárquico...")
        webbrowser.open('http://localhost:5000/dashboard/hierarquico')
        
        print("✅ Sistema aberto no navegador!")
        
    except Exception as e:
        print(f"❌ Erro ao abrir navegador: {e}")
        print("🔗 Acesse manualmente: http://localhost:5000/")

def mostrar_guia_uso():
    """Mostra um guia de uso do sistema atualizado"""
    
    print("📖 GUIA DE USO DO SISTEMA ATUALIZADO")
    print("=" * 50)
    
    passos = [
        {
            "passo": "1. Acesso ao Sistema",
            "descricao": "Acesse http://localhost:5000/ e faça login com suas credenciais AD"
        },
        {
            "passo": "2. Dashboard Principal", 
            "descricao": "Visualize o resumo de todas as regionais e servidores"
        },
        {
            "passo": "3. Gerenciar Regionais",
            "descricao": "Use o menu 'Regionais' para criar e gerenciar suas regionais"
        },
        {
            "passo": "4. Adicionar Servidores",
            "descricao": "Adicione servidores iDRAC/iLO às regionais específicas"
        },
        {
            "passo": "5. Verificar Status",
            "descricao": "Use os botões de verificação para testar conectividade"
        },
        {
            "passo": "6. Executar Sistema",
            "descricao": "Use 'Executar > Sistema Completo V2' para execução completa"
        },
        {
            "passo": "7. Visualizar Dashboards",
            "descricao": "Acesse os dashboards hierárquicos gerados automaticamente"
        }
    ]
    
    for passo_info in passos:
        print(f"📋 {passo_info['passo']}")
        print(f"   {passo_info['descricao']}")
        print()

def main():
    """Função principal de demonstração"""
    
    print("🎉 DEMONSTRAÇÃO DO SISTEMA ATUALIZADO")
    print("Sistema de Automação com Estrutura Hierárquica")
    print("=" * 60)
    print()
    
    # 1. Mostra estrutura atual
    if not mostrar_estrutura_atual():
        print("❌ Erro ao carregar estrutura. Verifique se o sistema está configurado.")
        return
    
    # 2. Mostra funcionalidades
    mostrar_funcionalidades_web()
    
    # 3. Mostra URLs importantes
    mostrar_urls_importantes()
    
    # 4. Verifica arquivos
    verificar_arquivos_gerados()
    
    # 5. Mostra endpoints da API
    demonstrar_api_endpoints()
    
    # 6. Mostra guia de uso
    mostrar_guia_uso()
    
    # 7. Pergunta se quer abrir no navegador
    print("🌐 DEMONSTRAÇÃO INTERATIVA")
    print("=" * 50)
    
    resposta = input("Deseja abrir o sistema no navegador para demonstração? (S/n): ")
    if resposta.lower() not in ['n', 'no', 'nao', 'não']:
        abrir_sistema_no_navegador()
    
    print("\n🎯 RESUMO DA ATUALIZAÇÃO")
    print("=" * 50)
    print("✅ Interface web totalmente integrada com estrutura hierárquica")
    print("✅ Dashboard principal mostra regionais e estatísticas")
    print("✅ Gerenciamento completo de regionais e servidores")
    print("✅ Execução V2 com dashboards hierárquicos")
    print("✅ Compatibilidade mantida com sistema legado")
    print("✅ APIs REST para integração")
    print()
    print("🚀 O sistema está pronto para uso!")
    print("🌐 Acesse: http://localhost:5000/")

if __name__ == "__main__":
    main()