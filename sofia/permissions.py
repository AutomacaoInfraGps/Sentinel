"""Server-side authorization boundary for SofIA capabilities."""

MVP_ALLOWED_ACTIONS = frozenset({"chat:basic", "sentinel:read"})


def usuario_pode_executar(usuario, acao, regional=None):
    """Authorize only the non-privileged MVP chat capability."""
    del regional
    return bool(
        usuario
        and getattr(usuario, "is_authenticated", False)
        and acao in MVP_ALLOWED_ACTIONS
    )
