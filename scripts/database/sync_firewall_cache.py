"""Check or manually sync a global firewall snapshot using the DPAPI credential."""

import argparse
import json
import os
from pathlib import Path
import re
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.operational_postgres import (  # noqa: E402
    SnapshotError, connect_collector, inspect_snapshot, prepare_snapshot, write_snapshot,
)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=PROJECT_ROOT / "output" / "dashboard_firewalls_cache.json")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--expected-digest")
    args = parser.parse_args(argv)
    try:
        if os.environ.get("COMPUTERNAME", "").upper() != "RIGEL":
            raise SnapshotError("Execute esta conferencia somente no Rigel.")
        if args.apply and not args.expected_digest:
            raise SnapshotError("Gravacao exige --expected-digest da conferencia revisada.")
        with args.cache.open(encoding="utf-8-sig") as stream:
            snapshot = prepare_snapshot(json.load(stream))
        if args.expected_digest and args.expected_digest != snapshot.digest:
            raise SnapshotError("Snapshot mudou. Refaca a conferencia antes de gravar.")
        with connect_collector(read_only=not args.apply) as connection:
            if args.apply:
                result = {**snapshot.summary(), "modo": write_snapshot(connection, snapshot)}
            else:
                result = inspect_snapshot(connection, snapshot)
        print(json.dumps(result, indent=2, ensure_ascii=True))
        return 0
    except SnapshotError as exc:
        print(str(exc), file=sys.stderr)
    except Exception as exc:
        state = getattr(exc, "sqlstate", None)
        state = state if isinstance(state, str) and re.fullmatch(r"[0-9A-Z]{5}", state) else "indisponivel"
        print(f"Falha na operacao paralela. SQLSTATE={state}. Confira o banco antes de repetir uma gravacao.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
