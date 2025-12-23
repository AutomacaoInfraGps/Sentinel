"""
Módulo de backup do sistema
"""

import os
import shutil
import zipfile
from pathlib import Path
from datetime import datetime

def criar_backup_completo():
    """Cria backup completo do sistema"""
    try:
        project_root = Path(__file__).parent
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"backup_sistema_{timestamp}.zip"
        backup_path = project_root / backup_name
        
        with zipfile.ZipFile(backup_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            # Adiciona arquivos importantes
            for arquivo in ["*.py", "*.json", "*.txt", "*.md"]:
                for file_path in project_root.glob(arquivo):
                    if not file_path.name.startswith('backup_'):
                        zipf.write(file_path, file_path.name)
        
        return str(backup_path)
    
    except Exception as e:
        print(f"Erro ao criar backup: {e}")
        return None
