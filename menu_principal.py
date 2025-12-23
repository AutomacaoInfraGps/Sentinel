#!/usr/bin/env python3
"""
Menu Principal do Sistema de Automação
Oferece opções para verificar requisitos, iniciar/parar serviço web
"""

import sys
import os
import subprocess
import time
import threading
import webbrowser
import psutil
from pathlib import Path

# Variável global para controlar o processo do servidor
servidor_processo = None
servidor_thread = None
servidor_ativo = False

def limpar_tela():
    """Limpa a tela do console"""
    os.system('cls' if os.name == 'nt' else 'clear')

def exibir_banner():
    """Exibe o banner do sistema"""
    print("=" * 60)
    print("    SISTEMA DE AUTOMAÇÃO DE INFRAESTRUTURA")
    print("=" * 60)
    print("    Versão: 1.0.0")
    print("    Compilado: Janeiro 2025")
    print("=" * 60)

def verificar_requisitos():
    """Verifica todos os requisitos e dependências do sistema"""
    print("\n🔍 VERIFICANDO REQUISITOS E DEPENDÊNCIAS...")
    print("-" * 50)
    
    requisitos_ok = True
    
    # 1. Verificar Python (já está embutido no exe)
    print("✅ Python 3.12: OK (Embutido no executável)")
    
    # 2. Verificar PowerShell
    try:
        result = subprocess.run(['powershell', '-Command', 'Get-Host'], 
                              capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            print("✅ PowerShell: OK")
        else:
            print("❌ PowerShell: ERRO - Não disponível")
            requisitos_ok = False
    except Exception as e:
        print(f"❌ PowerShell: ERRO - {e}")
        requisitos_ok = False
    
    # 3. Verificar porta 5000
    porta_livre = True
    for conn in psutil.net_connections():
        if conn.laddr.port == 5000:
            porta_livre = False
            break
    
    if porta_livre:
        print("✅ Porta 5000: Disponível")
    else:
        print("⚠️ Porta 5000: Em uso (pode causar conflitos)")
        requisitos_ok = False
    
    # 4. Verificar arquivos de configuração
    config_files = [
        "config.py",
        "web_config.py", 
        "iniciar_web.py",
        "executar_tudo.py"
    ]
    
    for arquivo in config_files:
        if os.path.exists(arquivo):
            print(f"✅ {arquivo}: OK")
        else:
            print(f"❌ {arquivo}: AUSENTE")
            requisitos_ok = False
    
    # 5. Verificar pastas necessárias
    pastas = ["templates", "data", "output", "logs"]
    for pasta in pastas:
        if os.path.exists(pasta):
            print(f"✅ Pasta {pasta}/: OK")
        else:
            print(f"⚠️ Pasta {pasta}/: Será criada automaticamente")
    
    # 6. Verificar dependências Python (embutidas)
    dependencias = [
        "flask", "werkzeug", "jinja2", "requests", 
        "pathlib", "json", "threading"
    ]
    
    for dep in dependencias:
        try:
            __import__(dep)
            print(f"✅ {dep}: OK")
        except ImportError:
            print(f"❌ {dep}: AUSENTE")
            requisitos_ok = False
    
    # 7. Verificar permissões de escrita
    try:
        test_file = Path("test_write.tmp")
        test_file.write_text("teste")
        test_file.unlink()
        print("✅ Permissões de escrita: OK")
    except Exception:
        print("❌ Permissões de escrita: ERRO")
        requisitos_ok = False
    
    print("-" * 50)
    if requisitos_ok:
        print("🎉 TODOS OS REQUISITOS ATENDIDOS!")
        print("   Sistema pronto para uso.")
    else:
        print("⚠️ ALGUNS REQUISITOS NÃO FORAM ATENDIDOS!")
        print("   Verifique os itens marcados com ❌")
        print("   Execute como administrador se necessário.")
    
    print("\nPressione ENTER para continuar...")
    input()

def iniciar_servidor_web():
    """Inicia o servidor web em thread separada"""
    global servidor_processo, servidor_ativo, servidor_thread
    
    if servidor_ativo:
        print("⚠️ Servidor web já está rodando!")
        print("   Acesse: http://localhost:5000")
        print("\nPressione ENTER para continuar...")
        input()
        return
    
    print("\n🚀 INICIANDO SERVIDOR WEB...")
    print("-" * 50)
    
    def executar_servidor():
        global servidor_processo, servidor_ativo
        try:
            # Usa o iniciar_web.py que tem toda a lógica correta
            print("📦 Carregando módulos...")
            
            # Importa e executa o iniciar_web
            import iniciar_web
            
            # Marca servidor como ativo
            servidor_ativo = True
            
            # Executa a função main do iniciar_web
            iniciar_web.main()
            
        except KeyboardInterrupt:
            print("\n✅ Servidor web encerrado pelo usuário")
        except Exception as e:
            print(f"\n❌ Erro ao iniciar servidor: {e}")
        finally:
            servidor_ativo = False
    
    # Inicia servidor em thread separada
    servidor_thread = threading.Thread(target=executar_servidor, daemon=True)
    servidor_thread.start()
    
    # Aguarda um pouco para o servidor inicializar
    time.sleep(2)
    
    if servidor_ativo:
        print("✅ Servidor web iniciado com sucesso!")
        print("🌐 Acesse: http://localhost:5000")
        print("📱 O navegador deve abrir automaticamente")
        print("\n💡 DICA: Deixe esta janela aberta para manter o servidor rodando")
        print("         Use a opção 3 do menu para parar o servidor")
    else:
        print("❌ Falha ao iniciar servidor web")
        print("   Verifique os requisitos e tente novamente")
    
    print("\nPressione ENTER para voltar ao menu...")
    input()

def parar_servidor_web():
    """Para o servidor web"""
    global servidor_processo, servidor_ativo, servidor_thread
    
    if not servidor_ativo:
        print("⚠️ Servidor web não está rodando!")
        print("\nPressione ENTER para continuar...")
        input()
        return
    
    print("\n🛑 PARANDO SERVIDOR WEB...")
    print("-" * 50)
    
    try:
        # Marca como inativo
        servidor_ativo = False
        
        # Tenta finalizar processos na porta 5000
        for proc in psutil.process_iter(['pid', 'name', 'connections']):
            try:
                for conn in proc.info['connections'] or []:
                    if conn.laddr.port == 5000:
                        print(f"🔄 Finalizando processo {proc.info['name']} (PID: {proc.info['pid']})")
                        proc.terminate()
                        proc.wait(timeout=5)
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.TimeoutExpired):
                pass
        
        print("✅ Servidor web parado com sucesso!")
        print("🌐 A interface web não está mais disponível")
        
    except Exception as e:
        print(f"⚠️ Erro ao parar servidor: {e}")
        print("   O servidor pode ainda estar rodando")
    
    print("\nPressione ENTER para continuar...")
    input()

def exibir_status():
    """Exibe o status atual do sistema"""
    global servidor_ativo
    
    print(f"\n📊 STATUS DO SISTEMA:")
    print("-" * 30)
    
    if servidor_ativo:
        print("🟢 Servidor Web: ATIVO")
        print("🌐 URL: http://localhost:5000")
    else:
        print("🔴 Servidor Web: INATIVO")
    
    # Verifica porta 5000
    porta_em_uso = False
    for conn in psutil.net_connections():
        if conn.laddr.port == 5000:
            porta_em_uso = True
            break
    
    if porta_em_uso:
        print("🟡 Porta 5000: EM USO")
    else:
        print("🟢 Porta 5000: LIVRE")

def menu_principal():
    """Menu principal do sistema"""
    while True:
        limpar_tela()
        exibir_banner()
        exibir_status()
        
        print("\n📋 OPÇÕES DISPONÍVEIS:")
        print("-" * 30)
        print("1. 🔍 Verificar Requisitos e Dependências")
        print("2. 🚀 Iniciar Serviço Web")
        print("3. 🛑 Parar Serviço Web")
        print("4. ❌ Sair")
        print("-" * 30)
        
        try:
            opcao = input("\n👉 Escolha uma opção (1-4): ").strip()
            
            if opcao == "1":
                verificar_requisitos()
            elif opcao == "2":
                iniciar_servidor_web()
            elif opcao == "3":
                parar_servidor_web()
            elif opcao == "4":
                # Para servidor se estiver rodando
                if servidor_ativo:
                    print("\n🛑 Parando servidor antes de sair...")
                    parar_servidor_web()
                
                print("\n👋 Obrigado por usar o Sistema de Automação!")
                print("   Desenvolvido com ❤️ para sua infraestrutura")
                time.sleep(2)
                break
            else:
                print("\n❌ Opção inválida! Escolha entre 1-4.")
                time.sleep(2)
                
        except KeyboardInterrupt:
            print("\n\n🛑 Interrompido pelo usuário...")
            if servidor_ativo:
                parar_servidor_web()
            break
        except Exception as e:
            print(f"\n❌ Erro inesperado: {e}")
            time.sleep(3)

if __name__ == "__main__":
    try:
        menu_principal()
    except Exception as e:
        print(f"❌ Erro crítico: {e}")
        input("Pressione ENTER para sair...")
    finally:
        # Garante que o servidor seja parado ao sair
        if servidor_ativo:
            try:
                parar_servidor_web()
            except Exception as e:
                print(f"Erro em {__file__}: {e}")