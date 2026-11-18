"""Capture a replication receipt without hostnames/errors, inspect or apply its current revision."""

import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.database.import_firewall_cache import ImportErrorSafe, _database_error
from services.operational_replication import (
    PUBLICATION_PATH, LOCK_PATH, SnapshotError, _InterprocessFileLock, read_current_snapshot,
    save_replication_publication, load_replication_publication, inspect_replication_snapshot,
    write_replication_snapshot, connect_collector,
)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--publication', type=Path, default=PUBLICATION_PATH)
    parser.add_argument('--source-timezone', help='Fuso legado explicito; somente com --capture.')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--capture', action='store_true')
    mode.add_argument('--apply', action='store_true')
    parser.add_argument('--expected-digest')
    args = parser.parse_args(argv)
    phase = 'leitura_publicacao'
    try:
        if os.environ.get('COMPUTERNAME', '').upper() != 'RIGEL':
            raise ImportErrorSafe('Execute somente no Rigel.')
        if args.source_timezone is not None and not args.capture:
            raise ImportErrorSafe('Fuso deve ser informado na captura, nao alterado no recibo revisado.')
        with _InterprocessFileLock(LOCK_PATH, timeout=0.25):
            if args.capture:
                snapshot = read_current_snapshot(args.source_timezone)
                save_replication_publication(snapshot, args.publication)
                result = {**snapshot.summary(), 'modo': 'captura_sem_conexao_ao_banco'}
            else:
                if not args.publication.is_file():
                    raise ImportErrorSafe('Recibo ausente. Execute --capture --source-timezone antes da conferencia.')
                snapshot = load_replication_publication(args.publication)
                if args.apply and args.expected_digest != snapshot.digest:
                    raise ImportErrorSafe('Gravacao exige o digest exato da publicacao revisada.')
                phase = 'conexao'
                with connect_collector(read_only=not args.apply) as connection:
                    phase = 'sincronizacao' if args.apply else 'conferencia'
                    result = ({**snapshot.summary(), 'modo': write_replication_snapshot(connection, snapshot)}
                              if args.apply else inspect_replication_snapshot(connection, snapshot))
                    phase = 'finalizacao_transacao'
        print(json.dumps(result, indent=2, ensure_ascii=True))
        return 0
    except (ImportErrorSafe, SnapshotError) as exc:
        print(str(exc), file=sys.stderr)
    except Exception as exc:
        print(str(_database_error(phase, exc)), file=sys.stderr)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
