"""Correspondencia segura entre nomes externos e codigos de regionais."""


def find_regional_code(regionals, target, normalize):
    """Relaciona uma origem externa pela identidade, nunca pela descricao."""
    def identity(value):
        normalized = normalize(value)
        tokens = [
            token for token in normalized.replace("-", "_").split("_")
            if token and token not in {"REG", "REGIONAL", "REGIAO"}
        ]
        return "_".join(tokens)

    target_identity = identity(target)
    if not target_identity:
        return None

    fields_by_code = {
        code: (
            identity(code),
            identity((data or {}).get("nome")),
        )
        for code, data in regionals.items()
    }

    # O codigo e a identidade da regional. Descricoes como estado ou area podem
    # se repetir e nao participam do vinculo operacional.
    for field_index in range(2):
        for code, fields in fields_by_code.items():
            if target_identity == fields[field_index]:
                return code

    partial_matches = [
        code
        for code, fields in fields_by_code.items()
        if any(
            len(target_identity) >= 5
            and field
            and (target_identity in field or field in target_identity)
            for field in fields
        )
    ]
    if len(partial_matches) == 1:
        return partial_matches[0]
    return None
