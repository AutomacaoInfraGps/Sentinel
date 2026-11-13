import json
from contextlib import redirect_stdout
import io
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from sofia.n8n.build_agent_workflow import AGENT, PREFIX, TOOL_TYPE, build_agent_workflow, main as build_cli
from sofia.n8n.build_readonly_workflows import build_workflows
from sofia.n8n_client import MAX_REPLY_LENGTH
from tests.unit.sofia_readonly_workflows_test import exports


class SofiaAgentWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.previous, inventory = exports()
        model = next(item for item in self.previous['nodes'] if item['name'] == 'Ollama Operacional')
        model.update(type='@n8n/n8n-nodes-langchain.lmChatOllama', typeVersion=1,
                     credentials={'ollamaApi': {'id': 'local-ollama'}})
        self.current, self.inventory = build_workflows(self.previous, inventory)
        self.snapshot = json.dumps([self.current, self.inventory, self.previous], sort_keys=True)
        self.result = build_agent_workflow(self.current, self.inventory, self.previous)

    def find(self, name):
        return next(item for item in self.result['nodes'] if item['name'] == name)

    def tool(self, resource):
        return next(item for item in self.result['nodes'] if item['name'] == {
            'alerts': 'Consultar alertas atuais', 'licenses': 'Consultar licencas',
            'inventory': 'Consultar inventario operacional',
        }[resource])

    def test_draft_does_not_overwrite_production_or_mutate_inputs(self):
        self.assertNotIn('id', self.result)
        self.assertFalse(self.result['active'])
        self.assertEqual(self.result['pinData'], {})
        self.assertNotEqual(self.find('Webhook')['parameters']['path'], self.current['nodes'][0]['parameters']['path'])
        self.assertEqual(self.snapshot, json.dumps([self.current, self.inventory, self.previous], sort_keys=True))
        for name in PREFIX[1:]:
            source = next(item for item in self.current['nodes'] if item['name'] == name)
            self.assertEqual(self.find(name)['parameters'], source['parameters'])
            self.assertEqual(self.find(name).get('credentials'), source.get('credentials'))

    def test_explicit_update_preserves_id_webhook_settings_and_credentials(self):
        original_hook = next(item for item in self.current['nodes'] if item['name'] == 'Webhook')
        original_hook['webhookId'] = 'existing-webhook-identity'
        self.current['settings'] = {'executionOrder': 'v1'}
        result = build_agent_workflow(self.current, self.inventory, self.previous,
                                      update_existing=True, expected_id=self.current['id'])
        self.assertEqual(result['id'], self.current['id'])
        self.assertEqual(result['name'], self.current['name'])
        self.assertFalse(result['active'])
        self.assertEqual(result['settings'], self.current['settings'])
        for name in [*PREFIX, 'Respond to Webhook']:
            source = next(item for item in self.current['nodes'] if item['name'] == name)
            target = next(item for item in result['nodes'] if item['name'] == name)
            self.assertEqual(target, source)
        memory = next(item for item in result['nodes'] if item['name'] == 'Memoria Agente Local')
        self.assertIn(':agent-v1', memory['parameters']['sessionKey'])
        self.assertNotIn(':agent-lab-v1', memory['parameters']['sessionKey'])
        self.assertEqual(memory['credentials'], self.find('Memoria Agente Local')['credentials'])

    def test_update_requires_matching_explicit_id(self):
        for expected in (None, '', 'wrong-id'):
            with self.assertRaises(ValueError):
                build_agent_workflow(self.current, self.inventory, self.previous,
                                     update_existing=True, expected_id=expected)

    def test_update_cli_keeps_exact_export_backup_and_does_not_overwrite_source(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            paths = [root / name for name in ('current.json', 'inventory.json', 'previous.json')]
            for path, value in zip(paths, (self.current, self.inventory, self.previous)):
                path.write_text(json.dumps(value, indent=2) + '\n', encoding='utf8')
            output = root / 'update.json'
            arguments = ['build', '--main', str(paths[0]), '--inventory', str(paths[1]),
                         '--previous', str(paths[2]), '--update-existing', '--expected-id', self.current['id'],
                         '--output', str(output)]
            for _ in range(2):
                with patch('sys.argv', arguments), redirect_stdout(io.StringIO()):
                    build_cli()
            backups = list(root.glob('sofia-main-before-agent-*.json'))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_bytes(), paths[0].read_bytes())
            self.assertEqual(json.loads(output.read_text(encoding='utf8'))['id'], self.current['id'])
            with patch('sys.argv', [*arguments[:-2], '--output', str(paths[0])]):
                with self.assertRaises(ValueError):
                    build_cli()

    def test_real_agent_memory_and_local_model_are_connected(self):
        agent = self.find(AGENT)
        self.assertEqual(agent['type'], '@n8n/n8n-nodes-langchain.agent')
        self.assertFalse(agent['parameters']['needsFallback'])
        self.assertTrue(agent['parameters']['options']['returnIntermediateSteps'])
        model = self.find('Ollama Local')
        self.assertEqual(model['parameters']['model'], 'qwen3:4b-instruct')
        self.assertEqual(model['credentials']['ollamaApi']['id'], 'local-ollama')
        self.assertEqual(self.find('Memoria Agente Local')['parameters']['tableName'], 'sofia_chat_history')
        self.assertIn(':agent-lab-v1', self.find('Memoria Agente Local')['parameters']['sessionKey'])
        for source, kind in [('Ollama Local', 'ai_languageModel'), ('Memoria Agente Local', 'ai_memory')]:
            self.assertEqual(self.result['connections'][source][kind][0][0]['node'], AGENT)
        self.assertFalse(any(item['name'] in {'Interpretar pedido', 'Validar plano', 'Guardar conversa'}
                             for item in self.result['nodes']))

    def test_tools_use_only_existing_scoped_workflow_with_server_injected_token(self):
        tools = [item for item in self.result['nodes'] if item['type'] == TOOL_TYPE]
        self.assertEqual(len(tools), 3)
        for item in tools:
            params = item['parameters']
            self.assertEqual(params['workflowId']['value'], self.inventory['id'])
            values = params['workflowInputs']['value']
            self.assertEqual(set(values), {'plan', 'sentinel_scope_token'})
            self.assertNotIn('$fromAI', values['sentinel_scope_token'])
            self.assertNotIn('sentinel_scope_token', values['plan'])
            self.assertEqual(self.result['connections'][item['name']]['ai_tool'][0][0]['node'], AGENT)
        self.assertIn('"alerts"', self.tool('alerts')['parameters']['workflowInputs']['value']['plan'])
        self.assertIn('"licenses"', self.tool('licenses')['parameters']['workflowInputs']['value']['plan'])

    def test_cancelled_branch_and_final_reply_contract_are_preserved(self):
        branches = self.result['connections']['Verificar cancelamento']['main']
        self.assertEqual(branches[0][0]['node'], 'Consulta cancelada')
        self.assertEqual(branches[1][0]['node'], AGENT)
        self.assertEqual(self.result['connections']['Consulta cancelada']['main'][0][0]['node'], 'Respond to Webhook')
        fields = self.find('Preparar resposta agente')['parameters']['assignments']['assignments']
        self.assertEqual([item['name'] for item in fields], ['reply'])
        self.assertIn(str(MAX_REPLY_LENGTH), fields[0]['value'])
        prompt = self.find(AGENT)['parameters']['options']['systemMessage']
        self.assertIn('RAG', prompt)
        self.assertIn('ainda nao possui ferramenta', prompt)
        self.assertNotIn('sentinel_scope_token', prompt)

    def test_bad_exports_and_external_model_override_are_rejected(self):
        with self.assertRaises(ValueError):
            build_agent_workflow(self.current, {**self.inventory, 'id': 'other'}, self.previous)
        with self.assertRaises(ValueError):
            build_agent_workflow({**self.current, 'pinData': {'Webhook': [{}]}}, self.inventory, self.previous)
        with self.assertRaises(ValueError):
            build_agent_workflow(self.current, self.inventory, self.previous, model='external-cloud')
        with self.assertRaises(ValueError):
            build_agent_workflow(self.current, self.inventory, {**self.previous, 'nodes': []})
        changed = build_agent_workflow(self.current, self.inventory, self.previous, model='qwen3:8b')
        self.assertEqual(next(item for item in changed['nodes'] if item['name'] == 'Ollama Local')['parameters']['model'], 'qwen3:8b')

    @unittest.skipUnless(shutil.which('node'), 'Node required for expression checks')
    def test_tool_and_session_expressions_reject_bad_values_without_repair(self):
        runner = r"""
const fs = require('node:fs');
const input = JSON.parse(fs.readFileSync(0,'utf8'));
try {
  const lookup = () => ({first:()=>({json:{body:input.body ?? {}}})});
  const fromAI = (key, description, type, fallback) => Object.hasOwn(input.params,key) ? input.params[key] : fallback;
  const result = new Function('$json','$','$fromAI','return (' + input.code.slice(3,-2) + ');')(input.data ?? {},lookup,fromAI);
  process.stdout.write(JSON.stringify({result}));
} catch (error) { process.stdout.write(JSON.stringify({error:error.message})); }
"""

        def evaluate(code, params=None, **extra):
            self.assertNotIn('}}', code[3:-2])
            result = subprocess.run(['node', '-e', runner], input=json.dumps({
                'code': code, 'params': params or {}, **extra}), capture_output=True,
                text=True, encoding='utf8', check=True)
            return json.loads(result.stdout)

        code = self.tool('licenses')['parameters']['workflowInputs']['value']['plan']
        result = evaluate(code, {'fields': ['days_remaining'], 'regional': 'Nutricar'})['result']
        self.assertEqual(result['resource'], 'licenses')
        self.assertEqual(result['fields'], ['days_remaining'])
        self.assertEqual(result['limit'], 20)
        # A regional name accidentally placed in search is not a textual product lookup.
        scoped = {'message': 'E da regional TLSV POA?',
                  'allowed_regionals': ['REG_NUTRICAR', 'REG_TLSV_POA']}
        result = evaluate(code, {'fields': ['days_remaining'], 'search': 'TLSV POA'}, body=scoped)['result']
        self.assertEqual(result['regional'], 'REG_TLSV_POA')
        self.assertEqual(result['search'], '')
        self.assertEqual(result['fields'], ['days_remaining'])
        self.assertEqual(result['status'], '')
        for name, canonical in [('Araras', 'REG_ARARAS'), ('Sao Jose', 'REG_SAO_JOSE')]:
            result = evaluate(code, {'search': name}, body={
                'message': 'E da regional ' + name + '?', 'allowed_regionals': [canonical]})['result']
            self.assertEqual(result['regional'], canonical)
            self.assertEqual(result['search'], '')
        result = evaluate(code, {'regional': 'TLSV POA', 'search': 'REG_TLSV_POA'}, body=scoped)['result']
        self.assertEqual(result['regional'], 'TLSV POA')
        self.assertEqual(result['search'], '')
        # Observed POA failure: both filters were omitted and only the first page was read.
        result = evaluate(code, {'fields': ['days_remaining']}, body=scoped)['result']
        self.assertEqual(result['regional'], 'REG_TLSV_POA')
        self.assertEqual(result['search'], '')
        self.assertEqual(result['fields'], ['days_remaining'])
        self.assertEqual(result['limit'], 20)
        for message in ('E da TLSV POA?', 'E da TLSV_POA?', 'Quando vence a licenca da REG_TLSV_POA?'):
            result = evaluate(code, {'fields': ['days_remaining']}, body={**scoped, 'message': message})['result']
            self.assertEqual(result['regional'], 'REG_TLSV_POA')
        result = evaluate(code, {'search': 'forticare'}, body=scoped)['result']
        self.assertEqual(result['regional'], 'REG_TLSV_POA')
        self.assertEqual(result['search'], 'forticare')
        # The matching catalog, including the entire message, must be unambiguous.
        for body in ({'message': 'Quantas licencas existem?', 'allowed_regionals': scoped['allowed_regionals']},
                     {'message': scoped['message'], 'allowed_regionals': ['REG_NUTRICAR']},
                     {'message': 'Compare Nutricar e TLSV POA.', 'allowed_regionals': scoped['allowed_regionals']},
                     {'message': 'E da TLSV POA?', 'allowed_regionals': ['REG_TLSV_POA', 'TLSV_POA']},
                     {'message': 'E da TLSV?', 'allowed_regionals': scoped['allowed_regionals']}):
            self.assertEqual(evaluate(code, {}, body=body)['result']['regional'], '')
        preserved = [
            ({'search': 'TLSV POA'}, {'message': scoped['message'], 'allowed_regionals': ['REG_NUTRICAR']}),
            ({'search': 'TLSV POA'}, {'message': 'Quantas licencas existem?', 'allowed_regionals': scoped['allowed_regionals']}),
            ({'search': 'TLSV POA'}, {'message': 'Compare Nutricar e TLSV POA.', 'allowed_regionals': scoped['allowed_regionals']}),
            ({'regional': 'REG_NUTRICAR', 'search': 'TLSV POA'}, scoped),
            ({'search': 'TLSV POA'}, {'message': scoped['message'], 'allowed_regionals': ['REG_TLSV_POA', 'TLSV_POA']}),
        ]
        for params, body in preserved:
            result = evaluate(code, params, body=body)['result']
            self.assertEqual(result['search'], params['search'])
            self.assertEqual(result['regional'], params.get('regional', ''))
        for params in [{'fields': 'days_remaining'}, {'status': 'offline'}, {'limit': 100},
                       {'offset': -1}, {'view': 'invalid'}, {'fields': ['unknown_field']}, {'fields': ['firmware']},
                       {'view': 'count', 'fields': ['days_remaining']}]:
            self.assertIn('error', evaluate(code, params))
        code = self.tool('inventory')['parameters']['workflowInputs']['value']['plan']
        self.assertIn('error', evaluate(code, {'resource': 'alerts'}))
        result = evaluate(code, {'resource': 'servers', 'search': 'TLSV POA', 'status': 'offline'}, body=scoped)['result']
        self.assertEqual((result['regional'], result['search'], result['status']), ('REG_TLSV_POA', '', 'offline'))
        code = self.tool('alerts')['parameters']['workflowInputs']['value']['plan']
        result = evaluate(code, {'search': 'switch'}, body=scoped)['result']
        self.assertEqual(result['search'], 'switch')
        self.assertEqual(result['regional'], 'REG_TLSV_POA')
        session = self.find('Memoria Agente Local')['parameters']['sessionKey']
        self.assertIn('error', evaluate(session, body={'conversation_id': 'untrusted-browser-id'}))
        self.assertEqual(evaluate(session, body={'conversation_id': 'a'*64})['result'], 'a'*64 + ':agent-lab-v1')
        system = self.find(AGENT)['parameters']['options']['systemMessage']
        result = evaluate(system, body={'user_context': {'display_name': 'Teste'},
                                      'sentinel_scope_token': 'SECRET', 'allowed_regionals': ['REG_CENTRO']})['result']
        self.assertNotIn('SECRET', result)
        self.assertIn('REG_CENTRO', result)
        output = self.find('Preparar resposta agente')['parameters']['assignments']['assignments'][0]['value']
        self.assertEqual(evaluate(output, data={'output': 'Tudo bem!'})['result'], 'Tudo bem!')
        self.assertIn('error', evaluate(output, data={'output': 'x'*(MAX_REPLY_LENGTH+1)}))
