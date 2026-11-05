import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services import firewall_releases as module


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.data = {'checked_at': '2026-10-26T12:00:00+00:00', 'lines': ['7.4', '7.6'],
                     'releases': [self.release('7.4.9'), self.release('7.4.13'),
                                  self.release('7.6.8'), self.release('7.6.9', 'FG-61F')]}

    def release(self, value, hardware='FG-60F'):
        return {'version': value, 'models': [hardware],
                'url': module.BASE + '/document/fortigate/' + value + '/fortios-release-notes'}

    def test_patch_before_other_line_and_exact_model(self):
        result = module.assess(self.data, 'FortiGate-60F', 'v7.4.9, build123')
        self.assertEqual(result['state'], 'update')
        self.assertIn('7.4.13', result['message'])
        self.assertIn('7.6.8', result['message'])
        self.assertNotIn('7.6.9', result['message'])

    def test_absent_not_end_of_support(self):
        result = module.assess(self.data, 'FortiGate-60F', '4.3.1')
        self.assertEqual(result['state'], 'absent')
        self.assertNotIn('sem suporte', result['message'])

    def test_unknown_and_missing_catalog(self):
        for snapshot, hardware, firmware in [(None, 'FortiGate-60F', '7.4.9'),
                                             (self.data, 'Unknown', '7.4.9'),
                                             (self.data, 'FortiGate-60F', 'N/A')]:
            self.assertEqual(module.assess(snapshot, hardware, firmware)['state'], 'unknown')

    def test_no_matching_model_does_not_mean_current(self):
        self.assertEqual(module.assess(self.data, 'FortiGate-80F', '7.4.9')['state'], 'unknown')

    def test_current_and_stale(self):
        result = module.assess(self.data, 'FG-60F', '7.6.8', True)
        self.assertEqual(result['state'], 'current')
        self.assertIn('desatualizada', result['label'])

    def test_failure_keeps_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'catalog.json'
            path.write_text(json.dumps(self.data), encoding='utf-8')
            catalog = module.ReleaseCatalog(path)
            with patch.object(module, 'collect', side_effect=ValueError()):
                catalog._refresh()
            self.assertEqual(catalog.snapshot(), self.data)

    def test_external_links_rejected(self):
        for url in ['http://docs.fortinet.com/a', 'https://example.invalid/a',
                    'https://docs.fortinet.com@example.invalid/a']:
            with self.assertRaises(ValueError):
                module._public_url(url)

    def test_partial_newer_line_prevents_current_claim(self):
        self.data['unverified_lines'] = ['7.8']
        self.assertEqual(module.assess(self.data, 'FG-60F', '7.6.8')['state'], 'unknown')

    def test_update_rule_stays_within_installed_major_family(self):
        current = self.release('7.0.0')
        next_version = self.release('7.1.0')
        next_family = self.release('8.0.0')

        cases = [
            ([current, next_version], 'update', '7.1.0'),
            ([current, next_version, next_family], 'update', '7.1.0'),
            ([current, next_family], 'current', None),
            ([current], 'current', None),
        ]
        for releases, state, available in cases:
            with self.subTest(releases=[release['version'] for release in releases]):
                snapshot = {'checked_at': self.data['checked_at'],
                            'lines': ['7.0', '7.1', '8.0'], 'releases': releases}
                result = module.assess(snapshot, 'FG-60F', '7.0.0')
                self.assertEqual(result['state'], state)
                self.assertEqual(result.get('available_version'), available)

    def test_relative_page_url_is_normalized(self):
        from unittest.mock import Mock
        session = Mock()
        session.get.return_value.status_code = 200
        session.get.return_value.text = '<html></html>'
        _, url = module._page(session, '/product/fortigate/9.0')
        self.assertEqual(url, module.BASE + '/product/fortigate/9.0')

    def test_fresh_cache_does_not_start_thread(self):
        from datetime import datetime, timezone
        self.data['checked_at'] = datetime.now(timezone.utc).isoformat()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'catalog.json'
            path.write_text(json.dumps(self.data), encoding='utf-8')
            with patch.object(module.threading, 'Thread') as thread:
                _, stale = module.ReleaseCatalog(path).get()
                self.assertFalse(stale)
                thread.assert_not_called()

    def test_collect_discovers_line_and_parses_table(self):
        from bs4 import BeautifulSoup
        pages = ['<a href="/product/fortigate/9.0">9.0</a>',
                 '<a href="/document/fortigate/9.0.1/fortios-release-notes">notes</a>',
                 '<h2>Supported models</h2><table><tr><td>FG-60F, FG-61F</td></tr></table>']
        with patch.object(module, '_page', side_effect=[(BeautifulSoup(p, 'html.parser'), module.BASE) for p in pages]):
            result = module.collect()
        self.assertEqual(result['lines'], ['9.0'])
        self.assertEqual(result['releases'][0]['models'], ['FG-60F', 'FG-61F'])


if __name__ == '__main__':
    unittest.main()
