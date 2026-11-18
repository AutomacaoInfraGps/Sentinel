"""Capture a PII-free receipt or inspect/apply its current SLA workbook revision."""

import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.database.import_firewall_cache import ImportErrorSafe, _database_error
from services.operational_sla_contacts import (
    PUBLICATION_PATH, LOCK_PATH, SnapshotError, _InterprocessFileLock, read_current_snapshot, save_contact_publication,
    load_contact_publication, inspect_contact_snapshot, write_contact_snapshot, connect_collector,
)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--publication', type=Path, default=PUBLICATION_PATH)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--capture', action='store_true', help='Le fonte atual e salva recibo sem dados pessoais; nao conecta ao banco.')
    mode.add_argument('--apply', action='store_true')
    parser.add_argument('--expected-digest')
    args = parser.parse_args(argv)
    phase = 'leitura_publicacao'
    try:
        if os.environ.get('COMPUTERNAME', '').upper() != 'RIGEL':
            raise ImportErrorSafe('Execute somente no Rigel.')
        with _InterprocessFileLock(LOCK_PATH, timeout=0.25):
            if args.capture:
                snapshot = read_current_snapshot()
                save_contact_publication(snapshot, args.publication)
                result = {**snapshot.summary(), 'modo': 'captura_sem_conexao_ao_banco'}
            else:
                if not args.publication.is_file():
                    raise ImportErrorSafe('Recibo ausente. Execute este comando com --capture antes da conferencia.')
                snapshot = load_contact_publication(args.publication)
                if args.apply and snapshot.digest != args.expected_digest:
                    raise ImportErrorSafe('Gravacao exige o digest exato da publicacao revisada.')
                phase = 'conexao'
                with connect_collector(read_only=not args.apply) as connection:
                    phase = 'sincronizacao' if args.apply else 'conferencia'
                    result = ({**snapshot.summary(), 'modo': write_contact_snapshot(connection, snapshot)} if args.apply
                              else inspect_contact_snapshot(connection, snapshot))
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
