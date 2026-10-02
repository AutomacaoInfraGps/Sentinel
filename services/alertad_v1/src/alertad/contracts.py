from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from .models import ADGroupEvent


MAX_EVENT_BATCH_SIZE = 500


@dataclass(frozen=True)
class EventCheckpoint:
    """Posição confirmável; sequence é ordem lógica da fonte, não EventRecordID."""

    source: str
    value: str
    generation: str = "legacy"
    sequence: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.source, str) or not self.source.strip():
            raise ValueError("source do checkpoint não pode ser vazio")
        if not isinstance(self.value, str) or not self.value.strip():
            raise ValueError("value do checkpoint não pode ser vazio")
        if not isinstance(self.generation, str) or not self.generation.strip():
            raise ValueError("generation do checkpoint não pode ser vazia")
        if isinstance(self.sequence, bool) or not isinstance(self.sequence, int):
            raise ValueError("sequence do checkpoint deve ser um número inteiro")
        if self.sequence < 0:
            raise ValueError("sequence do checkpoint não pode ser negativa")
        object.__setattr__(self, "source", self.source.strip().casefold())
        object.__setattr__(self, "generation", self.generation.strip())


@dataclass(frozen=True)
class CheckpointAdvance:
    """Transição contígua e otimista entre dois checkpoints."""

    expected: EventCheckpoint | None
    next: EventCheckpoint
    allow_generation_change: bool = False

    def __post_init__(self) -> None:
        if self.expected is None:
            if self.allow_generation_change:
                raise ValueError(
                    "allow_generation_change exige um checkpoint esperado"
                )
            return
        if self.expected.source != self.next.source:
            raise ValueError("A transição de checkpoint deve manter a mesma fonte")
        if self.expected.generation != self.next.generation:
            if not self.allow_generation_change:
                raise ValueError("Mudança de geração exige confirmação explícita")
            return
        if self.allow_generation_change:
            raise ValueError("allow_generation_change só é válido entre gerações")
        if self.next.sequence != self.expected.sequence + 1:
            raise ValueError(
                "A transição deve avançar exatamente uma sequência contígua"
            )


@dataclass(frozen=True)
class CollectedEvent:
    """XML coletado e posição confirmável imediatamente após esse item."""

    xml: str
    checkpoint: EventCheckpoint

    def __post_init__(self) -> None:
        if not self.xml.strip():
            raise ValueError("xml do evento coletado não pode ser vazio")


@dataclass(frozen=True)
class EventBatch:
    events: tuple[CollectedEvent, ...]
    next_checkpoint: EventCheckpoint | None
    has_more: bool = False

    def __post_init__(self) -> None:
        if len(self.events) > MAX_EVENT_BATCH_SIZE:
            raise ValueError(
                f"O lote não pode exceder {MAX_EVENT_BATCH_SIZE} eventos"
            )
        if self.events and self.next_checkpoint is None:
            raise ValueError("Lote com eventos deve informar next_checkpoint")
        if self.has_more and not self.events:
            raise ValueError("Lote vazio não pode indicar has_more")


@dataclass(frozen=True)
class DeliveryResult:
    success: bool
    retryable: bool = False
    error: str | None = None
    retry_after_seconds: float | None = None
    failure_kind: str | None = None

    def __post_init__(self) -> None:
        if self.success and (
            self.retryable
            or self.error is not None
            or self.retry_after_seconds is not None
            or self.failure_kind is not None
        ):
            raise ValueError("Entrega concluída não pode conter estado de falha")
        if self.retry_after_seconds is not None and self.retry_after_seconds < 0:
            raise ValueError("retry_after_seconds não pode ser negativo")


class EventSource(Protocol):
    def read_new_events(
        self,
        checkpoint: EventCheckpoint | None,
        *,
        limit: int,
    ) -> EventBatch: ...


@dataclass(frozen=True)
class DirectoryObject:
    sid: str
    account_name: str
    object_type: str
    domain_name: str | None = None
    display_name: str | None = None


class DirectoryResolutionStatus(StrEnum):
    RESOLVED = "resolved"
    NOT_FOUND = "not_found"
    TEMPORARY_FAILURE = "temporary_failure"
    PERMANENT_FAILURE = "permanent_failure"


@dataclass(frozen=True)
class DirectoryResolution:
    status: DirectoryResolutionStatus
    directory_object: DirectoryObject | None = None
    error_code: str | None = None

    def __post_init__(self) -> None:
        if self.status is DirectoryResolutionStatus.RESOLVED:
            if self.directory_object is None:
                raise ValueError("Resolução concluída deve informar directory_object")
        elif self.directory_object is not None:
            raise ValueError("Resolução não concluída não pode informar directory_object")


class DirectoryResolver(Protocol):
    def resolve_sid(self, sid: str) -> DirectoryResolution: ...


class OccurrenceCategory(StrEnum):
    INVALID_EVENT = "invalid_event"
    PERMANENT_DELIVERY_ERROR = "permanent_delivery_error"


@dataclass(frozen=True)
class OperationalOccurrence:
    category: OccurrenceCategory
    component: str
    reason_code: str
    fingerprint: str
    occurred_at_utc: datetime
    source: str | None = None

    def __post_init__(self) -> None:
        if not self.component.strip():
            raise ValueError("component da ocorrência não pode ser vazio")
        if not self.reason_code.strip():
            raise ValueError("reason_code da ocorrência não pode ser vazio")
        if not self.fingerprint.strip():
            raise ValueError("fingerprint da ocorrência não pode ser vazio")
        if self.occurred_at_utc.tzinfo is None:
            raise ValueError("occurred_at_utc deve possuir fuso horário")


class OccurrenceStore(Protocol):
    def record_occurrence(self, occurrence: OperationalOccurrence) -> bool: ...


class Notifier(Protocol):
    channel: str

    def send(self, event: ADGroupEvent, message: str) -> DeliveryResult: ...
