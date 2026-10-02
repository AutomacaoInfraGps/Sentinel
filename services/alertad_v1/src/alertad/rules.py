from __future__ import annotations

from dataclasses import dataclass, field

from .models import ADGroupEvent


DEFAULT_FIXED_GROUPS = frozenset(
    {
        "Domain Admins",
        "Administrators",
        "Backup Operators",
        "Enterprise Admins",
        "Schema Admins",
    }
)


@dataclass(frozen=True)
class GroupMatcher:
    fixed_groups: frozenset[str] = field(default_factory=lambda: DEFAULT_FIXED_GROUPS)
    name_prefix: str = "GGS_Suporte"

    def __post_init__(self) -> None:
        if not self.name_prefix.strip():
            raise ValueError("name_prefix não pode ser vazio")

    def matches_name(self, group_name: str) -> bool:
        normalized = group_name.strip().casefold()
        fixed = {name.strip().casefold() for name in self.fixed_groups}
        return normalized in fixed or normalized.startswith(self.name_prefix.strip().casefold())

    def matches(self, event: ADGroupEvent) -> bool:
        return self.matches_name(event.target_user_name)

