"""Privacy-conscious JSONL audit logging for SofIA requests."""

from datetime import datetime, timezone
import json
from pathlib import Path
from threading import Lock


_AUDIT_LOCK = Lock()
_AUDIT_PATH = Path(__file__).resolve().parents[1] / "logs" / "sofia_audit.jsonl"


def registrar_evento_sofia(*, usuario, status, tamanho_mensagem, endereco_remoto=None, detalhe=None):
    """Append request metadata without storing conversation contents."""
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "usuario": str(usuario or "desconhecido"),
        "acao": "chat:basic",
        "status": str(status),
        "tamanho_mensagem": int(tamanho_mensagem or 0),
        "endereco_remoto": str(endereco_remoto or ""),
    }
    if detalhe:
        event["detalhe"] = str(detalhe)[:160]

    _AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _AUDIT_LOCK:
        with _AUDIT_PATH.open("a", encoding="utf-8") as audit_file:
            audit_file.write(json.dumps(event, ensure_ascii=False) + "\n")

