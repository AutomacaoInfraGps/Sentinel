#!/usr/bin/env python3
"""
Utilitários para caminhos de arquivos
Resolve problemas de caminhos quando executando como executável compilado
"""

import sys
import os
from pathlib import Path

def get_base_dir():
    """
    Retorna o diretório base do projeto, considerando se está rodando como executável
    """
    # Se estiver rodando como executável (cx_Freeze)
    if getattr(sys, 'frozen', False):
        # Quando compilado, sys.executable aponta para o .exe
        return Path(sys.executable).parent.absolute()
    else:
        # Quando rodando como script Python normal
        # Usa o diretório do arquivo que está chamando esta função
        frame = sys._getframe(1)
        caller_file = frame.f_globals.get('__file__')
        if caller_file:
            return Path(caller_file).parent.absolute()
        else:
            # Fallback para o diretório atual
            return Path.cwd()

def get_file_path(relative_path):
    """
    Retorna o caminho completo para um arquivo relativo ao diretório base
    """
    return get_base_dir() / relative_path

def get_environment_file():
    """
    Retorna o caminho para o arquivo environment.json
    """
    return get_file_path("environment.json")

def get_credentials_dir():
    """
    Retorna o diretório de credenciais
    """
    return get_file_path(".credentials")