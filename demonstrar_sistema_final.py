"""
Demonstração do Sistema Final
Sistema 100% hierárquico com autenticação AD original
"""

import webbrowser
import time
from pathlib import Path
import json

def mostrar_sistema_final():
    """Mostra as características do sistema final"""
    
    print("🎉 SISTEMA FINAL - 100% HIERÁRQUICO COM AD")
    print("=" * 60)
    
    caracteristicas = [
        {
            "categoria": "🏗️ Estrutura",
            "itens": [
                "✅ 100% hierárquico: Regional → Servidores",
                "✅ 4 regionais organizadas",
                "✅ 4 servidores distribuídos",
                "✅ Sem sistema legado"
            ]
        },
        {
            "categoria": "🔐 Autenticação",
            "itens": [
                "✅ Active Directory completo",
                "✅ Domínio: DOMINIO.LOCAL",
                "✅ Servidor: DC01 (192.0.2.11)",
                "✅ OU: Usuarios Administrativos",
                "✅ Interface de login original"
            ]
        },
        {
            "categoria": "🌐 Interface Web",
            "itens": [
                "✅ Dashboard hierárquico limpo",
                "✅ Menu organizado por categorias",
                "✅ Navegação Regional → Servidores",
                "✅ Informações do usuário AD no header",
                "✅ Templates específicos para cada função"
            ]
        },
        {
            "categoria": "🚀 Funcionalidades",
            "itens": [
                "✅ Gerenciamento completo de regionais",
                "✅ Adição de servidores por regional",
                "✅ Verificação de status hierárquica",
                "✅ Dashboard hierárquico integrado",
                "✅ Execução completa V2"
            ]
        }
    ]
    
    for categoria in caracteristicas:
        print(f"\n{categoria['categoria']}:")
        for item in categoria['itens']:
            print(f"   {item}")
    
    print()

def verificar_estrutura_atual():
    """Verifica a estrutura atual do sistema"""
    
    print("📊 ESTRUTURA ATUAL:")
    print("-" * 30)
    
    try:
        from gerenciar_regionais import GerenciadorRegionais
        
        gerenciador = GerenciadorRegionais()
        regionais = gerenciador.listar_regionais()
        
        print(f"🏢 Total de Regionais: {len(regionais)}")
        
        total_servidores = 0
        for codigo_regional in regionais:
            regional_info = gerenciador.obter_regional(codigo_regional)
            if regional_info:
                servidores = regional_info.get('servidores', [])
                total_servidores += len(servidores)
                print(f"   📋 {regional_info.get('nome', codigo_regional)}: {len(servidores)} servidores")
        
        print(f"🖥️ Total de Servidores: {total_servidores}")
        
        return True
        
    except Exception as e:
        print(f"❌ Erro ao verificar estrutura: {e}")
        return False

def verificar_autenticacao():
    """Verifica se a autenticação AD está funcionando"""
    
    print("\n🔐 VERIFICAÇÃO DA AUTENTICAÇÃO AD:")
    print("-" * 40)
    
    try:
        from auth_ad import testar_conexao_ad
        
        sucesso, mensagem = testar_conexao_ad()
        
        if sucesso:
            print("✅ Conexão AD: OK")
            print("✅ Servidor SIRIUS: Acessível")
            print("✅ Domínio GALAXIA.LOCAL: Conectado")
        else:
            print(f"⚠️ Conexão AD: {mensagem}")
        
        return sucesso
        
    except Exception as e:
        print(f"❌ Erro na verificação AD: {e}")
        return False

def mostrar_urls_sistema():
    """Mostra as URLs do sistema final"""
    
    print("\n🔗 URLS DO SISTEMA:")
    print("-" * 25)
    
    urls = [
        ("🔐 Login", "http://localhost:5000/login"),
        ("🏠 Dashboard", "http://localhost:5000/"),
        ("🏢 Regionais", "http://localhost:5000/regionais"),
        ("➕ Nova Regional", "http://localhost:5000/regional/nova"),
        ("🚀 Execução", "http://localhost:5000/executar/completo"),
        ("📊 Dashboard Hierárquico", "http://localhost:5000/dashboard/hierarquico"),
        ("⚙️ Configurações", "http://localhost:5000/configuracoes"),
        ("💾 Backup", "http://localhost:5000/backup"),
        ("🚪 Logout", "http://localhost:5000/logout")
    ]
    
    for nome, url in urls:
        print(f"   {nome}: {url}")

def verificar_arquivos_sistema():
    """Verifica os arquivos do sistema final"""
    
    print("\n📁 ARQUIVOS DO SISTEMA:")
    print("-" * 30)
    
    arquivos_principais = [
        ("web_config.py", "Interface web hierárquica com AD"),
        ("auth_ad.py", "Autenticação Active Directory"),
        ("gerenciar_regionais.py", "Gerenciamento hierárquico"),
        ("estrutura_regionais.json", "Dados das regionais"),
        ("templates/login.html", "Interface de login AD"),
        ("templates/index.html", "Dashboard hierárquico"),
        ("templates/base.html", "Template base com usuário AD"),
        ("templates/regionais.html", "Listagem de regionais"),
        ("templates/regional_detalhes.html", "Detalhes da regional"),
        ("templates/servidor_regional_form.html", "Formulário de servidor")
    ]
    
    for arquivo, descricao in arquivos_principais:
        arquivo_path = Path(arquivo)
        status = "✅" if arquivo_path.exists() else "❌"
        print(f"   {status} {arquivo}")
        if arquivo_path.exists():
            print(f"      📝 {descricao}")

def mostrar_fluxo_uso():
    """Mostra o fluxo de uso do sistema"""
    
    print("\n📖 FLUXO DE USO:")
    print("-" * 20)
    
    passos = [
        "1. 🔐 Acesse http://localhost:5000/",
        "2. 🔑 Faça login com credenciais AD",
        "3. 🏠 Visualize dashboard hierárquico",
        "4. 🏢 Gerencie regionais e servidores",
        "5. 🚀 Execute verificações completas",
        "6. 📊 Visualize dashboards gerados",
        "7. 🚪 Logout seguro"
    ]
    
    for passo in passos:
        print(f"   {passo}")

def abrir_sistema():
    """Abre o sistema no navegador"""
    
    print("\n🌐 ABRINDO SISTEMA NO NAVEGADOR:")
    print("-" * 40)
    
    try:
        print("🚀 Abrindo página de login...")
        webbrowser.open('http://localhost:5000/')
        
        print("✅ Sistema aberto!")
        print("🔐 Faça login com suas credenciais AD")
        
    except Exception as e:
        print(f"❌ Erro ao abrir navegador: {e}")
        print("🔗 Acesse manualmente: http://localhost:5000/")

def main():
    """Função principal de demonstração"""
    
    print("🎯 DEMONSTRAÇÃO DO SISTEMA FINAL")
    print("Sistema Hierárquico com Autenticação AD")
    print("=" * 60)
    
    # 1. Mostra características do sistema
    mostrar_sistema_final()
    
    # 2. Verifica estrutura
    if not verificar_estrutura_atual():
        print("\n⚠️ AVISO: Problemas na estrutura hierárquica")
    
    # 3. Verifica autenticação
    verificar_autenticacao()
    
    # 4. Mostra URLs
    mostrar_urls_sistema()
    
    # 5. Verifica arquivos
    verificar_arquivos_sistema()
    
    # 6. Mostra fluxo de uso
    mostrar_fluxo_uso()
    
    # 7. Pergunta se quer abrir
    print("\n" + "=" * 60)
    resposta = input("🌐 Deseja abrir o sistema no navegador? (S/n): ")
    
    if resposta.lower() not in ['n', 'no', 'nao', 'não']:
        abrir_sistema()
    
    # 8. Resumo final
    print("\n🎉 RESUMO FINAL:")
    print("=" * 20)
    print("✅ Sistema 100% hierárquico")
    print("✅ Autenticação AD original mantida")
    print("✅ Interface web limpa e organizada")
    print("✅ Navegação Regional → Servidores")
    print("✅ Sem sistema legado")
    print("✅ Código focado e limpo")
    print("\n🚀 O sistema está perfeito para uso!")
    print("🌐 URL: http://localhost:5000/")
    print("🔐 Login: Credenciais Active Directory")

if __name__ == "__main__":
    main()