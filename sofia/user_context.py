"""Build the minimal authenticated user context exposed to SofIA."""

from __future__ import annotations

import re


MAX_DISPLAY_NAME_LENGTH = 80
_WHITESPACE_RE = re.compile(r"\s+")


def parse_creator_users(value):
    """Normalize a local creator allowlist without exposing it to the model."""
    if isinstance(value, str):
        entries = re.split(r"[,;\r\n]+", value)
    elif isinstance(value, (list, tuple, set, frozenset)):
        entries = value
    else:
        entries = ()
    return frozenset(
        str(entry).strip().casefold()
        for entry in entries
        if str(entry).strip()
    )


def build_user_context(user, creator_users=()):
    """Return identity facts asserted by Sentinel after authentication."""
    username = str(
        getattr(user, "username", None)
        or getattr(user, "id", None)
        or ""
    ).strip()
    raw_display_name = str(getattr(user, "display_name", None) or username).strip()
    display_name = _WHITESPACE_RE.sub(" ", raw_display_name)[:MAX_DISPLAY_NAME_LENGTH]
    relationship = (
        "creator"
        if username.casefold() in parse_creator_users(creator_users)
        else "user"
    )
    return {
        "display_name": display_name or "Usuario",
        "relationship": relationship,
    }
