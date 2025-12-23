#!/usr/bin/env python3
"""
Script simples para corrigir erros de sintaxe específicos
"""

import re
from pathlib import Path

def corrigir_prints_malformados():
    """Corrige prints malformados com f-strings"""
    project_root = Path(__file__).parent.absolute()
    
    arquivos_problematicos = [
        "gerenciar_switches.py",
        "gerenciar_vms.py", 
        "menu_principal.py",
        "vm_manager.py"
    ]
    
    for arquivo_nome in arquivos_problematicos:
        arquivo_path = project_root / arquivo_nome
        
        if not arquivo_path.exists():
            continue
            
        try:
            with open(arquivo_path, 'r', encoding='utf-8') as f:
                conteudo = f.read()
            
            # Padrão problemático: print(f"Erro em {}: {e}".format(__file__))
            conteudo_corrigido = re.sub(
                r'print\(f"([^"]*)\{([^}]*)\}: \{([^}]*)\}"\.format\(__file__\)\)',
                r'print(f"\1{__file__}: {\3}")',
                conteudo
            )
            
            # Padrão alternativo
            conteudo_corrigido = re.sub(
                r'print\(f"([^"]*)\{([^}]*)\}: \{([^}]*)\}"\.format\([^)]+\)\)',
                r'print(f"\1{\2}: {\3}")',
                conteudo_corrigido
            )
            
            if conteudo_corrigido != conteudo:
                with open(arquivo_path, 'w', encoding='utf-8') as f:
                    f.write(conteudo_corrigido)
                
                print(f"✅ {arquivo_nome}: Prints corrigidos")
            else:
                print(f"ℹ️ {arquivo_nome}: Nenhuma correção necessária")
        
        except Exception as e:
            print(f"❌ Erro ao corrigir {arquivo_nome}: {e}")

def main():
    """Função principal"""
    print("🔧 CORREÇÃO SIMPLES DE SINTAXE")
    print("="*50)
    
    corrigir_prints_malformados()
    
    print("\n🎉 Correções concluídas!")

if __name__ == "__main__":
    main()