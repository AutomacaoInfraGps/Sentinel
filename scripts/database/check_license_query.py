"""Operator-only scoped SQL diagnostic; this CLI does not authenticate AD users."""

import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.operational_license_query import LicenseQueryError, query_postgres_licenses
from services.operational_postgres import connect_collector


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--regional", action="append", required=True,
                        help="Escopo explicito desta conferencia tecnica; pode repetir.")
    parser.add_argument("--within-days", type=int)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--offset", type=int, default=0)
    args = parser.parse_args(argv)
    if os.environ.get("COMPUTERNAME", "").upper() != "RIGEL":
        parser.error("Execute somente no Rigel.")
    try:
        with connect_collector(read_only=True) as connection:
            result = query_postgres_licenses(
                connection, allowed_regionals=args.regional,
                expires_within_days=args.within_days, limit=args.limit, offset=args.offset,
            )
        print(json.dumps(result, indent=2, ensure_ascii=True))
        return 0
    except (ValueError, PermissionError, LicenseQueryError) as exc:
        print(str(exc), file=sys.stderr)
    except Exception:
        print("Falha na conferencia de licencas. Detalhes omitidos.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
