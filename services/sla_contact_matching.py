"""SLA-only regional identity rules; never resolve contacts by a person's name."""

from unifi_site_matching import normalize_unifi_site


# Confirmed against the Rigel firewall catalog, not geographic descriptions.
VERIFIED_ALIASES = {
    'V024_REGIONAL_CEARA2': ('REG_CEARA_2', 'REPORT DE SEGURANCA-FGT_REGCEARA02ULTRA'),
    'V028_REGIONAL_CAMPINAS_BASE_2': ('REG_CAMPINAS_02', 'REPORT DE SEGURANCA-FGT_REGCAMPINAS02'),
    'V041_REGIONAL_CAXIAS_DO_SUL': ('REG_CAXIAS', 'REPORT DE SEGURANCA-FTG_REGCAXIAS'),
    'V049_REGIONAL_MACAE01': ('REG_MACAE', 'REPORT DE SEGURANCA-FTG_REGMACAE01'),
}


def resolve_sla_contact_regional(regionals, regional_label, fortianalyzer_label):
    """Return (code, reason, candidates), preserving unknown and ambiguous cases."""
    label = regional_label.strip() if isinstance(regional_label, str) else ''
    forti = fortianalyzer_label.strip() if isinstance(fortianalyzer_label, str) else ''
    alias = VERIFIED_ALIASES.get(label.upper())
    if alias:
        code, expected_report = alias
        if forti.casefold() != expected_report.casefold():
            return None, 'rotulo_fortianalyzer_divergente_do_alias', ()
        if code not in regionals:
            return None, 'destino_alias_ausente', ()
        return code, 'alias_sla_verificado', (code,)
    identity = normalize_unifi_site(label)
    if not identity:
        return None, 'nao_encontrado', ()
    candidates = set()
    for code, entry in regionals.items():
        for value in (code, entry.get('nome')):
            if isinstance(value, str) and value.strip() and normalize_unifi_site(value) == identity:
                candidates.add(code)
    candidates = tuple(sorted(candidates))
    if len(candidates) == 1:
        return candidates[0], 'identidade_normalizada_unica', candidates
    return None, 'ambiguo' if candidates else 'nao_encontrado', candidates
