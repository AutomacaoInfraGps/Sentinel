#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Service runner for Automacao Web - uses global Python, no venv"""

import sys
import os
from pathlib import Path
from datetime import datetime

# Ensure we're in the right directory
os.chdir(r'C:\Automacao')
sys.path.insert(0, r'C:\Automacao')

def main():
    try:
        # Import Flask app
        from web_config import app
        
        # Try waitress first, fall back to Flask dev server
        try:
            from waitress import serve
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Iniciando com Waitress...", flush=True)
            serve(app, listen="0.0.0.0:5000", threads=8)
        except ImportError:
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Waitress não encontrado, usando Flask dev server...", flush=True)
            app.run(host="0.0.0.0", port=5000, debug=False)
            
    except Exception as e:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ERRO: {e}", flush=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
