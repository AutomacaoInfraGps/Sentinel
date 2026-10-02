from __future__ import annotations

import json
import os
from pathlib import Path
from typing import MutableMapping


_GRAPH_ENVIRONMENT_FIELDS = {
    "tenant_id": "M365_TENANT_ID",
    "client_id": "M365_CLIENT_ID",
    "client_secret": "M365_CLIENT_SECRET",
    "sender_upn": "M365_SENDER_UPN",
}


def load_sentinel_graph_environment(
    path: str | Path,
    *,
    environ: MutableMapping[str, str] | None = None,
) -> None:
    """Load Graph values in memory without logging or duplicating secrets."""
    source = Path(path)
    if not source.is_file():
        raise ValueError("Arquivo de ambiente do Sentinel nao encontrado")
    try:
        payload = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("Arquivo de ambiente do Sentinel invalido") from exc
    if not isinstance(payload, dict):
        raise ValueError("Arquivo de ambiente do Sentinel invalido")
    graph = payload.get("microsoft_graph")
    if not isinstance(graph, dict):
        raise ValueError("Configuracao Microsoft Graph do Sentinel ausente")

    target = environ if environ is not None else os.environ
    for field, variable in _GRAPH_ENVIRONMENT_FIELDS.items():
        value = graph.get(field)
        normalized = value.strip() if isinstance(value, str) else ""
        if normalized and not str(target.get(variable, "")).strip():
            target[variable] = normalized
