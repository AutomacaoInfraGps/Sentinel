"""Shared license alert boundaries, independent of firewall availability."""

from datetime import date, datetime
import math


UNAVAILABLE = {'offline', 'unavailable', 'indisponivel', 'timeout', 'erro_consulta', 'unknown', 'sem sinal'}


def _known_expiry(value):
    if isinstance(value, bool) or value is None:
        return False
    try:
        numeric = float(value)
    except (ValueError, TypeError):
        try:
            text = str(value).strip()
            if len(text) == 10:
                try:
                    date.fromisoformat(text)
                except ValueError:
                    datetime.strptime(text, '%d/%m/%Y')
            else:
                datetime.fromisoformat(text.replace('Z', '+00:00'))
            return True
        except ValueError:
            return False
    if not math.isfinite(numeric) or numeric <= 0:
        return False
    try:
        datetime.fromtimestamp(numeric)
        return True
    except (ValueError, OverflowError, OSError):
        return False


def license_alert_flags(license, threshold=60):
    unavailable = (license.get('status_indisponivel') is True
                   or str(license.get('status') or '').strip().lower() in UNAVAILABLE)
    days = license.get('dias_restantes')
    numeric_days = not unavailable and type(days) in (int, float) and math.isfinite(days)
    known = numeric_days and _known_expiry(license.get('expiracao'))
    expired = not unavailable and (bool(license.get('notificacao_expirada'))
                                   or str(license.get('status') or '').lower() in {'expired', 'no_license'}
                                   or (known and days < 0))
    # Preserve existing positive-day alerts; zero requires a real expiry, not a fallback.
    expiring = numeric_days and not expired and (0 < days <= threshold or (known and days == 0))
    return {'status_indisponivel': unavailable,
            'prazo_conhecido': bool(known or (numeric_days and days > 0)),
            'notificacao_expirada': bool(expired), 'notificacao_critica': bool(expiring),
            'alerta_vencimento': bool(expiring),
            'vencimento_critico': bool(expired or (known and days == 0))}
