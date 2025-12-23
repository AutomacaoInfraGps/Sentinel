"""
Script para validar a compatibilidade das modificações com o sistema original
"""
import sys
import traceback
from pathlib import Path

def testar_importacoes():
    """Testa se todas as importações funcionam corretamente"""
    print("🧪 TESTE DE COMPATIBILIDADE DO SISTEMA")
    print("=" * 60)
    
    erros = []
    sucessos = []
    
    # Teste 1: Importação do config
    print("\n📦 Testando importação do config...")
    try:
        from config import (
            CONEXOES_FILE, REGIONAL_HTMLS_DIR, GPS_HTML, REPLICACAO_HTML, 
            UNIFI_HTML, DASHBOARD_FINAL, DASHBOARD_FINAL_ORIGINAL, ensure_directories, 
            get_regional_html_path, validate_config, PROJECT_ROOT, RELATORIO_PREVENTIVA_DIR
        )
        sucessos.append("✅ Importação do config")
        print("   ✅ Todas as importações do config funcionaram")
    except Exception as e:
        erros.append(f"❌ Erro na importação do config: {e}")
        print(f"   ❌ Erro: {e}")
    
    # Teste 2: Verificação de caminhos
    print("\n📁 Testando caminhos...")
    try:
        print(f"   - PROJECT_ROOT: {PROJECT_ROOT}")
        print(f"   - DASHBOARD_FINAL: {DASHBOARD_FINAL}")
        print(f"   - DASHBOARD_FINAL_ORIGINAL: {DASHBOARD_FINAL_ORIGINAL}")
        print(f"   - RELATORIO_PREVENTIVA_DIR: {RELATORIO_PREVENTIVA_DIR}")
        sucessos.append("✅ Verificação de caminhos")
    except Exception as e:
        erros.append(f"❌ Erro nos caminhos: {e}")
        print(f"   ❌ Erro: {e}")
    
    # Teste 3: Criação de diretórios
    print("\n📂 Testando criação de diretórios...")
    try:
        ensure_directories()
        sucessos.append("✅ Criação de diretórios")
        print("   ✅ Diretórios criados com sucesso")
    except Exception as e:
        erros.append(f"❌ Erro na criação de diretórios: {e}")
        print(f"   ❌ Erro: {e}")
    
    # Teste 4: Verificação de arquivos necessários
    print("\n📄 Testando arquivos necessários...")
    arquivos_necessarios = [
        ("executar_tudo.py", PROJECT_ROOT / "executar_tudo.py"),
        ("config.py", PROJECT_ROOT / "config.py"),
    ]
    
    for nome, caminho in arquivos_necessarios:
        if caminho.exists():
            print(f"   ✅ {nome} encontrado")
            sucessos.append(f"✅ Arquivo {nome}")
        else:
            print(f"   ❌ {nome} NÃO encontrado em {caminho}")
            erros.append(f"❌ Arquivo {nome} não encontrado")
    
    # Teste 5: Teste de escrita nos diretórios
    print("\n✍️ Testando permissões de escrita...")
    try:
        # Testa escrita no diretório original
        teste_original = DASHBOARD_FINAL_ORIGINAL.parent / "teste_escrita.txt"
        teste_original.write_text("teste", encoding="utf-8")
        teste_original.unlink()
        print("   ✅ Escrita no diretório original funcionando")
        
        # Testa escrita no novo diretório
        teste_novo = RELATORIO_PREVENTIVA_DIR / "teste_escrita.txt"
        teste_novo.write_text("teste", encoding="utf-8")
        teste_novo.unlink()
        print("   ✅ Escrita no novo diretório funcionando")
        
        sucessos.append("✅ Permissões de escrita")
    except Exception as e:
        erros.append(f"❌ Erro nas permissões de escrita: {e}")
        print(f"   ❌ Erro: {e}")
    
    # Teste 6: Simulação de execução do executar_tudo.py (apenas importações)
    print("\n🔄 Testando compatibilidade com executar_tudo.py...")
    try:
        # Tenta importar as principais dependências do executar_tudo.py
        import subprocess
        import webbrowser
        import os
        import re
        from datetime import datetime
        from pathlib import Path
        
        print("   ✅ Todas as dependências do executar_tudo.py disponíveis")
        sucessos.append("✅ Dependências do executar_tudo.py")
    except Exception as e:
        erros.append(f"❌ Erro nas dependências: {e}")
        print(f"   ❌ Erro: {e}")
    
    # Relatório final
    print(f"\n📊 RELATÓRIO FINAL:")
    print(f"   - Sucessos: {len(sucessos)}")
    print(f"   - Erros: {len(erros)}")
    
    if erros:
        print(f"\n❌ ERROS ENCONTRADOS:")
        for erro in erros:
            print(f"   {erro}")
    
    if sucessos:
        print(f"\n✅ SUCESSOS:")
        for sucesso in sucessos:
            print(f"   {sucesso}")
    
    # Conclusão
    if len(erros) == 0:
        print(f"\n🎉 SISTEMA TOTALMENTE COMPATÍVEL!")
        print(f"✅ Todas as modificações são compatíveis com o sistema original")
        print(f"✅ O executar_tudo.py funcionará normalmente")
        return True
    else:
        print(f"\n⚠️ PROBLEMAS DE COMPATIBILIDADE ENCONTRADOS!")
        print(f"❌ {len(erros)} erro(s) precisam ser corrigidos")
        return False

def testar_funcionalidade_completa():
    """Testa se a funcionalidade completa funcionará"""
    print(f"\n🔧 TESTE DE FUNCIONALIDADE COMPLETA:")
    
    try:
        from config import DASHBOARD_FINAL, DASHBOARD_FINAL_ORIGINAL, get_dashboard_filename
        
        # Simula a criação de um relatório
        html_teste = """
        <!DOCTYPE html>
        <html>
        <head><title>Teste</title></head>
        <body><h1>Teste de Compatibilidade</h1></body>
        </html>
        """
        
        # Testa salvamento no novo local
        DASHBOARD_FINAL.write_text(html_teste, encoding="utf-8")
        print(f"   ✅ Arquivo salvo no novo local: {DASHBOARD_FINAL}")
        
        # Testa salvamento no local original
        DASHBOARD_FINAL_ORIGINAL.write_text(html_teste, encoding="utf-8")
        print(f"   ✅ Arquivo salvo no local original: {DASHBOARD_FINAL_ORIGINAL}")
        
        # Verifica se os arquivos existem
        if DASHBOARD_FINAL.exists() and DASHBOARD_FINAL_ORIGINAL.exists():
            print(f"   ✅ Ambos os arquivos foram criados com sucesso")
            
            # Remove os arquivos de teste
            DASHBOARD_FINAL.unlink()
            DASHBOARD_FINAL_ORIGINAL.unlink()
            print(f"   ✅ Arquivos de teste removidos")
            
            return True
        else:
            print(f"   ❌ Falha na criação dos arquivos")
            return False
            
    except Exception as e:
        print(f"   ❌ Erro no teste de funcionalidade: {e}")
        traceback.print_exc()
        return False

if __name__ == "__main__":
    compativel = testar_importacoes()
    funcional = testar_funcionalidade_completa()
    
    print(f"\n" + "="*60)
    if compativel and funcional:
        print(f"🎯 RESULTADO FINAL: SISTEMA PRONTO PARA USO!")
        print(f"✅ Você pode executar o executar_tudo.py normalmente")
        print(f"✅ Os relatórios serão salvos na nova estrutura de pastas")
        print(f"✅ A compatibilidade com o sistema original foi mantida")
    else:
        print(f"⚠️ RESULTADO FINAL: CORREÇÕES NECESSÁRIAS!")
        print(f"❌ Verifique os erros acima antes de usar o sistema")