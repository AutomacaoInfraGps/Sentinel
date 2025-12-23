#!/usr/bin/env python3
"""
Verificação final dos erros do projeto
"""

import ast
import sys
from pathlib import Path

def verificar_sintaxe_arquivos():
    """Verifica sintaxe de todos os arquivos Python"""
    project_root = Path(__file__).parent.absolute()
    arquivos_python = list(project_root.glob("*.py"))
    
    erros_sintaxe = []
    arquivos_ok = []
    
    print("🔍 VERIFICAÇÃO FINAL DE SINTAXE")
    print("="*50)
    
    for arquivo in arquivos_python:
        if arquivo.name.startswith('verificacao_final'):
            continue
            
        try:
            with open(arquivo, 'r', encoding='utf-8') as f:
                codigo = f.read()
            
            # Verifica sintaxe
            try:
                ast.parse(codigo)
                arquivos_ok.append(arquivo.name)
                print(f"✅ {arquivo.name}")
            except SyntaxError as e:
                erros_sintaxe.append({
                    "arquivo": arquivo.name,
                    "erro": str(e),
                    "linha": e.lineno
                })
                print(f"❌ {arquivo.name}: {e.msg} (linha {e.lineno})")
        
        except Exception as e:
            print(f"⚠️ {arquivo.name}: Erro ao ler arquivo - {e}")
    
    print(f"\n📊 RESUMO:")
    print(f"   ✅ Arquivos OK: {len(arquivos_ok)}")
    print(f"   ❌ Arquivos com erro: {len(erros_sintaxe)}")
    
    if erros_sintaxe:
        print(f"\n🚨 ERROS RESTANTES:")
        for erro in erros_sintaxe:
            print(f"   • {erro['arquivo']}: {erro['erro']} (linha {erro['linha']})")
        return False
    else:
        print(f"\n🎉 TODOS OS ARQUIVOS ESTÃO SINTATICAMENTE CORRETOS!")
        return True

def testar_imports_principais():
    """Testa imports dos módulos principais"""
    print(f"\n🔍 TESTANDO IMPORTS PRINCIPAIS")
    print("="*50)
    
    modulos_principais = [
        "config",
        "credentials", 
        "gerenciar_servidores",
        "web_config"
    ]
    
    imports_ok = []
    imports_erro = []
    
    for modulo in modulos_principais:
        try:
            __import__(modulo)
            imports_ok.append(modulo)
            print(f"✅ {modulo}")
        except Exception as e:
            imports_erro.append({"modulo": modulo, "erro": str(e)})
            print(f"❌ {modulo}: {e}")
    
    print(f"\n📊 RESUMO IMPORTS:")
    print(f"   ✅ Imports OK: {len(imports_ok)}")
    print(f"   ❌ Imports com erro: {len(imports_erro)}")
    
    return len(imports_erro) == 0

def main():
    """Função principal"""
    print("🏁 VERIFICAÇÃO FINAL DO PROJETO")
    print("="*70)
    
    sintaxe_ok = verificar_sintaxe_arquivos()
    imports_ok = testar_imports_principais()
    
    print(f"\n" + "="*70)
    print("🏆 RESULTADO FINAL")
    print("="*70)
    
    if sintaxe_ok and imports_ok:
        status = "🟢 EXCELENTE"
        mensagem = "Projeto sem erros críticos!"
        codigo_saida = 0
    elif sintaxe_ok:
        status = "🟡 BOM"
        mensagem = "Sintaxe OK, mas alguns imports falharam"
        codigo_saida = 1
    else:
        status = "🔴 CRÍTICO"
        mensagem = "Ainda existem erros de sintaxe"
        codigo_saida = 2
    
    print(f"Status: {status}")
    print(f"Resultado: {mensagem}")
    
    if codigo_saida == 0:
        print(f"\n🎉 PARABÉNS! Seu projeto está funcionando corretamente!")
        print(f"💡 Você pode executar: python iniciar_web.py")
    else:
        print(f"\n⚠️ Ainda há alguns problemas para resolver.")
        print(f"💡 Verifique os erros listados acima.")
    
    return codigo_saida

if __name__ == "__main__":
    exit(main())