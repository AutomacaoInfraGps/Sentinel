"""Adapter somente leitura entre o AlertAD e o sino do Sentinel."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python 3.11 possui zoneinfo
    ZoneInfo = None  # type: ignore[assignment]

from services.alertad_v1.src.alertad.sentinel_read import SentinelAlertReader


_TRUE_VALUES = frozenset({"1", "true", "yes", "on", "sim"})
_FALSE_VALUES = frozenset({"0", "false", "no", "off", "nao", "não", ""})


def _brasilia_timezone():
    if ZoneInfo is not None:
        try:
            return ZoneInfo("America/Sao_Paulo")
        except Exception:
            pass
    return timezone(timedelta(hours=-3), name="BRT")


def _display_datetime(value: object) -> str:
    raw_value = str(value or "").strip()
    try:
        parsed = datetime.fromisoformat(raw_value.replace("Z", "+00:00"))
    except ValueError:
        return raw_value or "Não informado"
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    local_time = parsed.astimezone(_brasilia_timezone())
    return f"{local_time:%d/%m/%Y %H:%M:%S} (Brasília)"


def _common_name(value: object) -> str:
    """Reduz um DN LDAP ao CN inicial sem expor sua hierarquia."""
    raw_value = str(value or "").strip()
    if not raw_value.casefold().startswith("cn="):
        return raw_value or "Não informado"

    common_name: list[str] = []
    escaped = False
    for character in raw_value[3:]:
        if escaped:
            common_name.append(character)
            escaped = False
        elif character == "\\":
            escaped = True
        elif character == ",":
            break
        else:
            common_name.append(character)
    if escaped:
        common_name.append("\\")
    return "".join(common_name).strip() or "Não informado"


def _boolean(value: object, *, name: str) -> bool:
    if isinstance(value, bool):
        return value
    normalized = str(value or "").strip().casefold()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    raise ValueError(f"{name} deve ser booleano")


def _integer(value: object, *, name: str, default: int) -> int:
    if value in (None, ""):
        return default
    if isinstance(value, bool):
        raise ValueError(f"{name} deve ser inteiro")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} deve ser inteiro") from exc
    if not 1 <= result <= 500:
        raise ValueError(f"{name} deve estar entre 1 e 500")
    return result


@dataclass(frozen=True)
class AlertADNotificationSettings:
    enabled: bool = False
    database_path: Path | None = None
    recent_limit: int = 100

    @classmethod
    def from_external_config(
        cls,
        environment_config: Mapping[str, object] | None,
        *,
        environ: Mapping[str, str] | None = None,
    ) -> "AlertADNotificationSettings":
        config = environment_config if isinstance(environment_config, Mapping) else {}
        raw_section = config.get("alertad", {})
        section = raw_section if isinstance(raw_section, Mapping) else {}
        external = environ if environ is not None else os.environ

        enabled_value = external.get(
            "SENTINEL_ALERTAD_ENABLED",
            section.get("enabled", False),
        )
        enabled = _boolean(enabled_value, name="alertad.enabled")
        path_value = external.get(
            "SENTINEL_ALERTAD_SQLITE_PATH",
            section.get("sqlite_path"),
        )
        limit_value = external.get(
            "SENTINEL_ALERTAD_RECENT_LIMIT",
            section.get("recent_limit", 100),
        )
        recent_limit = _integer(
            limit_value,
            name="alertad.recent_limit",
            default=100,
        )

        database_path = None
        if path_value not in (None, ""):
            database_path = Path(str(path_value).strip()).expanduser()
            if not database_path.is_absolute():
                raise ValueError("alertad.sqlite_path deve ser absoluto")
        if enabled and database_path is None:
            raise ValueError("alertad.sqlite_path é obrigatório quando habilitado")
        return cls(enabled, database_path, recent_limit)


def _notification(alert) -> dict[str, object]:
    """Seleciona explicitamente apenas campos aprovados para a API web."""
    message = "\n".join(
        (
            f"Grupo: {alert.group_name}",
            f"Usuário: {_common_name(alert.member_label)}",
            f"Executor: {alert.actor_label}",
            f"Origem: {alert.source_computer}",
            f"Data/hora: {_display_datetime(alert.occurred_at_utc)}",
        )
    )
    return {
        "id": alert.notification_id,
        "type": "alertad",
        "severity": "critical",
        "icon": "bi-shield-lock-fill",
        "title": alert.title,
        "message": message,
        "regional": "Active Directory",
        "device": alert.group_name,
        "persistent": False,
        "occurred_at": alert.occurred_at_utc,
        "url": "#",
    }


def load_alertad_notifications(
    environment_config: Mapping[str, object] | None,
    *,
    authorized: bool,
    logger=None,
    reader_factory=SentinelAlertReader,
    environ: Mapping[str, str] | None = None,
) -> list[dict[str, object]]:
    """Carrega alertas sem expor estado, erro ou metadado a não operadores."""
    if not authorized:
        return []

    try:
        settings = AlertADNotificationSettings.from_external_config(
            environment_config,
            environ=environ,
        )
        if not settings.enabled:
            return []
        reader = reader_factory(settings.database_path)
        return [
            _notification(alert)
            for alert in reader.list_recent(limit=settings.recent_limit)
        ]
    except Exception as exc:
        if logger is not None:
            logger.warning(
                "AlertAD indisponivel para o sino; reason=%s",
                type(exc).__name__,
            )
        return []
