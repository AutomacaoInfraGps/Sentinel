"""Shared credential naming rules for legacy server records."""

from __future__ import annotations

import re
import unicodedata
from typing import Mapping


LEGACY_CREDENTIAL_STORAGE = "vault-v1"


def reference_segment(value: object) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9._-]+", "-", ascii_value).strip("-._") or "item"


def server_reference(server: Mapping[str, object], index: int) -> str:
    server_id = server.get("id") or f"index-{index}"
    return f"legacy-servers/{reference_segment(server_id)}/senha"
