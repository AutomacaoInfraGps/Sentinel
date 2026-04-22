from pathlib import Path
from datetime import datetime
import os
import sys


def _configure_stdio():
    os.environ.setdefault("PYTHONUTF8", "1")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if not stream:
            continue
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def main():
    _configure_stdio()
    project_dir = Path(__file__).resolve().parent
    log_dir = project_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "web_service.log"

    try:
        from waitress import serve
        from web_config import app

        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().isoformat()}] Iniciando serviço web em 0.0.0.0:5000\n")

        serve(app, listen="0.0.0.0:5000", threads=8)
    except Exception as exc:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().isoformat()}] Erro no serviço web: {exc}\n")
        raise


if __name__ == "__main__":
    main()