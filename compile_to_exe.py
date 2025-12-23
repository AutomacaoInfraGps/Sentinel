"""
Script automatizado para compilar o Sistema de Automação para .exe
"""
import subprocess
import sys
import os
from pathlib import Path
import shutil

def verificar_pyinstaller():
    """Verifica se PyInstaller está instalado"""
    try:
        import PyInstaller
        print("✅ PyInstaller encontrado")
        return True
    except ImportError:
        print("❌ PyInstaller não encontrado. Instalando...")
        try:
            subprocess.run([sys.executable, "-m", "pip", "install", "pyinstaller"], check=True)
            print("✅ PyInstaller instalado com sucesso")
            return True
        except subprocess.CalledProcessError:
            print("❌ Erro ao instalar PyInstaller")
            return False

def limpar_builds_anteriores():
    """Remove builds anteriores"""
    print("🧹 Limpando builds anteriores...")
    
    dirs_to_clean = ["build", "dist", "__pycache__"]
    files_to_clean = ["*.spec"]
    
    for dir_name in dirs_to_clean:
        if Path(dir_name).exists():
            shutil.rmtree(dir_name)
            print(f"   🗑️ Removido: {dir_name}")
    
    # Remove arquivos .spec
    for spec_file in Path(".").glob("*.spec"):
        spec_file.unlink()
        print(f"   🗑️ Removido: {spec_file}")

def verificar_arquivos_necessarios():
    """Verifica se os arquivos principais existem"""
    print("📋 Verificando arquivos necessários...")
    
    arquivos_obrigatorios = [
        "executar_tudo.py",
        "config.py",
    ]
    
    arquivos_opcionais = [
        "credentials.py",
        "data_store.py",
        "vm_manager.py",
    ]
    
    pastas_importantes = [
        "templates",
        "output",
        "data",
    ]
    
    # Verifica arquivos obrigatórios
    for arquivo in arquivos_obrigatorios:
        if not Path(arquivo).exists():
            print(f"❌ Arquivo obrigatório não encontrado: {arquivo}")
            return False
        print(f"   ✅ {arquivo}")
    
    # Verifica arquivos opcionais
    for arquivo in arquivos_opcionais:
        if Path(arquivo).exists():
            print(f"   ✅ {arquivo}")
        else:
            print(f"   ⚠️ {arquivo} (opcional, não encontrado)")
    
    # Verifica pastas
    for pasta in pastas_importantes:
        if Path(pasta).exists():
            print(f"   ✅ {pasta}/")
        else:
            print(f"   ⚠️ {pasta}/ (será criada se necessário)")
    
    return True

def criar_arquivo_spec():
    """Cria arquivo .spec personalizado"""
    print("📝 Criando arquivo .spec personalizado...")
    
    spec_content = '''# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

# Arquivos de dados a serem incluídos
datas = [
    ('*.ps1', '.'),
    ('*.json', '.'),
    ('*.txt', '.'),
    ('*.xlsx', '.'),
]

# Adiciona pastas se existirem
import os
if os.path.exists('templates'):
    datas.append(('templates', 'templates'))
if os.path.exists('output'):
    datas.append(('output', 'output'))
if os.path.exists('data'):
    datas.append(('data', 'data'))
if os.path.exists('logs'):
    datas.append(('logs', 'logs'))

# Módulos ocultos (dependências não detectadas automaticamente)
hiddenimports = [
    'requests',
    'urllib3',
    'pathlib',
    'json',
    'subprocess',
    'webbrowser',
    'datetime',
    'config',
    'credentials',
    'data_store',
    'vm_manager',
    'gerenciar_servidores',
    'gerenciar_switches',
    'gerenciar_vms',
    'gerenciar_regionais',
    'gerenciar_fortigate',
]

a = Analysis(
    ['executar_tudo.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='SistemaAutomacaoInfraestrutura',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
'''
    
    with open("SistemaAutomacao.spec", "w", encoding="utf-8") as f:
        f.write(spec_content)
    
    print("   ✅ Arquivo .spec criado: SistemaAutomacao.spec")

def compilar_projeto():
    """Executa a compilação"""
    print("🔧 Iniciando compilação...")
    
    # Usa o arquivo .spec personalizado
    cmd = ["pyinstaller", "SistemaAutomacao.spec"]
    
    print(f"   Comando: {' '.join(cmd)}")
    
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        print("✅ Compilação concluída com sucesso!")
        
        # Verifica se o arquivo foi criado
        exe_path = Path("dist/SistemaAutomacaoInfraestrutura.exe")
        if exe_path.exists():
            size_mb = exe_path.stat().st_size / (1024 * 1024)
            print(f"📊 Executável criado: {exe_path}")
            print(f"📊 Tamanho: {size_mb:.1f} MB")
            return True
        else:
            print("❌ Executável não foi criado")
            return False
        
    except subprocess.CalledProcessError as e:
        print("❌ Erro na compilação:")
        print("STDOUT:", result.stdout if 'result' in locals() else "N/A")
        print("STDERR:", result.stderr if 'result' in locals() else "N/A")
        return False

def testar_executavel():
    """Testa o executável gerado"""
    print("🧪 Testando executável...")
    
    exe_path = Path("dist/SistemaAutomacaoInfraestrutura.exe")
    if not exe_path.exists():
        print("❌ Executável não encontrado para teste")
        return False
    
    print("   ℹ️ Para testar completamente, execute manualmente:")
    print(f"   📁 {exe_path.absolute()}")
    
    return True

def criar_pacote_distribuicao():
    """Cria um pacote para distribuição"""
    print("📦 Criando pacote de distribuição...")
    
    # Cria pasta de distribuição
    dist_folder = Path("distribuicao")
    if dist_folder.exists():
        shutil.rmtree(dist_folder)
    
    dist_folder.mkdir()
    
    # Copia o executável
    exe_source = Path("dist/SistemaAutomacaoInfraestrutura.exe")
    if exe_source.exists():
        shutil.copy2(exe_source, dist_folder / "SistemaAutomacaoInfraestrutura.exe")
        print("   ✅ Executável copiado")
    
    # Cria arquivo README para distribuição
    readme_content = """# Sistema de Automação de Infraestrutura

## Como usar:
1. Execute o arquivo SistemaAutomacaoInfraestrutura.exe
2. O sistema irá gerar relatórios na pasta "Relatório Preventiva" na área de trabalho
3. Os relatórios serão organizados por data (Ano/Mês/Dia)

## Requisitos:
- Windows 10 ou superior
- PowerShell habilitado
- Acesso à rede para conectar aos servidores

## Suporte:
- Em caso de problemas, verifique se o Windows Defender não está bloqueando o executável
- Execute como administrador se necessário

Versão compilada em: """ + str(Path().cwd()) + """
"""
    
    with open(dist_folder / "LEIA-ME.txt", "w", encoding="utf-8") as f:
        f.write(readme_content)
    
    print(f"   ✅ Pacote criado em: {dist_folder.absolute()}")
    return True

def main():
    """Função principal"""
    print("🚀 COMPILAÇÃO AUTOMÁTICA - SISTEMA DE AUTOMAÇÃO")
    print("=" * 60)
    
    # Passo 1: Verificar PyInstaller
    if not verificar_pyinstaller():
        return False
    
    # Passo 2: Limpar builds anteriores
    limpar_builds_anteriores()
    
    # Passo 3: Verificar arquivos necessários
    if not verificar_arquivos_necessarios():
        return False
    
    # Passo 4: Criar arquivo .spec
    criar_arquivo_spec()
    
    # Passo 5: Compilar
    if not compilar_projeto():
        return False
    
    # Passo 6: Testar
    if not testar_executavel():
        return False
    
    # Passo 7: Criar pacote de distribuição
    if not criar_pacote_distribuicao():
        return False
    
    print("\n" + "=" * 60)
    print("🎉 COMPILAÇÃO CONCLUÍDA COM SUCESSO!")
    print("✅ Executável criado e testado")
    print("📦 Pacote de distribuição pronto")
    print(f"📁 Localização: {Path('distribuicao').absolute()}")
    print("\n🎯 PRÓXIMOS PASSOS:")
    print("1. Teste o executável em uma máquina diferente")
    print("2. Verifique se todas as funcionalidades funcionam")
    print("3. Distribua o pacote para os usuários finais")
    
    return True

if __name__ == "__main__":
    try:
        sucesso = main()
        if not sucesso:
            print("\n❌ Compilação falhou. Verifique os erros acima.")
            sys.exit(1)
    except KeyboardInterrupt:
        print("\n⚠️ Compilação cancelada pelo usuário")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Erro inesperado: {e}")
        sys.exit(1)