from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable

from .formatting import format_alert
from .models import ADGroupEvent
from .parsing import parse_windows_event
from .persistence import EventStore
from .rules import GroupMatcher


class ProcessStatus(StrEnum):
    READY = "ready"
    OUT_OF_SCOPE = "out_of_scope"
    DUPLICATE = "duplicate"


@dataclass(frozen=True)
class ProcessResult:
    status: ProcessStatus
    event: ADGroupEvent
    message: str | None = None


class EventProcessor:
    def __init__(
        self,
        *,
        matcher: GroupMatcher | None = None,
        store: EventStore | None = None,
        channels: Iterable[str] = ("teams", "email"),
    ) -> None:
        self.matcher = matcher or GroupMatcher()
        self.store = store
        self.channels = tuple(channels)

    def process_xml(self, xml_text: str) -> ProcessResult:
        event = parse_windows_event(xml_text)
        if not self.matcher.matches(event):
            return ProcessResult(ProcessStatus.OUT_OF_SCOPE, event)

        # A mensagem precisa existir antes da persistência. Assim, um erro de
        # formatação nunca deixa entregas pendentes sem snapshot recuperável.
        message = format_alert(event)
        if self.store is not None and not self.store.add_event(
            event,
            self.channels,
            message=message,
        ):
            return ProcessResult(ProcessStatus.DUPLICATE, event)

        return ProcessResult(ProcessStatus.READY, event, message)
