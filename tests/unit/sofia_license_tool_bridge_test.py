import json
import os
import shutil
import subprocess
import unittest

from sofia.n8n.build_license_tool_bridge import BRIDGE_ID, build_bridge
from sofia.n8n.build_agent_workflow import _tool_plan
from tests.unit import sofia_agent_workflow_test as fixtures


class SofiaLicenseToolBridgeTests(unittest.TestCase):
    def setUp(self):
        fixture = fixtures.SofiaAgentWorkflowTests()
        fixture.setUp()
        self.current = fixture.result
        self.current['id'] = 'existing-main'
        self.original = json.dumps(self.current, sort_keys=True)
        self.bridge, self.update = build_bridge(self.current)

    def test_only_license_tool_changes_in_main(self):
        self.assertEqual(json.dumps(self.current, sort_keys=True), self.original)
        self.assertEqual(self.update['id'], self.current['id'])
        self.assertFalse(self.update['active'])
        for before, after in zip(self.current['nodes'], self.update['nodes']):
            if before['name'] != 'Consultar licencas':
                self.assertEqual(before, after)
            else:
                self.assertEqual(before['id'], after['id'])
                inputs = after['parameters']['workflowInputs']['value']
                self.assertEqual(inputs['sentinel_scope_token'], before['parameters']['workflowInputs']['value']['sentinel_scope_token'])
                self.assertNotIn('throw', inputs['plan'])
                self.assertNotIn('normalize', inputs['plan'])
                self.assertNotIn('$fromAI', inputs['request_context'])
                self.assertNotIn('REG_TLSV_POA', inputs['plan'])
                self.assertEqual(after['parameters']['workflowId']['value'], BRIDGE_ID)
        self.assertEqual(self.update['connections'], self.current['connections'])

    def test_invalid_input_never_reaches_authorized_bridge(self):
        self.assertFalse(self.bridge['active'])
        self.assertEqual(len(self.bridge['nodes']), 5)
        execute = next(node for node in self.bridge['nodes'] if node['type'].endswith('.executeWorkflow'))
        original = next(node for node in self.current['nodes'] if node['name'] == 'Consultar licencas')
        self.assertEqual(execute['parameters']['workflowId'], original['parameters']['workflowId'])
        branches = self.bridge['connections']['Argumentos validos']['main']
        self.assertEqual(branches[0][0]['node'], execute['name'])
        self.assertEqual(branches[1][0]['node'], 'Retornar erro de argumentos')
        self.assertFalse(any(node['type'].endswith(('.code', '.httpRequest', '.postgres', '.executeCommand')) for node in self.bridge['nodes']))
        self.assertEqual({node['type'] for node in self.bridge['nodes']}, {
            'n8n-nodes-base.executeWorkflowTrigger', 'n8n-nodes-base.set',
            'n8n-nodes-base.if', 'n8n-nodes-base.executeWorkflow'})

    @unittest.skipUnless(shutil.which('node'), 'Node required')
    def test_set_node_validation_and_expression_transport(self):
        plan = dict(mode='query', reply='', resource='licenses', regional='', status='', search='',
                    view='list', fields=['days_remaining'], limit=20, offset=0)
        context = dict(message='E da TLSV POA?', allowed_regionals=['REG_TLSV_POA', 'REG_NUTRICAR'])
        base = dict(plan=plan, request_context=context, sentinel_scope_token='private-token')
        cases = [base, {**base, 'plan': {**plan, 'search': 'TLSV POA'}},
                 {**base, 'plan': {**plan, 'search': 'forticare'}}]
        for changes in ({'offset': 0.000111111}, {'offset': -1}, {'limit': 51}, {'limit': '20'},
                        {'fields': 'days_remaining'}, {'fields': ['firmware']},
                        {'view': 'count'}, {'status': 'offline'}, {'resource': 'servers'},
                        {'mode': 'chat'}, {'extra': 'private-token'}):
            cases.append({**base, 'plan': {**plan, **changes}})
        cases.extend([{**base, 'plan': None}, {**base, 'request_context': None},
                      {**base, 'sentinel_scope_token': ''}])
        tool = next(node for node in self.update['nodes'] if node['name'] == 'Consultar licencas')
        runner = r"""
const fs=require('fs');
const input=JSON.parse(fs.readFileSync(0,'utf8'));
const exprContext={
  $fromAI:(key,desc,type,fallback)=>Object.hasOwn(input.params,key)?input.params[key]:fallback,
  $:()=>({first:()=>({json:{body:input.body}})})
};
const evaluate=process.env.SOFIA_N8N_WORKFLOW_PATH
  ? code=>new (require(process.env.SOFIA_N8N_WORKFLOW_PATH).Expression)('America/Sao_Paulo').resolveSimpleParameterValue(code,exprContext)
  : code=>new Function('$fromAI','$','return ('+code.slice(3,-2)+');')(exprContext.$fromAI,exprContext.$);
const results=input.cases.map(value=>{
  if(process.env.SOFIA_N8N_WORKFLOW_PATH){
    return new (require(process.env.SOFIA_N8N_WORKFLOW_PATH).Expression)('America/Sao_Paulo').resolveSimpleParameterValue(input.validationExpression, {$json:value});
  }
  return new Function('$json','return ('+input.validationExpression.slice(3,-2)+');')(value);
});
const legacy=process.env.SOFIA_N8N_WORKFLOW_PATH ? evaluate(input.legacyExpression) : null;
console.log(JSON.stringify({results, transport:evaluate(input.expression), legacyUndefined:legacy===undefined}));
"""
        result = subprocess.run(['node', '-e', runner], input=json.dumps({
            'validationExpression': next(node for node in self.bridge['nodes'] if node['name']=='Validar argumentos')['parameters']['assignments']['assignments'][0]['value'], 'cases': cases,
            'expression': tool['parameters']['workflowInputs']['value']['plan'],
            'legacyExpression': _tool_plan('licenses'),
            'params': {'fields': ['days_remaining'], 'offset': 0.000111111}, 'body': context}),
            capture_output=True, text=True, encoding='utf-8', check=True)
        parsed = json.loads(result.stdout)
        self.assertEqual(parsed['transport']['offset'], 0.000111111)
        if os.environ.get('SOFIA_N8N_WORKFLOW_PATH'):
            self.assertTrue(parsed['legacyUndefined'])
        self.assertEqual(parsed['results'][0]['plan']['regional'], 'REG_TLSV_POA')
        self.assertEqual(parsed['results'][1]['plan']['search'], '')
        self.assertEqual(parsed['results'][2]['plan']['search'], 'forticare')
        for value in parsed['results'][3:]:
            self.assertFalse(value['valid'])
            self.assertFalse(value['response']['success'])
            self.assertEqual(value['response']['error_code'], 'INVALID_TOOL_ARGUMENTS')
            self.assertNotIn('sentinel_scope_token', value)
            self.assertNotIn('private-token', json.dumps(value))


if __name__ == '__main__':
    unittest.main()
