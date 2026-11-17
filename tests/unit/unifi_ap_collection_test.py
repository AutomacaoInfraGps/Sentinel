import ast
from datetime import datetime, timezone
from pathlib import Path
import unittest
from unittest.mock import MagicMock

from services.unifi_ap_collection import confirmed_device_response, ap_collection_evidence


class UnifiApCollectionTests(unittest.TestCase):
    def test_confirmed_response_attaches_aware_time_after_validation(self):
        response = MagicMock()
        devices = [{'type': 'uap', 'state': 1}]
        response.json.return_value = {'meta': {'rc': 'ok'}, 'data': devices}
        before = datetime.now(timezone.utc)
        result, at = confirmed_device_response(response)
        self.assertEqual(result, devices)
        self.assertGreaterEqual(datetime.fromisoformat(at), before)
        response.raise_for_status.assert_called_once()

    def test_http_error_or_api_error_is_not_empty_success(self):
        response = MagicMock()
        response.raise_for_status.side_effect = RuntimeError('HTTP error')
        with self.assertRaises(RuntimeError):
            confirmed_device_response(response)
        response.json.assert_not_called()
        response.raise_for_status.side_effect = None
        for data in ({'meta': {'rc': 'error'}, 'data': []}, {'data': [None]},
                     {'data': {}}, [], {'meta': 'error', 'data': []}):
            response.json.return_value = data
            with self.assertRaises(ValueError):
                confirmed_device_response(response)

    def test_real_empty_response_is_valid_but_does_not_infer_offline(self):
        response = MagicMock()
        response.json.return_value = {'data': []}
        devices, at = confirmed_device_response(response)
        self.assertEqual(devices, [])
        self.assertIsNotNone(datetime.fromisoformat(at).utcoffset())

    def test_missing_or_untyped_state_does_not_confirm_status(self):
        for value in (None, True, '1', -1, {}, 1.0):
            self.assertFalse(ap_collection_evidence({'state': value}, 'site', 'time')['coleta_status_confirmada'])
        for value in (0, 1, 5):
            result = ap_collection_evidence({'state': value, 'password': 'PRIVATE'}, 'site', 'time')
            self.assertTrue(result['coleta_status_confirmada'])
            self.assertNotIn('PRIVATE', str(result))

    def test_both_native_collectors_use_evidence_in_existing_device_query(self):
        root = Path(__file__).resolve().parents[2]
        for filename in ('Unifi.Py', 'scripts/Unifi.py'):
            tree = ast.parse((root / filename).read_text(encoding='utf-8-sig'))
            calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)]
            self.assertEqual(sum(node.func.id == 'confirmed_device_response' for node in calls), 1)
            self.assertEqual(sum(node.func.id == 'ap_collection_evidence' for node in calls), 1)
            self.assertTrue(any(isinstance(node, ast.Constant) and node.value == 'coleta_aps_confirmada'
                                for node in ast.walk(tree)))


if __name__ == '__main__':
    unittest.main()
