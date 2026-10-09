"""Build the SofIA alert snapshot from the same aggregate used by the map."""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from config import PROJECT_ROOT


MAP_ALERT_CACHE = PROJECT_ROOT / "output" / "mapa_monitoramento_cache.json"
BRASILIA_TZ = ZoneInfo("America/Sao_Paulo")
SEVERITY_MAP = {
    "critico": "critical",
    "alto": "high",
    "medio": "medium",
    "atencao": "attention",
}


def _parse_datetime(value):
    try:
        parsed = datetime.fromisoformat(str(value or "").strip().replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=BRASILIA_TZ)
    return parsed


def _brasilia_iso(value):
    parsed = _parse_datetime(value)
    return parsed.astimezone(BRASILIA_TZ).isoformat() if parsed else None


def _alert_id(regional, alert):
    raw = "|".join(
        (
            str(regional or ""),
            str(alert.get("tipo") or ""),
            str(alert.get("severidade") or ""),
            str(alert.get("descricao") or ""),
        )
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def load_map_alert_snapshot(path=None, now=None):
    """Load aggregate alert buckets without exposing the map's device payload."""
    cache_path = Path(path or MAP_ALERT_CACHE)
    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    updated_at = payload.get("cache_atualizado_em") or (payload.get("fontes") or {}).get("atualizado_em")
    updated = _parse_datetime(updated_at)
    reference = now or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    ttl_seconds = max(1, int(payload.get("cache_ttl_segundos") or 300))
    age_seconds = None
    if updated:
        age_seconds = max(0, int((reference.astimezone(timezone.utc) - updated.astimezone(timezone.utc)).total_seconds()))

    alerts = []
    counts = {severity: 0 for severity in SEVERITY_MAP.values()}
    for regional in payload.get("regionais") or []:
        regional_code = str(regional.get("codigo") or regional.get("nome") or "Sem regional").strip()
        # This is the map snapshot time, not the time when a device last changed.
        occurred_at = _brasilia_iso(updated_at)
        for alert in regional.get("alertas") or []:
            severity = SEVERITY_MAP.get(str(alert.get("severidade") or "").strip().lower())
            try:
                quantity = int(alert.get("quantidade") or 0)
            except (TypeError, ValueError):
                continue
            if not severity or quantity < 1:
                continue
            description = str(alert.get("descricao") or alert.get("tipo") or "Alerta operacional").strip()
            counts[severity] += quantity
            alerts.append(
                {
                    "id": _alert_id(regional_code, alert),
                    "type": str(alert.get("tipo") or "operational").strip(),
                    "severity": severity,
                    "title": description[:1].upper() + description[1:],
                    "message": f"{quantity} ocorrencia(s) no mapa: {description}.",
                    "regional": regional_code,
                    "device": None,
                    "quantity": quantity,
                    "persistent": False,
                    "occurred_at": occurred_at,
                }
            )

    severity_order = {"critical": 0, "high": 1, "medium": 2, "attention": 3}
    alerts.sort(key=lambda item: (severity_order[item["severity"]], item["regional"], item["title"]))
    total = sum(counts.values())
    return {
        "updated_at": updated_at,
        "updated_at_brasilia": _brasilia_iso(updated_at),
        "fresh": age_seconds is not None and age_seconds <= ttl_seconds,
        "age_seconds": age_seconds,
        "ttl_seconds": ttl_seconds,
        "summary": {**counts, "total": total},
        "alerts": alerts,
    }
