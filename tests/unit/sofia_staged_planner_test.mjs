import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp, writeFile, unlink, rmdir} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {spawnSync} from 'node:child_process';
import {contracts, parameterSchema, planInStages, resolvePlan} from '../manual/sofia_staged_planner.mjs';

const allowed = ['REG_CENTRO', 'REG_SUL'];
const route = {mode:'query', resource:'licenses', view:'list', context_mode:'continue'};
const previous = {mode:'query', resource:'licenses', regional:'REG_CENTRO', status:'expiring',
  search:'forticare', fields:['days_remaining'], view:'list'};
const empty = {regional:'', status:'', search:'', fields:[], inherit:[]};

test('new regional replaces old regional with explicit attribute inheritance', () => {
  const plan = resolvePlan(route, {...empty, regional:'REG_SUL', inherit:['fields']}, previous, allowed);
  assert.equal(plan.regional, 'REG_SUL');
  assert.equal(plan.status, '');
  assert.equal(plan.search, '');
  assert.deepEqual(plan.fields, ['days_remaining']);
  assert.equal(previous.regional, 'REG_CENTRO');
});

test('all severities clears only severity when category inheritance is explicit', () => {
  const plan = resolvePlan({...route, resource:'alerts'}, {...empty, inherit:['search']},
    {...previous, resource:'alerts', status:'high', search:'vpn', fields:[]}, allowed);
  assert.equal(plan.status, '');
  assert.equal(plan.search, 'vpn');
});

test('all regionals preserves only explicitly inherited constraints', () => {
  const plan = resolvePlan(route, {...empty, inherit:['status', 'fields']}, previous, allowed);
  assert.equal(plan.regional, '');
  assert.equal(plan.status, 'expiring');
  assert.deepEqual(plan.fields, ['days_remaining']);
});

test('independent requests do not inherit previous restrictions', () => {
  const plan = resolvePlan({...route, resource:'alerts', context_mode:'new'}, empty, previous, allowed);
  assert.equal(plan.regional, '');
  assert.equal(plan.search, '');
  assert.equal(plan.status, '');
  assert.throws(() => resolvePlan({...route, context_mode:'new'}, {...empty, inherit:['status']}, previous, allowed));
});

test('incompatible fields, states, regions and contradictory count are rejected', () => {
  const invalid = [
    [{...route, resource:'alerts'}, {...empty, fields:['firmware']}],
    [{...route, resource:'alerts'}, {...empty, status:'offline'}],
    [route, {...empty, regional:'REG_OTHER'}],
    [route, {...empty, regional:'REG_SUL', search:'Sul'}],
    [{...route, view:'count'}, {...empty, fields:['days_remaining']}],
    [route, {...empty, inherit:['status'], status:'valid'}],
    [route, {...empty, inherit:['status', 'status']}],
    [route, {...empty, fields:['name', 'name']}],
    [route, {...empty, resource:'servers'}],
  ];
  for (const [intent, params] of invalid) assert.throws(() => resolvePlan(intent, params, previous, allowed));
});

test('inheritance across resources checks compatibility and never copies search or fields', () => {
  const serverQuery = {...previous, resource:'servers', status:'offline'};
  const vpn = {...route, resource:'vpns'};
  assert.equal(resolvePlan(vpn, {...empty, inherit:['status']}, serverQuery, allowed).status, 'offline');
  assert.throws(() => resolvePlan(vpn, {...empty, inherit:['fields']}, serverQuery, allowed));
  assert.throws(() => resolvePlan(vpn, {...empty, inherit:['search']}, serverQuery, allowed));
  assert.throws(() => resolvePlan(route, {...empty, inherit:['status']}, serverQuery, allowed));
  assert.throws(() => resolvePlan(route, {...empty, inherit:['status']}, null, allowed));
});

test('each resource schema exposes only its own fields and status domain', () => {
  for (const resource of Object.keys(contracts)) {
    const schema = parameterSchema(resource, allowed);
    assert.deepEqual(schema.required, ['regional', 'status', 'search', 'fields', 'inherit']);
    assert.equal(schema.additionalProperties, false);
  }
  assert.equal(parameterSchema('alerts', allowed).properties.fields.items.enum.includes('firmware'), false);
  assert.equal(parameterSchema('licenses', allowed).properties.status.enum.includes('offline'), false);
  assert.equal(parameterSchema('licenses', allowed).properties.fields.items.enum.includes('days_remaining'), true);
});

test('new topic sends no prior query or historical assistant claims to parameter extraction', async () => {
  const requests = [];
  const output = await planInStages({baseConfig:{model:'local', options:{temperature:0}},
    message:'Mostre as ocorrencias atuais dos links.', allowedRegionals:allowed,
    context:{previous_query:previous, recent_messages:[
      {role:'ai', text:'SECRET_OLD_ANSWER'}, {role:'human', text:'Obrigado'},
    ]}, ask:async request => {
      requests.push(request);
      return requests.length === 1 ? {...route, resource:'alerts', context_mode:'new'}
        : {...empty, search:'link'};
    }});
  assert.equal(requests.length, 2);
  assert.equal(JSON.stringify(requests).includes('SECRET_OLD_ANSWER'), false);
  const input = JSON.parse(requests[1].messages[1].content);
  assert.equal(input.previous_query, null);
  assert.deepEqual(input.recent_user_messages, []);
  assert.equal(output.plan.search, 'link');
  assert.equal(output.trace.length, 2);
});

test('social classification produces conversation without parameter extraction', async () => {
  let calls = 0;
  const output = await planInStages({baseConfig:{}, message:'Como voce esta?',
    allowedRegionals:allowed, context:{previous_query:previous}, ask:async request => {
      calls++;
      if (calls === 1) return {mode:'chat', resource:'', view:'list', context_mode:'new'};
      assert.deepEqual(request.format.required, ['reply']);
      assert.equal(JSON.parse(request.messages[1].content).previous_query, undefined);
      return {reply:'Tudo bem!'};
    }});
  assert.equal(output.plan.mode, 'chat');
  assert.equal(output.plan.reply, 'Tudo bem!');
  assert.equal(calls, 2);
});

test('stage errors preserve raw trace and do not start a third correction call', async () => {
  let calls = 0;
  await assert.rejects(planInStages({baseConfig:{}, message:'Mostre licencas.', allowedRegionals:allowed,
    ask:async () => ++calls === 1 ? {...route, context_mode:'new'} : {...empty, status:'offline'},
  }), error => {
    assert.equal(error.stagedTrace.length, 2);
    assert.equal(error.stagedTrace[1].saida.status, 'offline');
    return true;
  });
  assert.equal(calls, 2);
});

test('manual evaluator scores all stages without sending expectations to the model', async () => {
  const folder = await mkdtemp(join(tmpdir(), 'sofia-staged-'));
  try {
    const workflow = join(folder, 'workflow.json');
    // Only the source workflow contract is needed to initialize the manual evaluator.
    const properties = {resource:{type:'string',enum:Object.keys(contracts)},
      fields:{type:'array', items:{type:'string'}}, status:{type:'string'}, search:{type:'string'}};
    const body = '={{ JSON.stringify(' + JSON.stringify({model:'old', format:{anyOf:[
      {properties:{query:{properties}}},
    ]}, messages:[{role:'system',content:''},{role:'user',content:'{}'}]}) + ') }}';
    await writeFile(workflow, JSON.stringify({nodes:[{name:'Interpretar pedido',parameters:{body}}]}));
    const runner = `
      import assert from 'node:assert/strict';
      import {pathToFileURL} from 'node:url';
      process.argv = ['node', process.argv[2], process.argv[3], '--staged-contract', '--model', 'local-test'];
      let calls = 0;
      globalThis.fetch = async (url, request) => {
        assert.equal(url, 'http://ollama:11434/api/chat');
        const body = JSON.parse(request.body);
        assert.equal(body.model, 'local-test');
        const input = JSON.parse(body.messages[1].content);
        assert.equal(Object.hasOwn(input, 'expected'), false);
        assert.equal(Object.hasOwn(input, 'erros'), false);
        calls++;
        const plan = body.format.required.includes('mode')
          ? {mode:'chat',resource:'',view:'list',context_mode:'new'} : {reply:'Resposta simulada'};
        return {ok:true,json:async()=>({done:true,done_reason:'stop',message:{content:JSON.stringify(plan)}})};
      };
      const logs = [];
      console.log = value => logs.push(JSON.parse(value));
      await import(pathToFileURL(process.argv[1]));
      assert.equal(calls, 40);
      assert.equal(logs.at(-1).casos, 20);
      assert.equal(logs.at(-1).falhas, 19);
      assert.equal(logs.filter(row => row.caso && row.etapas.length === 2).length, 20);
      process.exitCode = 0;
    `;
    const evaluator = new URL('../manual/sofia_planner_ollama_test.mjs', import.meta.url);
    const result = spawnSync(process.execPath, ['--input-type=module', '-',
      (await import('node:url')).fileURLToPath(evaluator), workflow], {input:runner, encoding:'utf8'});
    assert.equal(result.status, 0, result.stdout + result.stderr);
  } finally {
    await unlink(join(folder, 'workflow.json'));
    await rmdir(folder);
  }
});
