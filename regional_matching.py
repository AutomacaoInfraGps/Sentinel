"""Correspondencia segura entre nomes externos e codigos de regionais."""


def find_regional_code(regionals, target, normalize):
    """Prioriza igualdade completa antes de considerar nomes parcialmente iguais."""
    candidates_by_code = {
        code: {
            normalize(code),
            normalize((data or {}).get("nome")),
            normalize((data or {}).get("descricao")),
        }
        for code, data in regionals.items()
    }

    for code, candidates in candidates_by_code.items():
        if target in candidates:
            return code

    for code, candidates in candidates_by_code.items():
        if any(target and (target in candidate or candidate in target) for candidate in candidates if candidate):
            return code
    return None
