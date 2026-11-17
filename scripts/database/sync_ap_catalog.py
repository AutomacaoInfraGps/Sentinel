"""Inspect a confirmed AP publication; applying requires its exact digest."""

import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.database.import_firewall_cache import _database_error, ImportErrorSafe
from services.operational_ap_postgres import (
    PUBLICATION_PATH, load_ap_publication, inspect_ap_snapshot, write_ap_snapshot, connect_collector,
)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--publication', type=Path, default=PUBLICATION_PATH)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--expected-digest')
    args = parser.parse_args(argv)
    phase = 'leitura_publicacao'
    try:
        if os.environ.get('COMPUTERNAME', '').upper() != 'RIGEL':
            raise ImportErrorSafe('Execute a conferencia de banco somente no Rigel.')
        if not args.publication.is_file():
            raise ImportErrorSafe('Publicacao ausente. Execute uma nova coleta UniFi e aguarde sua conclusao.')
        snapshot = load_ap_publication(args.publication)
        if args.apply and args.expected_digest != snapshot.digest:
            raise ImportErrorSafe('Gravacao exige o digest exato da publicacao revisada.')
        phase = 'conexao'
        with connect_collector(read_only=not args.apply) as connection:
            phase = 'sincronizacao' if args.apply else 'conferencia'
            result = ({**snapshot.summary(), 'modo': write_ap_snapshot(connection, snapshot)} if args.apply
                      else inspect_ap_snapshot(connection, snapshot))
            phase = 'finalizacao_transacao'
        print(json.dumps(result, indent=2, ensure_ascii=True))
        return 0
    except ImportErrorSafe as exc:
        print(str(exc), file=sys.stderr)
    except Exception as exc:
        print(str(_database_error(phase, exc)), file=sys.stderr)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
