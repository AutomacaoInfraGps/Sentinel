from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .contracts import MAX_EVENT_BATCH_SIZE
from .event_source import DEFAULT_OVERLAP_SIZE, MAX_OVERLAP_SIZE
from .rules import DEFAULT_FIXED_GROUPS


SUPPORTED_DELIVERY_CHANNELS = frozenset({"teams", "email"})


def _string(data: dict[str, Any], name: str, default: str) -> str:
    value = data.get(name, default)
    if not isinstance(value, str):
        raise ValueError(f"{name} deve ser texto")
    return value.strip()


def _integer(data: dict[str, Any], name: str, default: int) -> int:
    value = data.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} deve ser um número inteiro")
    return value


def _number(data: dict[str, Any], name: str, default: float) -> float:
    value = data.get(name, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} deve ser um número")
    return float(value)


def _optional_number(data: dict[str, Any], name: str) -> float | None:
    value = data.get(name)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} deve ser um número")
    return float(value)


def _optional_string(data: dict[str, Any], name: str) -> str | None:
    value = data.get(name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{name} deve ser texto ou null")
    stripped = value.strip()
    return stripped or None


@dataclass(frozen=True)
class DirectorySettings:
    enabled: bool = False
    backend: str = "POWERSHELL_ADWS"
    server: str | None = None
    query_timeout_seconds: float = 30.0
    cache_ttl_seconds: float = 300.0
    cache_max_entries: int = 2048

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise ValueError("directory.enabled deve ser booleano")
        if not isinstance(self.backend, str):
            raise ValueError("directory.backend deve ser texto")
        backend = self.backend.strip().upper()
        if backend != "POWERSHELL_ADWS":
            raise ValueError("directory.backend deve ser POWERSHELL_ADWS")
        object.__setattr__(self, "backend", backend)
        if self.server is not None:
            if not isinstance(self.server, str) or not self.server.strip():
                raise ValueError("directory.server deve ser texto não vazio ou null")
            server = self.server.strip()
            if "://" in server or any(character.isspace() for character in server):
                raise ValueError("directory.server deve conter somente o nome do servidor")
            object.__setattr__(self, "server", server)
        for name in (
            "query_timeout_seconds",
            "cache_ttl_seconds",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"directory.{name} deve ser um número")
            if not math.isfinite(float(value)) or float(value) <= 0:
                raise ValueError(f"directory.{name} deve ser finito e maior que zero")
            object.__setattr__(self, name, float(value))
        if isinstance(self.cache_max_entries, bool) or not isinstance(
            self.cache_max_entries, int
        ):
            raise ValueError("directory.cache_max_entries deve ser inteiro")
        if self.cache_max_entries < 1:
            raise ValueError("directory.cache_max_entries deve ser maior que zero")

    def validate_for_worker(self) -> None:
        if not self.enabled:
            raise ValueError("directory.enabled deve ser true para o worker produtivo")


@dataclass(frozen=True)
class RetentionPolicy:
    """Expurgo só pode ser ativado após configuração explícita dos limites."""

    events_and_deliveries_days: int | None = None
    occurrences_days: int | None = None
    operational_logs_days: int | None = None
    exceptional_raw_xml_days: int | None = None
    deduplication_guard_days: int | None = None
    purge_enabled: bool = False

    def __post_init__(self) -> None:
        for name in (
            "events_and_deliveries_days",
            "occurrences_days",
            "operational_logs_days",
            "exceptional_raw_xml_days",
            "deduplication_guard_days",
        ):
            value = getattr(self, name)
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value < 1
            ):
                raise ValueError(f"retention.{name} deve ser um inteiro positivo ou null")
        if not isinstance(self.purge_enabled, bool):
            raise ValueError("retention.purge_enabled deve ser booleano")
        if self.purge_enabled and any(
            value is None
            for value in (
                self.events_and_deliveries_days,
                self.occurrences_days,
                self.deduplication_guard_days,
            )
        ):
            raise ValueError(
                "Expurgo exige retenção de eventos, ocorrências e janela de deduplicação"
            )
        if self.purge_enabled:
            raise ValueError(
                "Expurgo permanece desabilitado até a janela real de replay ser "
                "comprovada no ambiente corporativo"
            )


@dataclass(frozen=True)
class Settings:
    fixed_groups: frozenset[str] = DEFAULT_FIXED_GROUPS
    group_name_prefix: str = "GGS_Suporte"
    timezone: str = "America/Sao_Paulo"
    max_delivery_attempts: int = 6
    delivery_channels: tuple[str, ...] = ("teams", "email")
    event_log_channel: str = "ForwardedEvents"
    event_batch_size: int = MAX_EVENT_BATCH_SIZE
    event_overlap_size: int = DEFAULT_OVERLAP_SIZE
    poll_interval_seconds: float | None = None
    directory: DirectorySettings = DirectorySettings()
    retention: RetentionPolicy = RetentionPolicy()

    def __post_init__(self) -> None:
        if not isinstance(self.fixed_groups, (set, frozenset)):
            raise ValueError("fixed_groups deve ser um conjunto de textos")
        fixed_groups = frozenset(
            name.strip() for name in self.fixed_groups if isinstance(name, str) and name.strip()
        )
        if not fixed_groups or len(fixed_groups) != len(self.fixed_groups):
            raise ValueError("fixed_groups deve conter somente nomes não vazios")
        object.__setattr__(self, "fixed_groups", fixed_groups)

        if not isinstance(self.group_name_prefix, str):
            raise ValueError("group_name_prefix deve ser texto")
        group_name_prefix = self.group_name_prefix.strip()
        if not group_name_prefix:
            raise ValueError("group_name_prefix não pode ser vazio")
        object.__setattr__(self, "group_name_prefix", group_name_prefix)

        if not isinstance(self.timezone, str):
            raise ValueError("timezone deve ser texto")
        timezone_name = self.timezone.strip()
        if not timezone_name:
            raise ValueError("timezone não pode ser vazio")
        object.__setattr__(self, "timezone", timezone_name)

        if isinstance(self.max_delivery_attempts, bool) or not isinstance(
            self.max_delivery_attempts, int
        ):
            raise ValueError("max_delivery_attempts deve ser um número inteiro")
        if self.max_delivery_attempts != 6:
            raise ValueError(
                "max_delivery_attempts deve ser 6: envio inicial e cinco retentativas"
            )

        if not isinstance(self.delivery_channels, tuple) or any(
            not isinstance(channel, str) for channel in self.delivery_channels
        ):
            raise ValueError("delivery_channels deve ser uma tupla de textos")
        delivery_channels = tuple(
            dict.fromkeys(channel.strip().casefold() for channel in self.delivery_channels)
        )
        if not delivery_channels or any(
            channel not in SUPPORTED_DELIVERY_CHANNELS for channel in delivery_channels
        ):
            raise ValueError("delivery_channels aceita somente 'teams' e 'email'")
        object.__setattr__(self, "delivery_channels", delivery_channels)

        if not isinstance(self.event_log_channel, str):
            raise ValueError("event_log_channel deve ser texto")
        event_log_channel = self.event_log_channel.strip()
        if not event_log_channel:
            raise ValueError("event_log_channel não pode ser vazio")
        object.__setattr__(self, "event_log_channel", event_log_channel)

        if isinstance(self.event_batch_size, bool) or not isinstance(self.event_batch_size, int):
            raise ValueError("event_batch_size deve ser um número inteiro")
        if not 1 <= self.event_batch_size <= MAX_EVENT_BATCH_SIZE:
            raise ValueError(
                f"event_batch_size deve estar entre 1 e {MAX_EVENT_BATCH_SIZE}"
            )

        if isinstance(self.event_overlap_size, bool) or not isinstance(
            self.event_overlap_size, int
        ):
            raise ValueError("event_overlap_size deve ser um número inteiro")
        if not 0 <= self.event_overlap_size <= MAX_OVERLAP_SIZE:
            raise ValueError(
                f"event_overlap_size deve estar entre 0 e {MAX_OVERLAP_SIZE}"
            )

        if self.poll_interval_seconds is not None:
            if isinstance(self.poll_interval_seconds, bool) or not isinstance(
                self.poll_interval_seconds, (int, float)
            ):
                raise ValueError("poll_interval_seconds deve ser um número")
            if not math.isfinite(float(self.poll_interval_seconds)):
                raise ValueError("poll_interval_seconds deve ser finito")
            if self.poll_interval_seconds <= 0:
                raise ValueError("poll_interval_seconds deve ser maior que zero")
            object.__setattr__(
                self,
                "poll_interval_seconds",
                float(self.poll_interval_seconds),
            )

        if not isinstance(self.retention, RetentionPolicy):
            raise ValueError("retention deve usar o contrato RetentionPolicy")
        if not isinstance(self.directory, DirectorySettings):
            raise ValueError("directory deve usar o contrato DirectorySettings")

    def validate_for_worker(self, *, require_directory: bool = True) -> None:
        """Valida opções exigidas somente pelo worker contínuo."""
        if self.poll_interval_seconds is None:
            raise ValueError(
                "poll_interval_seconds deve ser definido antes de iniciar o worker"
            )
        if require_directory:
            self.directory.validate_for_worker()

    @classmethod
    def load(cls, path: str | Path) -> "Settings":
        source = Path(path)
        try:
            data = json.loads(source.read_text(encoding="utf-8-sig"))
        except OSError as exc:
            raise ValueError(f"Não foi possível ler a configuração: {source}") from exc
        except json.JSONDecodeError as exc:
            raise ValueError(f"JSON de configuração inválido: {source}") from exc

        if not isinstance(data, dict):
            raise ValueError(f"A configuração deve ser um objeto JSON: {source}")

        raw_fixed_groups = data.get("fixed_groups", list(DEFAULT_FIXED_GROUPS))
        if not isinstance(raw_fixed_groups, list) or any(
            not isinstance(item, str) for item in raw_fixed_groups
        ):
            raise ValueError("fixed_groups deve ser uma lista de textos")

        raw_delivery_channels = data.get("delivery_channels", ["teams", "email"])
        if not isinstance(raw_delivery_channels, list) or any(
            not isinstance(item, str) for item in raw_delivery_channels
        ):
            raise ValueError("delivery_channels deve ser uma lista de textos")

        raw_retention = data.get("retention", {})
        if not isinstance(raw_retention, dict):
            raise ValueError("retention deve ser um objeto JSON")

        raw_directory = data.get("directory", {})
        if not isinstance(raw_directory, dict):
            raise ValueError("directory deve ser um objeto JSON")
        obsolete_directory_keys = {
            "host",
            "port",
            "base_dn",
            "authentication",
            "ca_cert_file",
            "connect_timeout_seconds",
            "receive_timeout_seconds",
        }.intersection(raw_directory)
        if obsolete_directory_keys:
            names = ", ".join(sorted(obsolete_directory_keys))
            raise ValueError(
                "Configuração LDAPS obsoleta em directory: "
                f"{names}; use backend POWERSHELL_ADWS"
            )

        return cls(
            fixed_groups=frozenset(item.strip() for item in raw_fixed_groups),
            group_name_prefix=_string(data, "group_name_prefix", "GGS_Suporte"),
            timezone=_string(data, "timezone", "America/Sao_Paulo"),
            max_delivery_attempts=_integer(data, "max_delivery_attempts", 6),
            delivery_channels=tuple(
                item.strip().casefold() for item in raw_delivery_channels
            ),
            event_log_channel=_string(
                data,
                "event_log_channel",
                "ForwardedEvents",
            ),
            event_batch_size=_integer(
                data,
                "event_batch_size",
                MAX_EVENT_BATCH_SIZE,
            ),
            event_overlap_size=_integer(
                data,
                "event_overlap_size",
                DEFAULT_OVERLAP_SIZE,
            ),
            poll_interval_seconds=_optional_number(data, "poll_interval_seconds"),
            directory=DirectorySettings(
                enabled=raw_directory.get("enabled", False),
                backend=_string(
                    raw_directory,
                    "backend",
                    "POWERSHELL_ADWS",
                ),
                server=_optional_string(raw_directory, "server"),
                query_timeout_seconds=_number(
                    raw_directory,
                    "query_timeout_seconds",
                    30,
                ),
                cache_ttl_seconds=_number(
                    raw_directory,
                    "cache_ttl_seconds",
                    300,
                ),
                cache_max_entries=_integer(
                    raw_directory,
                    "cache_max_entries",
                    2048,
                ),
            ),
            retention=RetentionPolicy(
                events_and_deliveries_days=raw_retention.get(
                    "events_and_deliveries_days"
                ),
                occurrences_days=raw_retention.get("occurrences_days"),
                operational_logs_days=raw_retention.get("operational_logs_days"),
                exceptional_raw_xml_days=raw_retention.get(
                    "exceptional_raw_xml_days"
                ),
                deduplication_guard_days=raw_retention.get(
                    "deduplication_guard_days"
                ),
                purge_enabled=raw_retention.get("purge_enabled", False),
            ),
        )

