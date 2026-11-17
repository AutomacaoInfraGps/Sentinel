"""Compare confirmed link observations; guarded manual sync is optional."""

import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.database.import_firewall_cache import DatabaseProgress, ImportErrorSafe, _database_error
from services.operational_postgres import SnapshotError, connect_collector
from services.operational_link_postgres import (
    PUBLICATION_PATH, inspect_link_snapshot, load_link_publication, write_link_snapshot,
)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--publication', type=Path, default=PUBLICATION_PATH)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--expected-digest')
    args = parser.parse_args(argv)
    progress = DatabaseProgress(phase='leitura_publicacao')
    try:
        if os.environ.get('COMPUTERNAME', '').upper() != 'RIGEL':
            raise SnapshotError('Execute somente no Rigel.')
        if not args.publication.is_file():
            raise SnapshotError('Publicacao de links ausente. Aguarde coleta confirmada do codigo atualizado.')
        snapshot = load_link_publication(args.publication)
        if args.apply and args.expected_digest != snapshot.digest:
            raise SnapshotError('Gravacao exige o digest exato da publicacao revisada.')
        progress.phase = 'conexao'
        with connect_collector(read_only=not args.apply) as connection:
            progress.phase = 'sincronizacao_links' if args.apply else 'conferencia_somente_leitura'
            result = ({**snapshot.summary(), 'modo': write_link_snapshot(connection, snapshot)}
                      if args.apply else inspect_link_snapshot(connection, snapshot))
            progress.phase = 'finalizacao_transacao'
        print(json.dumps(result, indent=2, ensure_ascii=True))
        return 0
    except (ImportErrorSafe, SnapshotError) as exc:
        print(str(exc), file=sys.stderr)
    except Exception as exc:
        print(str(_database_error(progress.phase, exc)), file=sys.stderr)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
