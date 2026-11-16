"""Run the actual switch job functions without importing production Flask setup."""

import ast
from pathlib import Path
from queue import Queue
from threading import Thread
import unittest
from unittest.mock import Mock

from flask import Flask, current_app, has_app_context, has_request_context


ROOT = Path(__file__).resolve().parents[2]


class SwitchBackgroundContextTest(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config['SWITCH_TEST_MARKER'] = 'context-active'
        self.app.logger = Mock()
        self.manager = Mock()
        self.manager.switches = [{'host': 'SW1', 'status': 'online'}]
        self.manager.regionais = {'REG_A': self.manager.switches}
        self.result = {'status': 'online', 'detalhes': {}, 'ultima_verificacao': None}

        def assert_context(*args, **kwargs):
            self.assertTrue(has_app_context())
            self.assertFalse(has_request_context())
            self.assertEqual(current_app.config['SWITCH_TEST_MARKER'], 'context-active')

        self.assert_context = assert_context

        def create_manager():
            assert_context()
            return self.manager

        def authenticate():
            assert_context()
            return True

        def verify_single(*args, **kwargs):
            assert_context()
            return dict(self.result)

        def verify_all(*args, **kwargs):
            assert_context()
            kwargs['progress_callback'](1, 1, 'SW1', self.result)
            return {'SW1': dict(self.result)}

        self.manager.autenticar.side_effect = authenticate
        self.manager.verificar_switch.side_effect = verify_single
        self.manager.verificar_todos_switches.side_effect = verify_all
        self.published = Mock(side_effect=assert_context)
        self.completed = Mock(side_effect=assert_context)
        self.failed = Mock(side_effect=assert_context)
        self.namespace = {
            'app': self.app, 'GerenciadorSwitches': create_manager,
            '_publicar_switches_atualizados': self.published,
            '_update_background_job': Mock(side_effect=assert_context),
            '_complete_background_job': self.completed,
            '_fail_background_job': self.failed,
            '_switches_da_regional_manager': Mock(return_value=self.manager.switches),
            '_verificar_switches_manager_regional': Mock(return_value={'SW1': self.result}),
        }
        tree = ast.parse((ROOT / 'web_config.py').read_text(encoding='utf-8-sig'))
        names = {'_run_switches_job', '_execute_switches_job', '_build_switches_resumo'}
        selected = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
        self.assertEqual(len(selected), len(names))
        module = ast.Module(body=selected, type_ignores=[])
        exec(compile(module, str(ROOT / 'web_config.py'), 'exec'), self.namespace)

    def run_in_thread(self, mode):
        errors = Queue()

        def execute():
            try:
                self.namespace['_run_switches_job']('job1', mode=mode, regional='REG_A', host='SW1')
                self.assertFalse(has_app_context())
            except BaseException as exc:
                errors.put(exc)

        thread = Thread(target=execute)
        thread.start()
        thread.join(timeout=5)
        self.assertFalse(thread.is_alive())
        if not errors.empty():
            raise errors.get()

    def test_all_modes_publish_inside_app_context_without_request(self):
        for mode in ('all', 'single', 'regional', 'reload'):
            with self.subTest(mode=mode):
                self.completed.reset_mock()
                self.published.reset_mock()
                self.run_in_thread(mode)
                self.published.assert_called_once_with(self.manager)
                self.completed.assert_called_once()
                self.failed.assert_not_called()
                self.assertFalse(has_app_context())

    def test_publishing_failure_marks_job_failed_and_releases_context(self):
        def fail_publish(*args):
            self.assert_context()
            raise RuntimeError('publication failed')

        self.published.side_effect = fail_publish
        self.run_in_thread('all')
        self.failed.assert_called_once()
        self.completed.assert_not_called()
        self.app.logger.exception.assert_called_once()

    def test_manager_initialization_failure_is_reported(self):
        self.namespace['GerenciadorSwitches'] = Mock(side_effect=RuntimeError('initialization failed'))
        self.run_in_thread('all')
        self.failed.assert_called_once()
        self.completed.assert_not_called()
        self.published.assert_not_called()

    def test_authentication_failure_does_not_publish(self):
        self.manager.autenticar.side_effect = lambda: False
        self.run_in_thread('all')
        self.failed.assert_called_once()
        self.published.assert_not_called()
        self.completed.assert_not_called()

    def test_regional_error_does_not_publish(self):
        self.namespace['_verificar_switches_manager_regional'].return_value = {'error': 'Regional sem switches'}
        self.run_in_thread('regional')
        self.failed.assert_called_once()
        self.published.assert_not_called()
        self.completed.assert_not_called()

    def test_context_is_released_even_if_inner_job_raises(self):
        self.namespace['_execute_switches_job'] = Mock(side_effect=RuntimeError('unexpected'))
        with self.assertRaises(RuntimeError):
            self.namespace['_run_switches_job']('job1')
        self.assertFalse(has_app_context())


if __name__ == '__main__':
    unittest.main()
