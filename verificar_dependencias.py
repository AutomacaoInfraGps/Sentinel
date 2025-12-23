"""
Script para verificar e listar todas as dependências do projeto
"""
import sys
import importlib
import subprocess
from pathlib import Path

def verificar_modulo(nome_modulo):
    """Verifica se um módulo está disponível"""
    try:
        importlib.import_module(nome_modulo)
        return True
    except ImportError:
        return False

def listar_dependencias_projeto():
    """Lista todas as dependências encontradas no projeto"""
    print("🔍 ANÁLISE DE DEPENDÊNCIAS DO PROJETO")
    print("=" * 50)
    
    # Módulos padrão do Python (built-in)
    modulos_builtin = [
        'os', 'sys', 'subprocess', 'pathlib', 'json', 'datetime', 
        'webbrowser', 're', 'codecs', 'locale', 'tempfile', 'shutil'
    ]
    
    # Módulos externos (precisam ser instalados)
    modulos_externos = [
        'requests', 'urllib3', 'playwright'
    ]
    
    # Módulos do próprio projeto
    modulos_projeto = [
        'config', 'credentials', 'data_store', 'vm_manager',
        'gerenciar_servidores', 'gerenciar_switches', 'gerenciar_vms',
        'gerenciar_regionais', 'gerenciar_fortigate'
    ]
    
    print("\n📦 MÓDULOS BUILT-IN (Python padrão):")
    for modulo in modulos_builtin:
        status = "✅" if verificar_modulo(modulo) else "❌"
        print(f"   {status} {modulo}")
    
    print("\n🌐 MÓDULOS EXTERNOS (pip install):")
    externos_faltando = []
    for modulo in modulos_externos:
        if verificar_modulo(modulo):
            print(f"   ✅ {modulo}")
        else:
            print(f"   ❌ {modulo} (FALTANDO)")
            externos_faltando.append(modulo)
    
    print("\n🏠 MÓDULOS DO PROJETO:")
    projeto_faltando = []
    for modulo in modulos_projeto:
        arquivo_py = Path(f"{modulo}.py")
        if arquivo_py.exists():
            print(f"   ✅ {modulo} ({arquivo_py})")
        else:
            print(f"   ⚠️ {modulo} (arquivo não encontrado)")
            projeto_faltando.append(modulo)
    
    # Resumo
    print(f"\n📊 RESUMO:")
    print(f"   - Módulos built-in: {len(modulos_builtin)} (todos disponíveis)")
    print(f"   - Módulos externos: {len(modulos_externos) - len(externos_faltando)}/{len(modulos_externos)} disponíveis")
    print(f"   - Módulos do projeto: {len(modulos_projeto) - len(projeto_faltando)}/{len(modulos_projeto)} encontrados")
    
    if externos_faltando:
        print(f"\n⚠️ MÓDULOS EXTERNOS FALTANDO:")
        for modulo in externos_faltando:
            print(f"   pip install {modulo}")
    
    if projeto_faltando:
        print(f"\n⚠️ ARQUIVOS DO PROJETO FALTANDO:")
        for modulo in projeto_faltando:
            print(f"   {modulo}.py")
    
    return len(externos_faltando) == 0 and len(projeto_faltando) == 0

def gerar_requirements_txt():
    """Gera arquivo requirements.txt"""
    print("\n📝 Gerando requirements.txt...")
    
    try:
        result = subprocess.run([sys.executable, "-m", "pip", "freeze"], 
                              capture_output=True, text=True, check=True)
        
        with open("requirements.txt", "w", encoding="utf-8") as f:
            f.write(result.stdout)
        
        print("   ✅ requirements.txt criado")
        
        # Mostra apenas as dependências relevantes
        linhas = result.stdout.strip().split('\n')
        relevantes = [linha for linha in linhas if any(pkg in linha.lower() 
                     for pkg in ['requests', 'urllib3', 'playwright', 'pyinstaller'])]
        
        if relevantes:
            print("   📋 Dependências relevantes encontradas:")
            for linha in relevantes:
                print(f"      {linha}")
        
        return True
        
    except subprocess.CalledProcessError as e:
        print(f"   ❌ Erro ao gerar requirements.txt: {e}")
        return False

def verificar_arquivos_dados():
    """Verifica arquivos de dados necessários"""
    print("\n📁 VERIFICANDO ARQUIVOS DE DADOS:")
    
    arquivos_importantes = [
        ("executar_tudo.py", "Script principal"),
        ("config.py", "Configurações"),
        ("Conexoes.txt", "Lista de conexões (opcional)"),
        ("servidores.json", "Configuração de servidores (opcional)"),
        ("environment.json", "Configurações de ambiente (opcional)"),
    ]
    
    pastas_importantes = [
        ("templates", "Templates HTML"),
        ("output", "Arquivos de saída"),
        ("data", "Dados do sistema"),
        ("logs", "Logs do sistema"),
    ]
    
    scripts_powershell = list(Path(".").glob("*.ps1"))
    
    # Verifica arquivos
    for arquivo, descricao in arquivos_importantes:
        if Path(arquivo).exists():
            print(f"   ✅ {arquivo} - {descricao}")
        else:
            print(f"   ⚠️ {arquivo} - {descricao} (não encontrado)")
    
    # Verifica pastas
    for pasta, descricao in pastas_importantes:
        pasta_path = Path(pasta)
        if pasta_path.exists():
            arquivos_count = len(list(pasta_path.rglob("*")))
            print(f"   ✅ {pasta}/ - {descricao} ({arquivos_count} arquivos)")
        else:
            print(f"   ⚠️ {pasta}/ - {descricao} (não encontrada)")
    
    # Verifica scripts PowerShell
    if scripts_powershell:
        print(f"   ✅ Scripts PowerShell encontrados: {len(scripts_powershell)}")
        for script in scripts_powershell:
            print(f"      📜 {script.name}")
    else:
        print(f"   ⚠️ Nenhum script PowerShell (.ps1) encontrado")

def main():
    """Função principal"""
    print("🔍 VERIFICAÇÃO COMPLETA DE DEPENDÊNCIAS")
    print("=" * 60)
    
    # Verifica dependências Python
    deps_ok = listar_dependencias_projeto()
    
    # Gera requirements.txt
    req_ok = gerar_requirements_txt()
    
    # Verifica arquivos de dados
    verificar_arquivos_dados()
    
    print("\n" + "=" * 60)
    if deps_ok:
        print("✅ TODAS AS DEPENDÊNCIAS ESTÃO OK!")
        print("🚀 Projeto pronto para compilação")
        print("\n🎯 PRÓXIMO PASSO:")
        print("   Execute: python compile_to_exe.py")
    else:
        print("⚠️ ALGUMAS DEPENDÊNCIAS ESTÃO FALTANDO")
        print("🔧 Instale as dependências faltando antes de compilar")
        print("\n🎯 COMANDOS PARA INSTALAR:")
        print("   pip install requests urllib3")
        print("   pip install pyinstaller")

if __name__ == "__main__":
    main()