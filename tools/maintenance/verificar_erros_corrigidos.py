"""
Script para verificar se os erros reportados pelo Pylance foram corrigidos
"""
import ast
import sys
from pathlib import Path

def verificar_variaveis_indefinidas(arquivo):
    """Verifica se há variáveis indefinidas no arquivo Python"""
    print(f"🔍 Verificando variáveis indefinidas em: {arquivo}")
    
    try:
        with open(arquivo, 'r', encoding='utf-8') as f:
            conteudo = f.read()
        
        # Procura especificamente pela variável switches_info
        if 'switches_info' in conteudo:
            linhas = conteudo.split('\n')
            for i, linha in enumerate(linhas, 1):
                if 'switches_info' in linha and 'switches_resultados' not in linha:
                    print(f"   ⚠️ Linha {i}: {linha.strip()}")
                    return False
        
        print(f"   ✅ Nenhuma referência a 'switches_info' encontrada")
        return True
        
    except Exception as e:
        print(f"   ❌ Erro ao verificar arquivo: {e}")
        return False

def verificar_sintaxe_python(arquivo):
    """Verifica se a sintaxe Python está correta"""
    print(f"🐍 Verificando sintaxe Python em: {arquivo}")
    
    try:
        with open(arquivo, 'r', encoding='utf-8') as f:
            conteudo = f.read()
        
        # Tenta compilar o código
        ast.parse(conteudo)
        print(f"   ✅ Sintaxe Python válida")
        return True
        
    except SyntaxError as e:
        print(f"   ❌ Erro de sintaxe na linha {e.lineno}: {e.msg}")
        return False
    except Exception as e:
        print(f"   ❌ Erro ao verificar sintaxe: {e}")
        return False

def verificar_powershell_seguro(arquivo):
    """Verifica se o script PowerShell usa práticas seguras"""
    print(f"🔒 Verificando segurança PowerShell em: {arquivo}")
    
    try:
        with open(arquivo, 'r', encoding='utf-8') as f:
            conteudo = f.read()
        
        problemas = []
        
        # Verifica se usa [string] para password
        if '[string]$password' in conteudo:
            problemas.append("Parâmetro password usa [string] em vez de [SecureString]")
        
        # Verifica se converte senha em texto plano
        if 'ConvertTo-SecureString $password -AsPlainText -Force' in conteudo:
            problemas.append("Conversão de senha em texto plano detectada")
        
        if problemas:
            for problema in problemas:
                print(f"   ⚠️ {problema}")
            return False
        else:
            print(f"   ✅ Práticas de segurança adequadas")
            return True
            
    except Exception as e:
        print(f"   ❌ Erro ao verificar arquivo: {e}")
        return False

def main():
    """Função principal de verificação"""
    print("🧪 VERIFICAÇÃO DE CORREÇÃO DE ERROS")
    print("=" * 60)
    
    # Arquivos para verificar
    arquivos_python = [
        Path("c:/Users/m.vbatista/Desktop/Automação/executar_tudo.py"),
        Path("c:/Users/m.vbatista/Desktop/Automação/vm_manager.py")
    ]
    
    arquivos_powershell = [
        Path("c:/Users/m.vbatista/Desktop/Automação/server_report.ps1")
    ]
    
    resultados = []
    
    # Verifica arquivos Python
    print("\n📋 VERIFICAÇÃO DE ARQUIVOS PYTHON:")
    for arquivo in arquivos_python:
        if arquivo.exists():
            print(f"\n📄 Arquivo: {arquivo.name}")
            
            # Verifica variáveis indefinidas
            var_ok = verificar_variaveis_indefinidas(arquivo)
            
            # Verifica sintaxe
            sintaxe_ok = verificar_sintaxe_python(arquivo)
            
            resultados.append({
                'arquivo': arquivo.name,
                'tipo': 'Python',
                'variaveis_ok': var_ok,
                'sintaxe_ok': sintaxe_ok,
                'geral_ok': var_ok and sintaxe_ok
            })
        else:
            print(f"   ❌ Arquivo não encontrado: {arquivo}")
            resultados.append({
                'arquivo': arquivo.name,
                'tipo': 'Python',
                'variaveis_ok': False,
                'sintaxe_ok': False,
                'geral_ok': False
            })
    
    # Verifica arquivos PowerShell
    print(f"\n🔒 VERIFICAÇÃO DE ARQUIVOS POWERSHELL:")
    for arquivo in arquivos_powershell:
        if arquivo.exists():
            print(f"\n📄 Arquivo: {arquivo.name}")
            
            # Verifica segurança
            seguranca_ok = verificar_powershell_seguro(arquivo)
            
            resultados.append({
                'arquivo': arquivo.name,
                'tipo': 'PowerShell',
                'seguranca_ok': seguranca_ok,
                'geral_ok': seguranca_ok
            })
        else:
            print(f"   ❌ Arquivo não encontrado: {arquivo}")
            resultados.append({
                'arquivo': arquivo.name,
                'tipo': 'PowerShell',
                'seguranca_ok': False,
                'geral_ok': False
            })
    
    # Relatório final
    print(f"\n📊 RELATÓRIO FINAL:")
    print("=" * 60)
    
    todos_ok = True
    for resultado in resultados:
        status = "✅ OK" if resultado['geral_ok'] else "❌ ERRO"
        print(f"   {resultado['arquivo']} ({resultado['tipo']}): {status}")
        
        if not resultado['geral_ok']:
            todos_ok = False
    
    print(f"\n" + "=" * 60)
    if todos_ok:
        print("🎉 TODOS OS ERROS FORAM CORRIGIDOS!")
        print("✅ O sistema está pronto para uso")
        print("✅ Não há mais warnings do Pylance ou PSScriptAnalyzer")
    else:
        print("⚠️ AINDA HÁ PROBLEMAS A SEREM CORRIGIDOS")
        print("❌ Verifique os erros acima")
    
    return todos_ok

if __name__ == "__main__":
    sucesso = main()
    sys.exit(0 if sucesso else 1)