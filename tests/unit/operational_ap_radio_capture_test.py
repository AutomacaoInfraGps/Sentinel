from contextlib import redirect_stdout, redirect_stderr
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from scripts.database import capture_ap_radio_catalog as module
from services.unifi_radio_collection import ap_radio_evidence

NOW = datetime(2026, 11, 19, 18, tzinfo=timezone.utc)
AT = (NOW - timedelta(minutes=1)).isoformat()


def payload():
    ap = {'mac': '00:11:22:33:44:55', 'site_id': 'PRIVATE_SITE', 'nome': 'PRIVATE_NAME',
          'coletado_em': AT, 'password': 'SECRET_MARKER'}
    native = ap_radio_evidence({
        'mac': ap['mac'], 'state': 0,
        'radio_table': [{'name': 'wifi1', 'radio': 'na', 'channel': 'auto'},
                        {'name': 'wifi0', 'radio': 'ng', 'channel': 0}],
        'radio_table_stats': [{'name': 'wifi0', 'cu_total': 0, 'cu_self_tx': 2,
                              'cu_self_rx': 1, 'password': 'SECRET_MARKER'}],
    }, ap['site_id'], AT)
    return {'controller': {'ip': '192.0.2.1', 'porta': 8443, 'password': 'SECRET_MARKER'},
            'timestamp': '2026-11-19T14:00:00', 'aps': [{**ap, 'radios_nativos': native}],
            'sites': [{'id': ap['site_id'], 'nome': 'PRIVATE_NAME',
                       'coletado_em': AT, 'coleta_aps_confirmada': True}],
            'interferencia_5ghz_por_site': {'SECRET_MARKER': []}}


def capture(original=None):
    return module.capture_payload(json.dumps(original or payload()).encode(), NOW)


class ApRadioCaptureTests(unittest.TestCase):
    def destination(self, endpoint=('192.0.2.1', 8443), sites=None, aps=None):
        connection, cursor = MagicMock(), MagicMock()
        connection.cursor.return_value.__enter__.return_value = cursor
        cursor.fetchone.side_effect = [('sentinel', 'sentinel_collector', 5433), endpoint]
        cursor.fetchall.side_effect = [sites if sites is not None else [('PRIVATE_SITE',)],
                                      aps if aps is not None else [('00:11:22:33:44:55', 'PRIVATE_SITE')]]
        return connection, cursor

    def test_destination_checks_existing_ids_readonly_without_names(self):
        connection, cursor = self.destination()
        result = module.inspect_destination(connection, capture())
        self.assertTrue(result['destino_compativel'])
        self.assertFalse(result['tabelas_rf_conferidas'])
        self.assertFalse(result['vinculos_existentes_modificados'])
        self.assertNotIn('PRIVATE', json.dumps(result))
        self.assertNotIn('192.0.2.1', json.dumps(result))
        queries = [call.args[0] for call in cursor.execute.call_args_list]
        self.assertEqual(queries[0], 'SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        self.assertTrue(all(query.startswith(('SET ', 'SELECT ')) for query in queries))
        self.assertTrue(all('nome' not in query.lower() for query in queries))

    def test_destination_reports_missing_moved_and_endpoint_mismatch_without_fixes(self):
        connection, _ = self.destination(endpoint=None, sites=[], aps=[])
        result = module.inspect_destination(connection, capture())
        self.assertFalse(result['destino_compativel'])
        self.assertFalse(result['controladora_encontrada'])
        self.assertEqual(result['aps_da_captura_ausentes'], 1)
        self.assertEqual(result['sites_da_captura_ausentes'], 1)
        connection, _ = self.destination(endpoint=('other.invalid', 8443),
                                         aps=[('00:11:22:33:44:55', 'other')])
        result = module.inspect_destination(connection, capture())
        self.assertFalse(result['destino_compativel'])
        self.assertEqual(result['aps_com_site_divergente'], 1)

    def test_destination_wrong_database_identity_blocks_before_inventory_queries(self):
        connection, cursor = self.destination()
        cursor.fetchone.side_effect = [('other', 'sentinel_collector', 5433)]
        with self.assertRaises(ValueError):
            module.inspect_destination(connection, capture())
        self.assertEqual(len(cursor.execute.call_args_list), 3)

    def test_cli_sql_requires_rigel_frozen_source_and_readonly_connection(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'snapshot.json'
            raw = module._encode(capture())
            path.write_bytes(raw)
            out, error = StringIO(), StringIO()
            connection, _ = self.destination()
            connection.__enter__.return_value = connection
            with patch.dict('os.environ', {'COMPUTERNAME': 'RIGEL'}), patch(
                    'services.operational_postgres.connect_collector', return_value=connection) as connect, redirect_stdout(out), redirect_stderr(error):
                self.assertEqual(module.main(['--check-database']), 1)
                connect.assert_not_called()
                self.assertEqual(module.main(['--source', str(path), '--check-database']), 0)
                connect.assert_called_once_with(read_only=True)
            result = json.loads(out.getvalue())
            self.assertTrue(result['banco']['destino_compativel'])
            self.assertTrue(result['vinculos_sql_conferidos'])
            self.assertEqual(result['modo'], 'conferencia_destino_somente_leitura')
            self.assertNotIn('PRIVATE', out.getvalue())
            self.assertEqual(path.read_bytes(), raw)
            with patch.dict('os.environ', {'COMPUTERNAME': 'OTHER'}), patch(
                    'services.operational_postgres.connect_collector') as connect, redirect_stderr(error):
                self.assertEqual(module.main(['--source', str(path), '--check-database']), 1)
                connect.assert_not_called()

    def test_cli_sql_failure_omits_driver_message_and_source_values(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'snapshot.json'
            path.write_bytes(module._encode(capture()))
            out, error = StringIO(), StringIO()
            with (patch.dict('os.environ', {'COMPUTERNAME': 'RIGEL'}), patch(
                    'services.operational_postgres.connect_collector', side_effect=RuntimeError('SECRET_MARKER')),
                    redirect_stdout(out), redirect_stderr(error)):
                self.assertEqual(module.main(['--source', str(path), '--check-database']), 1)
            self.assertEqual(out.getvalue(), '')
            self.assertNotIn('SECRET_MARKER', error.getvalue())
            self.assertIn('conexao', error.getvalue())

    def test_safe_snapshot_separate_tables_and_nulls_round_trip(self):
        original = payload()
        before = deepcopy(original)
        result = capture(original)
        self.assertEqual(module.validate_capture(module._encode(result)), result)
        self.assertEqual(original, before)
        self.assertNotIn('SECRET_MARKER', module._encode(result).decode())
        self.assertNotIn('PRIVATE_NAME', module._encode(result).decode())
        ap = result['aps'][0]
        self.assertEqual([r['nome_interface'] for r in ap['configuracoes']['registros']], ['wifi0', 'wifi1'])
        self.assertEqual(len(ap['estatisticas']['registros']), 1)
        self.assertEqual(ap['estatisticas']['registros'][0]['cu_total'], 0)
        self.assertIsNone(ap['estatisticas']['registros'][0]['tx_retry'])
        self.assertIsNone(ap['medido_em'])
        self.assertFalse(ap['ap_online_declarado'])
        summary = module.summary(result)
        self.assertEqual(summary['metricas_por_situacao']['tx_retry'], {'ausente': 1})
        self.assertEqual(summary['publicacao_fonte'], 'sem_fuso')
        for value in ('PRIVATE', '192.0.2.1', '00:11:22:33:44:55', 'wifi0'):
            self.assertNotIn(value, json.dumps(summary))
        self.assertFalse(summary['vinculos_sql_conferidos'])
        self.assertFalse(summary['postgresql_acessado'])

    def test_missing_projection_invalid_version_or_extra_fields_block(self):
        for edit in ('missing', 'extra', 'version', 'measurement', 'flag'):
            original = payload()
            row = original['aps'][0]['radios_nativos']
            if edit == 'missing':
                original['aps'][0].pop('radios_nativos')
            elif edit == 'extra':
                row['password'] = 'SECRET_MARKER'
            elif edit == 'version':
                row['version'] = True
            elif edit == 'measurement':
                row['medido_em'] = AT
            else:
                row['recebimento_com_fuso'] = False
            with self.subTest(edit=edit), self.assertRaises(module.CaptureError):
                capture(original)

    def test_identity_duplicates_and_clock_mismatches_block(self):
        for edit in ('mac', 'site', 'duplicate_ap', 'duplicate_site', 'site_time', 'ap_time', 'future', 'naive', 'empty'):
            original = payload()
            ap = original['aps'][0]
            if edit == 'mac':
                ap['radios_nativos']['mac'] = '00:11:22:33:44:66'
            elif edit == 'site':
                ap['radios_nativos']['site_id'] = 'other'
            elif edit == 'duplicate_ap':
                original['aps'].append(deepcopy(ap))
            elif edit == 'duplicate_site':
                original['sites'].append(deepcopy(original['sites'][0]))
            elif edit == 'site_time':
                original['sites'][0]['coletado_em'] = NOW.isoformat()
            elif edit == 'ap_time':
                ap['coletado_em'] = NOW.isoformat()
            elif edit == 'future':
                at = (NOW + timedelta(seconds=1)).isoformat()
                original['sites'][0]['coletado_em'] = ap['coletado_em'] = ap['radios_nativos']['recebido_em'] = at
            elif edit == 'naive':
                ap['radios_nativos']['recebido_em'] = '2026-11-19T10:00:00'
            else:
                original['aps'] = []
            with self.subTest(edit=edit), self.assertRaises(module.CaptureError):
                capture(original)

    def test_invalid_tables_ambiguous_interfaces_and_values_block(self):
        for edit in ('shape', 'discarded', 'name', 'duplicate', 'unique_flag', 'metric', 'state', 'channel'):
            original = payload()
            table = original['aps'][0]['radios_nativos']['estatisticas']
            row = table['registros'][0]
            if edit == 'shape':
                table['situacao'] = 'estrutura_invalida'
            elif edit == 'discarded':
                table['registros_invalidos'] = 1
            elif edit == 'name':
                row['nome_interface'] = None
                row['situacao_campos']['nome_interface'] = 'ausente'
            elif edit == 'duplicate':
                table['registros'].append(deepcopy(row))
            elif edit == 'unique_flag':
                row['interface_unica_na_tabela'] = False
            elif edit == 'metric':
                row['cu_total'] = True
            elif edit == 'state':
                row['situacao_campos']['cu_total'] = 'ausente'
            else:
                row['canal'] = 'SECRET_MARKER'
                row['situacao_campos']['canal'] = 'informado'
            with self.subTest(edit=edit), self.assertRaises(module.CaptureError):
                capture(original)

    def test_explicit_null_invalid_and_absent_states_preserved(self):
        original = payload()
        row = original['aps'][0]['radios_nativos']['estatisticas']['registros'][0]
        row['tx_retry'], row['situacao_campos']['tx_retry'] = None, 'invalido'
        row['cu_self_tx'], row['situacao_campos']['cu_self_tx'] = None, 'nulo'
        result = capture(original)
        self.assertEqual(module.summary(result)['metricas_por_situacao']['tx_retry'], {'invalido': 1})
        self.assertEqual(module.summary(result)['metricas_por_situacao']['cu_self_tx'], {'nulo': 1})

    def test_tampering_extra_envelope_and_noncanonical_order_block(self):
        for key, value in (('digest_carga', 'a'*64), ('sha256_projecao', 'b'*64),
                           ('sha256_arquivo_origem', 'c'*64), ('version', True),
                           ('password', 'SECRET_MARKER'), ('fonte', 'other')):
            result = {**capture(), key: value}
            with self.subTest(key=key), self.assertRaises(module.CaptureError):
                module.validate_capture(module._encode(result))
        result = capture()
        result['aps'][0]['configuracoes']['registros'].reverse()
        with self.assertRaises(module.CaptureError):
            module.validate_capture(module._encode(result))

    def test_cli_capture_exclusive_round_trip_and_safe_failures(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'data').mkdir()
            raw = json.dumps(payload()).encode()
            (root / 'data/unifi.json').write_bytes(raw)
            target = root / 'snapshot.json'
            original_capture = module.capture_payload
            out, error = StringIO(), StringIO()
            with patch.object(module, 'ROOT', root), patch.object(module, 'capture_payload',
                    side_effect=lambda data: original_capture(data, NOW)), redirect_stdout(out), redirect_stderr(error):
                self.assertEqual(module.main([]), 0)
                self.assertFalse(target.exists())
                self.assertEqual(module.main(['--capture', str(target)]), 0)
                frozen = target.read_bytes()
                self.assertEqual(module.main(['--source', str(target)]), 0)
                self.assertEqual(module.main(['--capture', str(target)]), 1)
                self.assertEqual(target.read_bytes(), frozen)
                self.assertEqual(module.main(['--source', str(target), '--capture', str(target)]), 1)
            self.assertNotIn('SECRET_MARKER', out.getvalue() + error.getvalue())
            self.assertNotIn('PRIVATE', out.getvalue() + error.getvalue())
            self.assertEqual((root / 'data/unifi.json').read_bytes(), raw)

    def test_source_change_during_read_blocks_capture(self):
        raw = json.dumps(payload()).encode()
        out, error = StringIO(), StringIO()
        original_capture = module.capture_payload
        with patch.object(Path, 'read_bytes', side_effect=[raw, b'changed']), patch.object(
                module, 'capture_payload', side_effect=lambda data: original_capture(data, NOW)), redirect_stdout(out), redirect_stderr(error):
            self.assertEqual(module.main([]), 1)
        self.assertIn('Fonte mudou', error.getvalue())
        self.assertEqual(out.getvalue(), '')

    def test_nonfinite_duplicate_json_keys_invalid_endpoint_and_oversize_block(self):
        for raw in (b'{"aps": [], "aps": []}', b'{"x":NaN}', b'SECRET_MARKER', b'[]', b'x'*(32*1024*1024+1)):
            with self.assertRaises(module.CaptureError) as error:
                module.capture_payload(raw, NOW)
            self.assertNotIn('SECRET_MARKER', str(error.exception))
        for host, port in (('999.999.1.1', 8443), ('https://private', 8443), ('host', True), ('host', 0)):
            original = payload()
            original['controller'].update(ip=host, porta=port)
            with self.assertRaises(module.CaptureError):
                capture(original)


if __name__ == '__main__':
    unittest.main()
