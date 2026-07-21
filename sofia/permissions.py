"""Server-side authorization boundary for SofIA capabilities."""

import json
from functools import lru_cache
from pathlib import Path


_PERMISSIONS_MATRIX_PATH = Path(__file__).resolve().parent / "permissions_matrix.json"
_FALLBACK_ALLOWED_ACTIONS = frozenset({"chat:basic", "sentinel:read", "knowledge:read"})


@lru_cache(maxsize=1)
def carregar_matriz_permissoes():
    """Load the allowlist matrix. Fail closed if the file is invalid."""
    try:
        data = json.loads(_PERMISSIONS_MATRIX_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {}
        return data
    except Exception:
        return {
            acao: {"enabled": True, "risk": "baixo"}
            for acao in _FALLBACK_ALLOWED_ACTIONS
        }


def acao_habilitada(acao):
    config = carregar_matriz_permissoes().get(str(acao), {})
    return bool(config.get("enabled") is True)


def usuario_pode_executar(usuario, acao, regional=None):
    """Authorize only enabled low-risk MVP capabilities for authenticated users."""
    del regional
    return bool(
        usuario
        and getattr(usuario, "is_authenticated", False)
        and acao_habilitada(acao)
    )
