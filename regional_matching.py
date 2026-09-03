"""Correspondencia segura entre nomes externos e codigos de regionais."""


def find_regional_code(regionals, target, normalize):
    """Prioriza igualdade completa antes de considerar nomes parcialmente iguais."""
    fields_by_code = {
        code: (
            normalize(code),
            normalize((data or {}).get("nome")),
            normalize((data or {}).get("descricao")),
        )
        for code, data in regionals.items()
    }

    # O codigo e a identidade da regional. Nomes e descricoes podem se repetir,
    # como ocorre com REG_MACAE e REG_GRSA_MACAE (ambas "Regional Macae").
    for field_index in range(3):
        for code, fields in fields_by_code.items():
            if target and target == fields[field_index]:
                return code

    for code, fields in fields_by_code.items():
        if any(target and (target in field or field in target) for field in fields if field):
            return code
    return None
