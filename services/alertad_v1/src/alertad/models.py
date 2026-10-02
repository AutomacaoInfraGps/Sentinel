from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum


class Action(StrEnum):
    ADD = "add"
    REMOVE = "remove"


class GroupScope(StrEnum):
    GLOBAL = "global"
    LOCAL = "local"
    UNIVERSAL = "universal"


@dataclass(frozen=True)
class EventDefinition:
    action: Action
    group_scope: GroupScope


EVENT_DEFINITIONS: dict[int, EventDefinition] = {
    4728: EventDefinition(Action.ADD, GroupScope.GLOBAL),
    4729: EventDefinition(Action.REMOVE, GroupScope.GLOBAL),
    4732: EventDefinition(Action.ADD, GroupScope.LOCAL),
    4733: EventDefinition(Action.REMOVE, GroupScope.LOCAL),
    4756: EventDefinition(Action.ADD, GroupScope.UNIVERSAL),
    4757: EventDefinition(Action.REMOVE, GroupScope.UNIVERSAL),
}


@dataclass(frozen=True)
class ADGroupEvent:
    event_id: int
    action: Action
    group_scope: GroupScope
    time_created_utc: datetime
    event_record_id: int
    channel: str
    source_computer: str
    member_name: str | None
    member_sid: str
    target_user_name: str
    target_domain_name: str | None
    target_sid: str | None
    subject_user_sid: str | None
    subject_user_name: str | None
    subject_domain_name: str | None
    subject_logon_id: str | None
    raw_xml: str
    time_created_raw: str | None = None

    def __post_init__(self) -> None:
        if self.time_created_utc.tzinfo is None:
            raise ValueError("time_created_utc deve possuir fuso horário")

    @property
    def event_key(self) -> str:
        timestamp = (
            self.time_created_raw.strip()
            if self.time_created_raw and self.time_created_raw.strip()
            else self.time_created_utc.astimezone(timezone.utc).isoformat()
        )
        parts = (
            "v2",
            self.source_computer.casefold(),
            self.channel.casefold(),
            str(self.event_record_id),
            str(self.event_id),
            timestamp,
        )
        return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()

    @property
    def legacy_event_key(self) -> str:
        timestamp = self.time_created_utc.astimezone(timezone.utc).isoformat(
            timespec="microseconds"
        )
        parts = (
            self.source_computer.casefold(),
            self.channel.casefold(),
            str(self.event_record_id),
            str(self.event_id),
            timestamp,
        )
        return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()

    @property
    def executor(self) -> str | None:
        if self.subject_user_name and self.subject_domain_name:
            return f"{self.subject_domain_name}\\{self.subject_user_name}"
        return self.subject_user_name or self.subject_user_sid

    @property
    def member(self) -> str:
        return self.member_name or self.member_sid

