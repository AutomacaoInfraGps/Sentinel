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
    
    print(f"Tentando carregar dados de: {file_path}")
    
    if not file_path.exists():
        print(f"Arquivo não encontrado: {file_path}")
        return None
    
    # Tenta diferentes codificações para lidar com possíveis BOM
    encodings = ['utf-8', 'utf-8-sig', 'latin1']
    
    for encoding in encodings:
        try:
            print(f"Tentando carregar com codificação: {encoding}")
            with open(file_path, 'r', encoding=encoding) as f:
                data = json.load(f)
            print(f"Dados carregados com sucesso usando {encoding}: {len(str(data))} bytes")
            return data
        except UnicodeDecodeError:
            print(f"Erro de decodificação com {encoding}, tentando próxima codificação...")
            continue
        except json.JSONDecodeError as e:
            print(f"Erro de formato JSON com {encoding}: {e}")
            continue
        except Exception as e:
            print(f"Erro desconhecido ao carregar dados de {component} com {encoding}: {e}")
            continue
    
    print(f"Falha ao carregar dados de {component} com todas as codificações tentadas")
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
            # Tenta diferentes formatos de timestamp
            timestamp_str = data['timestamp']
            
            try:
                # Tenta formato com timezone
                timestamp = datetime.fromisoformat(timestamp_str)
                # Se tem timezone, converte para UTC e remove timezone
                if timestamp.tzinfo is not None:
                    print(f"Convertendo timestamp com timezone: {timestamp}")
                    timestamp = timestamp.astimezone().replace(tzinfo=None)
                    print(f"Timestamp convertido: {timestamp}")
                return timestamp
            except ValueError as e:
                print(f"Erro ao converter timestamp com timezone: {e}")
                # Tenta formato sem timezone
                return datetime.fromisoformat(timestamp_str)
        except Exception as e:
            print(f"Erro ao processar timestamp: {e}")
    
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