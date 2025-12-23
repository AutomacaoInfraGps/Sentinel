"""
Script auxiliar para fornecer o caminho dinâmico do arquivo de replicação
para o script PowerShell.
"""

import sys
import os
from config import REPLICACAO_HTML

if __name__ == "__main__":
    # Converte para caminho Windows padrão
    path_str = str(REPLICACAO_HTML).replace('/', '\\')
    
    # Garante que o diretório existe
    os.makedirs(os.path.dirname(path_str), exist_ok=True)
    
    print(path_str)