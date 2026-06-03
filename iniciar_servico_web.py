#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Service runner for Automacao Web - uses global Python, no venv"""

import sys
import os
from pathlib import Path
from datetime import datetime


def resolve_web_port():
    raw_port = str(os.environ.get("AUTOMACAO_WEB_PORT") or "5000").strip()
    try:
        port = int(raw_port)
    except (TypeError, ValueError):
        return 5000
    return port if 1 <= port <= 65535 else 5000

# Ensure we're in the right directory
PROJECT_DIR = Path(__file__).resolve().parent
os.chdir(PROJECT_DIR)
sys.path.insert(0, str(PROJECT_DIR))

def main():
    try:
        port = resolve_web_port()
        # Import Flask app
        from web_config import app
        
        # Try waitress first, fall back to Flask dev server
        try:
            from waitress import serve
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Iniciando com Waitress...", flush=True)
            serve(app, listen=f"0.0.0.0:{port}", threads=8)
        except ImportError:
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Waitress não encontrado, usando Flask dev server...", flush=True)
            app.run(host="0.0.0.0", port=port, debug=False)
            
    except Exception as e:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ERRO: {e}", flush=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
