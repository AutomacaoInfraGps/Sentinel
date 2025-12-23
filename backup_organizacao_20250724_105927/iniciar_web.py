#!/usr/bin/env python3
"""
Script de Inicialização da Interface Web
Inicia o servidor web de configuração com verificações de dependências
"""

import sys
import subprocess
import webbrowser
import time
from pathlib import Path

def verificar_dependencias():
    """Verifica se as dependências estão instaladas"""
    dependencias = ['flask']
    faltando = []
    
    for dep in dependencias:
        try:
            __import__(dep)
        except ImportError:
            faltando.append(dep)
    
    return faltando

def instalar_dependencias(dependencias):
    """Instala dependências faltando"""
    print("🔧 Instalando dependências necessárias...")
    
    for dep in dependencias:
        print(f"   📦 Instalando {dep}...")
        try:
            subprocess.check_call([sys.executable, '-m', 'pip', 'install', dep])
            print(f"   ✅ {dep} instalado com sucesso")
        except subprocess.CalledProcessError:
            print(f"   ❌ Erro ao instalar {dep}")
            return False
    
    return True

def verificar_configuracao():
    """Verifica se o sistema está configurado"""
    from config import PROJECT_ROOT
    
    env_file = PROJECT_ROOT / "environment.json"
    servidores_file = PROJECT_ROOT / "servidores.json"
    regionais_file = PROJECT_ROOT / "estrutura_regionais.json"
    
    return {
        'environment': env_file.exists(),
        'servidores': servidores_file.exists(),
        'regionais': regionais_file.exists(),
        'estrutura_hierarquica': regionais_file.exists()
    }

def main():
    """Função principal"""
    print("🌐 Iniciando Interface Web de Configuração")
    print("=" * 50)
    
    # Verifica dependências
    print("🔍 Verificando dependências...")
    dependencias_faltando = verificar_dependencias()
    
    if dependencias_faltando:
        print(f"⚠️ Dependências faltando: {', '.join(dependencias_faltando)}")
        
        resposta = input("Deseja instalar automaticamente? (S/n): ")
        if resposta.lower() not in ['n', 'no', 'nao', 'não']:
            if not instalar_dependencias(dependencias_faltando):
                print("❌ Erro ao instalar dependências. Execute manualmente:")
                print(f"   pip install {' '.join(dependencias_faltando)}")
                return
        else:
            print("❌ Dependências necessárias não instaladas")
            return
    
    print("✅ Dependências verificadas")
    
    # Verifica configuração
    print("\n🔍 Verificando configuração...")
    config_status = verificar_configuracao()
    
    if not config_status['environment']:
        print("⚠️ Arquivo environment.json não encontrado")
    if not config_status['regionais']:
        print("⚠️ Nenhuma estrutura de servidores encontrada")
    
    if config_status['estrutura_hierarquica']:
        print("✅ Estrutura hierárquica detectada")
    
    
    if not any([config_status['environment'], config_status['servidores'], config_status['regionais']]):
        print("💡 Sistema não configurado. Use a interface web para configurar!")
        
    # Inicia o gerenciador de atualizações em paralelo
    print("\n🔄 Iniciando gerenciador de atualizações em paralelo...")
    try:
        import gerenciador_atualizacoes
        import threading
        threading.Thread(target=gerenciador_atualizacoes.start_update_threads, daemon=True).start()
        print("✅ Gerenciador de atualizações iniciado")
    except Exception as e:
        print(f"⚠️ Erro ao iniciar gerenciador de atualizações: {e}")
        print("   Os cards podem não ser atualizados automaticamente")
    
    # Inicia servidor web
    print("\n🚀 Iniciando servidor web...")
    print("📍 URL: http://localhost:5000")
    print("🔧 Para parar: Ctrl+C")
    print("=" * 50)
    
    # Abre navegador após 2 segundos
    def abrir_navegador():
        time.sleep(2)
        try:
            webbrowser.open('http://localhost:5000')
            print("🌐 Navegador aberto automaticamente")
        except:
            print("⚠️ Não foi possível abrir o navegador automaticamente")
            print("   Acesse manualmente: http://localhost:5000")
    
    import threading
    threading.Thread(target=abrir_navegador, daemon=True).start()
    
    # Inicia servidor Flask
    try:
        from web_config import app
        app.run(
            host='0.0.0.0',
            port=5000,
            debug=False,
            use_reloader=False
        )
    except KeyboardInterrupt:
        print("\n\n✅ Servidor web encerrado")
    except Exception as e:
        print(f"\n❌ Erro ao iniciar servidor: {e}")
        print("\nTente executar diretamente:")
        print("   python web_config.py")

if __name__ == "__main__":
    main()