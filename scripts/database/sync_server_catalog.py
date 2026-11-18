"""Compare or sync a server catalog; default mode is read-only using DPAPI."""

import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.database.import_firewall_cache import (
    DatabaseProgress, ImportErrorSafe, _database_error, _unique_keys,
)
from services.operational_postgres import SnapshotError, connect_collector
from services.operational_server_postgres import (
    inspect_server_snapshot, prepare_server_snapshot, write_server_snapshot,
)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "estrutura_regionais.json")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--simulate", action="store_true", help='Simular a projecao sem conexao SQL ou acesso ao cofre.')
    parser.add_argument("--expected-digest")
    args = parser.parse_args(argv)
    progress = DatabaseProgress(phase="leitura_origem")
    try:
        if os.environ.get("COMPUTERNAME", "").upper() != "RIGEL":
            raise SnapshotError("Execute somente no Rigel.")
        payload = json.loads(args.source.read_text(encoding="utf-8-sig"), object_pairs_hook=_unique_keys)
        snapshot = prepare_server_snapshot(payload)
        if args.simulate:
            print(json.dumps({**snapshot.summary(), 'modo': 'simulacao_sem_conexao_ao_banco'}, indent=2, ensure_ascii=True))
            return 0
        if args.apply and args.expected_digest != snapshot.digest:
            raise SnapshotError("Gravacao exige o digest exato da conferencia revisada.")
        progress.phase = "conexao"
        with connect_collector(read_only=not args.apply) as connection:
            progress.phase = "sincronizacao_servidores" if args.apply else "conferencia_somente_leitura"
            result = ({**snapshot.summary(), "modo": write_server_snapshot(connection, snapshot)}
                      if args.apply else inspect_server_snapshot(connection, snapshot))
            progress.phase = "finalizacao_transacao"
        print(json.dumps(result, indent=2, ensure_ascii=True))
        return 0
    except (ImportErrorSafe, SnapshotError) as exc:
        print(str(exc), file=sys.stderr)
    except Exception as exc:
        print(str(_database_error(progress.phase, exc)), file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
