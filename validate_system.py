"""
Script de validação do sistema escalável.
Verifica se todos os componentes estão funcionando corretamente.
"""

import sys
from pathlib import Path
from config import (
    PROJECT_ROOT, OUTPUT_DIR, REGIONAL_HTMLS_DIR, LOGS_DIR,
    CONEXOES_FILE, DASHBOARD_FINAL, GPS_HTML, REPLICACAO_HTML, UNIFI_HTML,
    ENV_CONFIG, validate_config
)

def check_file_structure():
    """Verifica se a estrutura de arquivos está correta"""
    print("📁 Verificando estrutura de arquivos...")
    
    required_files = [
        PROJECT_ROOT / "config.py",
        PROJECT_ROOT / "executar_tudo.py",
        PROJECT_ROOT / "setup.py",
        PROJECT_ROOT / "environment.json"
    ]
    
    # Arquivos opcionais (novo sistema)
    optional_files = [
        PROJECT_ROOT / "servidores.json",
        PROJECT_ROOT / "configure.py",
        PROJECT_ROOT / "manage.py",
        PROJECT_ROOT / "gerenciar_servidores.py"
    ]
    
    # Arquivo legado (compatibilidade)
    legacy_files = [CONEXOES_FILE]
    
    missing_files = []
    
    # Verifica arquivos obrigatórios
    print("📋 Arquivos obrigatórios:")
    for file_path in required_files:
        if file_path.exists():
            print(f"✅ {file_path.name}")
        else:
            print(f"❌ {file_path.name} - FALTANDO")
            missing_files.append(file_path)
    
    # Verifica arquivos do novo sistema
    print("\n🆕 Sistema de gerenciamento:")
    new_system_files = 0
    for file_path in optional_files:
        if file_path.exists():
            print(f"✅ {file_path.name}")
            new_system_files += 1
        else:
            print(f"⚪ {file_path.name} - Opcional")
    
    # Verifica arquivos legados
    print("\n📜 Compatibilidade legada:")
    for file_path in legacy_files:
        if file_path.exists():
            print(f"✅ {file_path.name} - Formato legado")
        else:
            print(f"⚪ {file_path.name} - Será criado automaticamente")
    
    # Recomendações
    if new_system_files >= 3:
        print("\n🎉 Sistema de gerenciamento moderno detectado!")
    else:
        print("\n💡 Recomendação: Execute 'python configure.py' para usar o sistema moderno")
    
    return len(missing_files) == 0

def check_directories():
    """Verifica se os diretórios estão criados"""
    print("\n📂 Verificando diretórios...")
    
    required_dirs = [OUTPUT_DIR, REGIONAL_HTMLS_DIR, LOGS_DIR]
    
    missing_dirs = []
    for dir_path in required_dirs:
        if dir_path.exists():
            print(f"✅ {dir_path.relative_to(PROJECT_ROOT)}")
        else:
            print(f"❌ {dir_path.relative_to(PROJECT_ROOT)} - FALTANDO")
            missing_dirs.append(dir_path)
    
    return len(missing_dirs) == 0

def check_configuration():
    """Verifica se as configurações estão válidas"""
    print("\n⚙️ Verificando configurações...")
    
    # Verifica se o environment.json foi carregado
    if not ENV_CONFIG:
        print("❌ environment.json não foi carregado corretamente")
        return False
    
    # Verifica seções obrigatórias
    required_sections = ["naos_server", "unifi_controller", "timeouts"]
    missing_sections = []
    
    for section in required_sections:
        if section in ENV_CONFIG:
            print(f"✅ Seção '{section}' encontrada")
        else:
            print(f"❌ Seção '{section}' faltando")
            missing_sections.append(section)
    
    # Verifica se as credenciais foram alteradas
    naos_config = ENV_CONFIG.get("naos_server", {})
    if naos_config.get("senha") == "ALTERE_AQUI":
        print("⚠️ Credenciais do NAOS ainda não foram configuradas")
    
    unifi_config = ENV_CONFIG.get("unifi_controller", {})
    if unifi_config.get("password") == "ALTERE_AQUI":
        print("⚠️ Credenciais do UniFi ainda não foram configuradas")
    
    return len(missing_sections) == 0

def check_connections_file():
    """Verifica se o arquivo de conexões está válido"""
    print("\n🔗 Verificando arquivo de conexões...")
    
    if not CONEXOES_FILE.exists():
        print(f"❌ Arquivo de conexões não encontrado: {CONEXOES_FILE}")
        return False
    
    try:
        content = CONEXOES_FILE.read_text(encoding="utf-8")
        
        # Conta quantas regionais estão definidas
        import re
        blocos = re.split(r"\n\s*\n", content.strip())
        regionais_validas = 0
        
        for bloco in blocos:
            if all(keyword in bloco for keyword in ["Nome:", "Tipo:", "IP:", "Usuario:", "Senha:"]):
                regionais_validas += 1
        
        print(f"✅ {regionais_validas} regionais encontradas no arquivo")
        
        if regionais_validas == 0:
            print("⚠️ Nenhuma regional válida encontrada")
            return False
        
        return True
        
    except Exception as e:
        print(f"❌ Erro ao ler arquivo de conexões: {e}")
        return False

def check_dependencies():
    """Verifica dependências Python"""
    print("\n📦 Verificando dependências...")
    
    dependencies = [
        "requests",
        "pathlib", 
        "json",
        "subprocess",
        "webbrowser"
    ]
    
    missing = []
    for dep in dependencies:
        try:
            __import__(dep)
            print(f"✅ {dep}")
        except ImportError:
            print(f"❌ {dep} - FALTANDO")
            missing.append(dep)
    
    return len(missing) == 0

def check_output_permissions():
    """Verifica se é possível escrever nos diretórios de saída"""
    print("\n🔐 Verificando permissões de escrita...")
    
    test_file = OUTPUT_DIR / "test_write.tmp"
    try:
        test_file.write_text("test", encoding="utf-8")
        test_file.unlink()
        print(f"✅ Permissão de escrita em {OUTPUT_DIR}")
        return True
    except Exception as e:
        print(f"❌ Erro de permissão em {OUTPUT_DIR}: {e}")
        return False

def generate_report():
    """Gera relatório de status do sistema"""
    print("\n📊 Gerando relatório de status...")
    
    report = {
        "project_root": str(PROJECT_ROOT),
        "output_dir": str(OUTPUT_DIR),
        "config_loaded": bool(ENV_CONFIG),
        "connections_file_exists": CONEXOES_FILE.exists(),
        "directories_created": all(d.exists() for d in [OUTPUT_DIR, REGIONAL_HTMLS_DIR, LOGS_DIR])
    }
    
    report_file = PROJECT_ROOT / "system_status.json"
    try:
        import json
        with open(report_file, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        print(f"✅ Relatório salvo em: {report_file}")
    except Exception as e:
        print(f"❌ Erro ao salvar relatório: {e}")

def main():
    """Função principal de validação"""
    print("🔍 Validação do Sistema Escalável")
    print("=" * 50)
    print(f"📁 Projeto: {PROJECT_ROOT}")
    print()
    
    checks = [
        ("Estrutura de Arquivos", check_file_structure),
        ("Diretórios", check_directories),
        ("Configurações", check_configuration),
        ("Arquivo de Conexões", check_connections_file),
        ("Dependências", check_dependencies),
        ("Permissões", check_output_permissions)
    ]
    
    results = []
    for name, check_func in checks:
        try:
            result = check_func()
            results.append((name, result))
        except Exception as e:
            print(f"❌ Erro durante verificação de {name}: {e}")
            results.append((name, False))
    
    # Validação adicional do config.py
    print("\n🔧 Validação adicional...")
    config_errors = validate_config()
    if config_errors:
        print("❌ Erros de configuração:")
        for error in config_errors:
            print(f"   - {error}")
        results.append(("Validação Config", False))
    else:
        print("✅ Validação do config.py passou")
        results.append(("Validação Config", True))
    
    # Gera relatório
    generate_report()
    
    # Resumo final
    print("\n" + "=" * 50)
    print("📋 RESUMO DA VALIDAÇÃO")
    print("=" * 50)
    
    passed = 0
    total = len(results)
    
    for name, result in results:
        status = "✅ PASSOU" if result else "❌ FALHOU"
        print(f"{name:.<30} {status}")
        if result:
            passed += 1
    
    print(f"\nResultado: {passed}/{total} verificações passaram")
    
    if passed == total:
        print("\n🎉 Sistema totalmente validado e pronto para uso!")
        print("\n📋 Próximos passos:")
        print("1. Execute: python executar_tudo.py")
        print("2. Verifique o dashboard gerado")
        return True
    else:
        print(f"\n⚠️ Sistema parcialmente validado ({passed}/{total})")
        print("Corrija os problemas acima antes de usar o sistema.")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)