"""Bootstrap SLA regional contact assignments without editing the external workbook."""

import argparse
from collections import Counter
from dataclasses import dataclass, field
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.database.audit_administrative_sources import CONTACT_COLUMNS, ROLES, _filled
from scripts.database.audit_ap_sources import _read
from scripts.database.import_firewall_cache import DatabaseProgress, ImportErrorSafe, _database_error
from scripts.database.import_server_catalog import _identity, _text
from scripts.database.import_switch_catalog import _load
from services.sla_contact_matching import resolve_sla_contact_regional
from unifi_site_matching import normalize_unifi_site

SOURCE_ID = 'sentinel_sla_principal'
TABLES = ('fontes_contatos_sla', 'regionais_contatos_sla', 'contatos_regionais_sla')


@dataclass(frozen=True, repr=False)
class ContactCatalog:
    digest: str
    workbook_sha256: str
    regionals_sha256: str
    sheet: str = field(repr=False)
    regional_codes: tuple = field(repr=False)
    assignments: tuple = field(repr=False)
    contacts: tuple = field(repr=False)

    def summary(self):
        return {'digest_carga': self.digest, 'sha256_planilha': self.workbook_sha256,
                'sha256_catalogo_regionais': self.regionals_sha256,
                'regionais_no_catalogo': len(self.regional_codes),
                'regionais_sla': len(self.assignments), 'vinculos_contato_regional_papel': len(self.contacts),
                'por_papel': dict(Counter(row[1] for row in self.contacts)),
                'por_regra_vinculo_regional': dict(Counter(row[3] for row in self.assignments)),
                'nomes_sem_email': sum(bool(row[2]) and not row[3] for row in self.contacts),
                'emails_sem_nome': sum(bool(row[3]) and not row[2] for row in self.contacts),
                'pessoas_fundidas_automaticamente': False,
                'planilha_modificada': False, 'sincronizacao_automatica_contatos': False}


def _workbook_records(raw, sheet_name):
    from openpyxl import load_workbook
    with BytesIO(raw) as stream:
        workbook = load_workbook(stream, read_only=True, data_only=False, keep_links=False)
        try:
            if sheet_name and sheet_name not in workbook.sheetnames:
                raise ImportErrorSafe('Aba configurada ausente. Nao selecionar outra automaticamente.')
            sheet = workbook[sheet_name or workbook.sheetnames[0]]
            _text(sheet.title, 128, required=True)
            rows = sheet.iter_rows()
            header = next(rows, ())
            headers = [str(cell.value or '').strip() for cell in header]
            if any(headers.count(column) != 1 for column in CONTACT_COLUMNS):
                raise ImportErrorSafe('Colunas obrigatorias ausentes ou duplicadas.')
            positions = {column: headers.index(column) for column in CONTACT_COLUMNS}
            records = []
            for row_number, cells in enumerate(rows, 2):
                record = {}
                for column, position in positions.items():
                    cell = cells[position] if position < len(cells) else None
                    if cell is not None and cell.data_type in ('f', 'e'):
                        raise ImportErrorSafe('Formula ou erro em coluna de contato exige revisao.')
                    value = cell.value if cell is not None else None
                    if value is not None and not isinstance(value, str):
                        raise ImportErrorSafe('Coluna de contato deve conter texto ou vazio.')
                    record[column] = value.strip() if value else ''
                if any(record.values()):
                    records.append((row_number, record))
            return sheet.title, records
        finally:
            workbook.close()


def build_contact_catalog(raw_workbook, raw_regionals, sheet_name=''):
    catalog = _load(raw_regionals)
    regions = catalog.get('regionais') if isinstance(catalog, dict) else None
    if not isinstance(regions, dict) or not regions or any(not isinstance(item, dict) for item in regions.values()):
        raise ImportErrorSafe('Catalogo regional ausente ou invalido.')
    for code, entry in regions.items():
        if _text(code, 120, required=True) != code or code != code.upper():
            raise ImportErrorSafe('Codigo regional invalido.')
        _text(entry.get('nome'))
    sheet, records = _workbook_records(raw_workbook, sheet_name)
    assignments, contacts = [], []
    codes, labels, forti_labels = set(), set(), set()
    for row_number, record in records:
        label = _text(record['NOME_REGIONAL'], 240, required=True)
        forti = _text(record['NOME_REG_FORTI'], 500, required=True)
        normalized = normalize_unifi_site(label)
        code, reason, _ = resolve_sla_contact_regional(regions, label, forti)
        if code is None:
            raise ImportErrorSafe('Contato sem vinculo regional unico. Revise a auditoria.')
        if code in codes or normalized in labels or forti.casefold() in forti_labels:
            raise ImportErrorSafe('Identidade regional ou rotulo de origem duplicado. Nenhuma linha foi fundida.')
        codes.add(code)
        labels.add(normalized)
        forti_labels.add(forti.casefold())
        assignments.append((code, label, forti, reason, row_number))
        for role, name_column, email_column in ROLES:
            raw_name = _text(record[name_column], 500)
            raw_email = _text(record[email_column], 2000)
            name = raw_name if _filled(raw_name) else None
            email = raw_email if _filled(raw_email) else None
            if name is not None or email is not None:
                contacts.append((code, role, name, email))
    if not assignments or not contacts:
        raise ImportErrorSafe('Carga de contatos vazia bloqueada.')
    assignments.sort(key=lambda row: row[0])
    contacts.sort(key=lambda row: row[:2])
    hashes = hashlib.sha256(raw_workbook).hexdigest(), hashlib.sha256(raw_regionals).hexdigest()
    regional_codes = tuple(sorted(regions))
    canonical = (SOURCE_ID, hashes, sheet, regional_codes, assignments, contacts)
    digest = hashlib.sha256(json.dumps(canonical, ensure_ascii=True, separators=(',', ':')).encode()).hexdigest()
    return ContactCatalog(digest, *hashes, sheet, regional_codes, tuple(assignments), tuple(contacts))


def _inspect(cursor, catalog):
    cursor.execute('SELECT codigo FROM operacional.regionais WHERE codigo=ANY(%s)', (list(catalog.regional_codes),))
    missing = len(set(catalog.regional_codes) - {row[0] for row in cursor.fetchall()})
    counts = {}
    for table in TABLES:
        cursor.execute('SELECT count(*) FROM operacional.' + table)
        counts[table] = cursor.fetchone()[0]
    return {'regionais_do_catalogo_ausentes_no_banco': missing, 'contagens': counts,
            'tabelas_contatos_vazias': all(count == 0 for count in counts.values())}


def inspect_contact_catalog(connection, catalog):
    with connection.cursor() as cursor:
        cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        cursor.execute("SET LOCAL statement_timeout='5s'")
        _identity(cursor)
        return _inspect(cursor, catalog)


def write_contact_catalog(connection, catalog, *, progress=None):
    progress = progress or DatabaseProgress()
    with connection.cursor() as cursor:
        progress.phase = 'configuracao_transacao'
        cursor.execute('SET TRANSACTION ISOLATION LEVEL READ COMMITTED')
        cursor.execute("SET LOCAL lock_timeout='5s'")
        cursor.execute("SET LOCAL statement_timeout='30s'")
        progress.phase = 'validacao_destino'
        _identity(cursor)
        for table in ('regionais', *TABLES):
            cursor.execute('LOCK TABLE operacional.' + table + ' IN SHARE ROW EXCLUSIVE MODE')
        inspection = _inspect(cursor, catalog)
        if not inspection['tabelas_contatos_vazias']:
            raise ImportErrorSafe('Tabelas de contatos nao estao vazias. Nao repetir a carga inicial.')
        if inspection['regionais_do_catalogo_ausentes_no_banco']:
            raise ImportErrorSafe('Catalogo regional divergente. Carga bloqueada.')
        progress.phase = 'insercao_fonte'
        cursor.execute('INSERT INTO operacional.fontes_contatos_sla '
                       '(id,aba,arquivo_origem_sha256,catalogo_regionais_sha256,digest_carga) VALUES (%s,%s,%s,%s,%s)',
                       (SOURCE_ID, catalog.sheet, catalog.workbook_sha256, catalog.regionals_sha256, catalog.digest))
        progress.phase = 'insercao_vinculos_regionais'
        for row in catalog.assignments:
            cursor.execute('INSERT INTO operacional.regionais_contatos_sla '
                           '(fonte_id,codigo_regional,rotulo_regional_origem,rotulo_fortianalyzer_origem,'
                           'regra_vinculo,linha_planilha_origem) VALUES (%s,%s,%s,%s,%s,%s)', (SOURCE_ID, *row))
        progress.phase = 'insercao_contatos'
        for row in catalog.contacts:
            cursor.execute('INSERT INTO operacional.contatos_regionais_sla '
                           '(fonte_id,codigo_regional,papel,nome_origem,email_origem) VALUES (%s,%s,%s,%s,%s)',
                           (SOURCE_ID, *row))
        progress.phase = 'conferencia_final'
        final = _inspect(cursor, catalog)
        expected = dict(zip(TABLES, (1, len(catalog.assignments), len(catalog.contacts))))
        if final['contagens'] != expected:
            raise ImportErrorSafe('Contagens divergentes. Transacao cancelada.')
        cursor.execute('SELECT papel,count(*) FROM operacional.contatos_regionais_sla GROUP BY papel')
        if dict(cursor.fetchall()) != dict(Counter(row[1] for row in catalog.contacts)):
            raise ImportErrorSafe('Contagem por papel divergente. Transacao cancelada.')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, help='Copia XLSX; sem argumento usa somente a configuracao existente.')
    parser.add_argument('--sheet', help='Aba exata da copia XLSX; exigida com --source.')
    parser.add_argument('--regionals', type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--check-database', action='store_true')
    mode.add_argument('--apply', action='store_true')
    parser.add_argument('--expected-digest')
    args = parser.parse_args(argv)
    progress = DatabaseProgress(phase='leitura_origem')
    try:
        if (args.apply or args.check_database) and args.regionals is None:
            raise ImportErrorSafe('Operacao de banco exige --regionals apontando para a copia revisada.')
        if args.source is None:
            if args.sheet is not None or args.apply or args.check_database:
                raise ImportErrorSafe('Operacao de banco exige copias explicitas com --source, --sheet e --regionals.')
            section = _read(ROOT / 'environment.json').get('email_contatos') or {}
            configured = section.get('xlsx_path')
            if not isinstance(configured, str) or not configured.strip():
                raise ImportErrorSafe('Planilha nao configurada.')
            source = Path(configured).expanduser()
            sheet = section.get('sheet_name') or ''
            if not source.is_absolute():
                raise ImportErrorSafe('Caminho configurado deve ser absoluto.')
        else:
            source, sheet = args.source, args.sheet
            if not sheet or not sheet.strip():
                raise ImportErrorSafe('Informe a aba exata da copia usando --sheet.')
        if source.suffix.lower() != '.xlsx':
            raise ImportErrorSafe('Fonte exige arquivo XLSX.')
        regional_source = args.regionals or ROOT / 'estrutura_regionais.json'
        catalog = build_contact_catalog(source.read_bytes(), regional_source.read_bytes(), sheet)
        result = {'modo': 'simulacao_sem_conexao_ao_banco', **catalog.summary()}
        if args.apply or args.check_database:
            if os.environ.get('COMPUTERNAME', '').upper() != 'RIGEL':
                raise ImportErrorSafe('Execute a operacao de banco somente no Rigel.')
            if args.apply and args.expected_digest != catalog.digest:
                raise ImportErrorSafe('Gravacao exige o digest exato da simulacao revisada.')
            from services.operational_postgres import connect_collector
            progress.phase = 'conexao'
            with connect_collector(read_only=not args.apply) as connection:
                if args.apply:
                    write_contact_catalog(connection, catalog, progress=progress)
                    result['modo'] = 'carga_inicial_contatos_sla_confirmada'
                else:
                    progress.phase = 'conferencia_somente_leitura'
                    result['banco'] = inspect_contact_catalog(connection, catalog)
                    result['modo'] = 'conferencia_somente_leitura'
                progress.phase = 'finalizacao_transacao'
        print(json.dumps(result, indent=2, ensure_ascii=True))
        return 0
    except ImportErrorSafe as exc:
        print(str(exc), file=sys.stderr)
    except Exception as exc:
        print(str(_database_error(progress.phase, exc)), file=sys.stderr)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
