#!/usr/bin/env python3
"""
Script para corrigir os últimos erros de print malformados
"""

import re
from pathlib import Path

def corrigir_vm_manager():
    """Corrige especificamente o vm_manager.py"""
    arquivo_path = Path(__file__).parent / "vm_manager.py"
    
    if not arquivo_path.exists():
        print("❌ vm_manager.py não encontrado")
        return
    
    try:
        with open(arquivo_path, 'r', encoding='utf-8') as f:
            conteudo = f.read()
        
        # Substitui todas as ocorrências do padrão problemático
        conteudo_corrigido = conteudo.replace(
            'print(f"Erro ignorado em {}: {{e}}".format(__file__))',
            'print(f"Erro ignorado em {__file__}: {e}")'
        )
        
        if conteudo_corrigido != conteudo:
            with open(arquivo_path, 'w', encoding='utf-8') as f:
                f.write(conteudo_corrigido)
            
            print("✅ vm_manager.py: Prints corrigidos")
        else:
            print("ℹ️ vm_manager.py: Nenhuma correção necessária")
    
    except Exception as e:
        print(f"❌ Erro ao corrigir vm_manager.py: {e}")

def corrigir_urllib3_import():
    """Corrige o import do urllib3 no gerenciar_vms.py"""
    arquivo_path = Path(__file__).parent / "gerenciar_vms.py"
    
    if not arquivo_path.exists():
        print("❌ gerenciar_vms.py não encontrado")
        return
    
    try:
        with open(arquivo_path, 'r', encoding='utf-8') as f:
            conteudo = f.read()
        
        # Substitui o import problemático
        if 'from requests.packages.urllib3.exceptions import InsecureRequestWarning' in conteudo:
            conteudo_corrigido = conteudo.replace(
                'from requests.packages.urllib3.exceptions import InsecureRequestWarning',
                '''try:
    from urllib3.exceptions import InsecureRequestWarning
except ImportError:
    try:
        from requests.packages.urllib3.exceptions import InsecureRequestWarning
    except ImportError:
        # Fallback se nenhum funcionar
        class InsecureRequestWarning(Warning):
            pass'''
            )
            
            with open(arquivo_path, 'w', encoding='utf-8') as f:
                f.write(conteudo_corrigido)
            
            print("✅ gerenciar_vms.py: Import do urllib3 corrigido")
        else:
            print("ℹ️ gerenciar_vms.py: Import já corrigido")
    
    except Exception as e:
        print(f"❌ Erro ao corrigir gerenciar_vms.py: {e}")

def main():
    """Função principal"""
    print("🔧 CORREÇÃO FINAL DE PRINTS MALFORMADOS")
    print("="*50)
    
    corrigir_vm_manager()
    corrigir_urllib3_import()
    
    print("\n🎉 Correções finais concluídas!")

if __name__ == "__main__":
    main()