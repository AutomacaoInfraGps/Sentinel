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
    print("Instalando dependencias necessarias...")
    
    for dep in dependencias:
        print(f"Instalando {dep}...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", dep])
            print(f"{dep} instalado com sucesso!")
        except subprocess.CalledProcessError:
            print(f"Erro ao instalar {dep}")
            return False
    
    return True

def verificar_configuracao():
    """Verifica se o sistema está configurado"""
    from pathlib import Path
    
    # Verifica arquivos de configuração
    environment_file = Path("environment.json")
    servidores_file = Path("servidores.json")
    regionais_file = Path("estrutura_regionais.json")
    
    # Verifica se há estrutura hierárquica
    estrutura_hierarquica = False
    try:
        from gerenciar_regionais import GerenciadorRegionais
        gerenciador = GerenciadorRegionais()
        regionais = gerenciador.listar_regionais()
        estrutura_hierarquica = len(regionais) > 0
    except:
        estrutura_hierarquica = False
    
    return {
        'environment': environment_file.exists(),
        'servidores': servidores_file.exists(),
        'regionais': regionais_file.exists(),
        'estrutura_hierarquica': estrutura_hierarquica
    }

def main():
    """Função principal"""
    print("Iniciando Interface Web de Configuracao")
    print("=" * 50)
    
    # Verifica dependências
    print("Verificando dependencias...")
    dependencias_faltando = verificar_dependencias()
    
    if dependencias_faltando:
        print(f"Dependencias faltando: {', '.join(dependencias_faltando)}")
        instalar_dependencias(dependencias_faltando)
    else:
        print("Dependencias verificadas")
    
    # Verifica configuração
    print("\nVerificando configuracao...")
    config_status = verificar_configuracao()
    
    if not config_status['environment']:
        print("Arquivo environment.json nao encontrado")
    if not config_status['regionais']:
        print("Nenhuma estrutura de servidores encontrada")
    
    if config_status['estrutura_hierarquica']:
        print("Estrutura hierarquica detectada")
    
    if not any([config_status['environment'], config_status['servidores'], config_status['regionais']]):
        print("Sistema nao configurado. Use a interface web para configurar!")
        
    # O serviço web real é sempre iniciado pelo runner dedicado,
    # com restart controlado para impedir múltiplas instâncias.
    print("\nReiniciando servico web..." )
    print("URL: http://localhost:5000")
    print("=" * 50)
    
    # Verifica e cria diretórios necessários
    try:
        from config import ensure_directories
        ensure_directories()
        print("Diretorios verificados/criados:")
        print("   - Output: c:\\Users\\m.vbatista\\Desktop\\Automacao\\output")
        print("   - Regionais: c:\\Users\\m.vbatista\\Desktop\\Automacao\\output\\htmls_regionais")
        print("   - Logs: c:\\Users\\m.vbatista\\Desktop\\Automacao\\logs")
        
        # Verifica diretório de relatório preventiva
        from config import RELATORIO_PREVENTIVA_DIR
        print(f"   - Relatorio Preventiva: {RELATORIO_PREVENTIVA_DIR}")
    except Exception as e:
        print(f"Erro ao verificar diretorios: {e}")
    
    # Abre navegador após 2 segundos
    def abrir_navegador():
        time.sleep(2)
        try:
            webbrowser.open('http://localhost:5000')
            print("Navegador aberto automaticamente")
        except:
            print("Nao foi possivel abrir o navegador automaticamente")
            print("   Acesse manualmente: http://localhost:5000")
    
    import threading
    threading.Thread(target=abrir_navegador, daemon=True).start()

    # Reinicia o serviço web de forma controlada
    try:
        restart_script = Path(__file__).with_name("restart_web_service.ps1")
        subprocess.check_call([
            "powershell",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(restart_script)
        ])
        print("Servico web reiniciado com sucesso")
    except KeyboardInterrupt:
        print("\n\nInicializacao interrompida")
    except Exception as e:
        print(f"\nErro ao reiniciar servidor: {e}")
        print("\nTente executar diretamente:")
        print("   powershell -ExecutionPolicy Bypass -File .\\restart_web_service.ps1")

if __name__ == "__main__":
    main()