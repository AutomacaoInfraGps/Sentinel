"""Compatibilidade para inicializadores antigos do Sentinel.

A aplicação canônica e todos os controles de segurança vivem em web_config.py.
"""

from web_config import app


if __name__ == "__main__":
    from run_web_service import main

    main()
