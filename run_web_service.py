from pathlib import Path
from datetime import datetime
import os
import socket
import sys
import threading


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


def _is_port_in_use(host: str = "127.0.0.1", port: int = 5000) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1)
        return sock.connect_ex((host, port)) == 0


def main():
    _configure_stdio()
    project_dir = Path(__file__).resolve().parent
    log_dir = project_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "web_service.log"

    if _is_port_in_use():
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().isoformat()}] Serviço web já está ativo na porta 5000; nova instância não será iniciada\n")
        print("Serviço web já está ativo na porta 5000. Use o script de restart para reiniciar a instância em execução.")
        return

    try:
        from waitress import serve
        from web_config import app

        try:
            import gerenciador_atualizacoes
            threading.Thread(target=gerenciador_atualizacoes.start_update_threads, daemon=True).start()
        except Exception as exc:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"[{datetime.now().isoformat()}] Falha ao iniciar gerenciador de atualizações: {exc}\n")

        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().isoformat()}] Iniciando serviço web em 0.0.0.0:5000\n")

        serve(app, listen="0.0.0.0:5000", threads=8)
    except Exception as exc:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().isoformat()}] Erro no serviço web: {exc}\n")
        raise


if __name__ == "__main__":
    main()
