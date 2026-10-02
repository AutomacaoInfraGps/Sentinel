from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from alertad.graph import DelegatedTokenProvider, GraphAuthenticationError


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Renova manualmente o cache delegado usado pelo Teams."
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=PROJECT_ROOT / ".env",
        help="Arquivo local protegido com as variáveis do Graph.",
    )
    args = parser.parse_args()
    try:
        from dotenv import load_dotenv
    except ImportError:
        load_dotenv = None
    if args.env_file.exists() and load_dotenv is not None:
        load_dotenv(args.env_file, override=False)

    client_id = (
        os.getenv("M365_DELEGATED_CLIENT_ID", "").strip()
        or os.getenv("M365_CLIENT_ID", "").strip()
    )
    try:
        provider = DelegatedTokenProvider(
            os.getenv("M365_TENANT_ID", ""),
            client_id,
            os.getenv("M365_SENDER_UPN", ""),
            os.getenv(
                "ALERTAD_TEAMS_CACHE_FILE",
                str(PROJECT_ROOT / ".auth_cache" / "teams_token_cache.bin"),
            ),
        )
        provider.renew_interactively()
    except (ValueError, GraphAuthenticationError) as exc:
        print(f"ERRO: {exc}", flush=True)
        return 1
    print("Cache delegado do Teams atualizado.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
