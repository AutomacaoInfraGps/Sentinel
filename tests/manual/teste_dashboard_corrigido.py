#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Teste do dashboard com correções dos servidores iDRAC/iLO
"""

import subprocess
import sys
from pathlib import Path

print("🚀 Teste do Dashboard com Correções")
print("=" * 60)

PROJECT_ROOT = Path(__file__).parent

print("🔍 Executando apenas a seção de servidores físicos...")

try:
    # Executa apenas a parte dos servidores do executar_tudo.py
    result = subprocess.run(
        ["python", str(PROJECT_ROOT / "executar_tudo.py")], 
        cwd=str(PROJECT_ROOT), 
        capture_output=True, 
        text=True,
        timeout=300
    )
    
    print(f"📊 Código de saída: {result.returncode}")
    
    if result.stdout:
        # Filtra apenas as linhas relevantes dos servidores
        lines = result.stdout.split('\n')
        server_lines = [line for line in lines if any(keyword in line for keyword in [
            '[EXEC] Coletando', 'iDRAC', 'iLO', '[ERRO]', '[OK]', 'HTML gerado'
        ])]
        
        print(f"\n📤 Saída dos servidores:")
        for line in server_lines[:20]:  # Mostra apenas as primeiras 20 linhas relevantes
            print(f"   {line}")
    
    if result.stderr:
        print(f"\n📥 Erros:")
        print(result.stderr[:1000])  # Primeiros 1000 caracteres
    
    # Verifica se o dashboard foi gerado
    dashboard_path = PROJECT_ROOT / "output" / "dashboard_final.html"
    if dashboard_path.exists():
        size = dashboard_path.stat().st_size
        print(f"\n✅ Dashboard gerado: {size} bytes")
        
        # Verifica se contém informações dos servidores
        with open(dashboard_path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        if "RG_GLOBAL SEGURANÇA" in content:
            print("   ✅ Contém dados do RG_GLOBAL SEGURANÇA")
        if "RG_MOTUS" in content:
            print("   ✅ Contém dados do RG_MOTUS")
        if "RG_GALAXIA" in content:
            print("   ✅ Contém dados do RG_GALAXIA")
        if "RG_REGIONAL BELO HORIZONTE" in content:
            print("   ✅ Contém dados do RG_REGIONAL BELO HORIZONTE")
            
        # Conta quantos servidores aparecem como OK vs Erro
        ok_count = content.count("server-status-ok")
        error_count = content.count("server-status-error")
        print(f"   📊 Servidores OK: {ok_count}")
        print(f"   📊 Servidores com Erro: {error_count}")
        
    else:
        print(f"\n❌ Dashboard não foi gerado!")

except subprocess.TimeoutExpired:
    print(f"⏰ Timeout na execução")
except Exception as e:
    print(f"❌ Erro inesperado: {e}")

print("\n" + "=" * 60)
print("✅ Teste concluído!")