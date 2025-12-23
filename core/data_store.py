#!/usr/bin/env python3
"""
Sistema de Armazenamento de Dados Centralizado
Armazena dados em formato JSON para fácil acesso pela interface web
"""

import json
import os
from datetime import datetime
from pathlib import Path

# Importa configurações
from config import PROJECT_ROOT

# Diretório de dados
DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)

def save_data(component, data):
    """
    Salva dados de um componente em formato JSON
    
    Args:
        component (str): Nome do componente (ex: 'unifi', 'replicacao', 'servidores')
        data (dict): Dados a serem salvos
    """
    # Adiciona timestamp
    data['timestamp'] = datetime.now().isoformat()
    
    # Salva em arquivo JSON
    file_path = DATA_DIR / f"{component}.json"
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    return True

def load_data(component):
    """
    Carrega dados de um componente
    
    Args:
        component (str): Nome do componente (ex: 'unifi', 'replicacao', 'servidores')
    
    Returns:
        dict: Dados do componente ou None se não existir
    """
    file_path = DATA_DIR / f"{component}.json"
    
    if not file_path.exists():
        return None
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data
    except Exception as e:
        print(f"Erro ao carregar dados de {component}: {e}")
        return None

def get_data_timestamp(component):
    """
    Retorna o timestamp da última atualização dos dados
    
    Args:
        component (str): Nome do componente
    
    Returns:
        datetime: Timestamp da última atualização ou None
    """
    data = load_data(component)
    
    if data and 'timestamp' in data:
        try:
            return datetime.fromisoformat(data['timestamp'])
        except:
            pass
    
    return None

def is_data_fresh(component, max_age_seconds=300):
    """
    Verifica se os dados estão atualizados
    
    Args:
        component (str): Nome do componente
        max_age_seconds (int): Idade máxima em segundos
    
    Returns:
        bool: True se os dados estiverem atualizados
    """
    timestamp = get_data_timestamp(component)
    
    if not timestamp:
        return False
    
    age = (datetime.now() - timestamp).total_seconds()
    return age <= max_age_seconds