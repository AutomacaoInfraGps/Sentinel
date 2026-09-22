"""Compatibilidade para importações antigas da autenticação AD.

Este módulo carrega exclusivamente a implementação canônica da raiz do projeto.
"""

import importlib.util
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

spec = importlib.util.spec_from_file_location(
    "sentinel_canonical_auth_ad",
    PROJECT_ROOT / "auth_ad.py",
)
if spec is None or spec.loader is None:
    raise ImportError("Não foi possível carregar a autenticação canônica do Sentinel")

_canonical = importlib.util.module_from_spec(spec)
spec.loader.exec_module(_canonical)

AuthAD = _canonical.AuthAD
auth_ad = _canonical.auth_ad
verificar_usuario_ad = _canonical.verificar_usuario_ad
testar_conexao_ad = _canonical.testar_conexao_ad
init_auth = _canonical.init_auth
get_user = _canonical.get_user

__all__ = [
    "AuthAD",
    "auth_ad",
    "verificar_usuario_ad",
    "testar_conexao_ad",
    "init_auth",
    "get_user",
]
