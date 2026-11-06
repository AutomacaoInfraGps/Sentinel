// SQL integration tests using a disposable in-memory PostgreSQL (PGlite).
// Development dependency only; no production database or network is accessed.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const { PGlite } = await import(process.env.PGLITE_MODULE || '@electric-sql/pglite');
const db = new PGlite();
const migration = async name => (await fs.readFile(
  path.join(root, 'sofia/database/migrations', name), 'utf8'
)).split(/\r?\n/).filter(line => !line.startsWith('\\')).join('\n');

try {
  await db.exec('CREATE ROLE sofia_owner NOLOGIN; CREATE ROLE sofia_runtime LOGIN;');
  for (const name of ['001_read_only_foundation.sql', '002_alert_snapshot_sync.sql',
    '003_alert_read_api.sql', '004_map_alert_alignment.sql', '009_canonical_alert_regionals.sql']) {
    await db.exec(await migration(name));
  }
  const active = {id:'baseline-active', regional:'REG_PARA', severity:'medium', title:'Links offline', quantity:1};
  const inactive = {...active, id:'baseline-inactive'};
  await db.query("SELECT * FROM sofia.sync_alert_snapshots($1::jsonb, clock_timestamp() - interval '10 minutes')", [JSON.stringify([active, inactive])]);
  await db.query("SELECT * FROM sofia.sync_alert_snapshots($1::jsonb, clock_timestamp() - interval '9 minutes')", [JSON.stringify([active])]);
  await db.exec(await migration('010_alert_history.sql'));

  await db.exec('SET ROLE sofia_runtime');
  const query = "SELECT sofia.get_alert_history('[\"REG_PARA\"]', statement_timestamp() - interval '1 day', statement_timestamp() + interval '1 minute', NULL, $1) AS history";
  let result = (await db.query(query, [null])).rows[0].history;
  assert.equal(result.available, 0, 'Existing snapshots must not become synthetic openings/recoveries');
  assert.equal(result.period_starts_before_tracking, true);
  result = (await db.query(query, ['baseline'])).rows[0].history;
  assert.equal(result.available, 1, 'Only preexisting active snapshots become baselines');
  await db.exec('RESET ROLE');
  await db.exec(await migration('010_alert_history.sql'));
  const counts = await db.query('SELECT count(*)::integer AS count FROM sofia.alert_events');
  assert.equal(counts.rows[0].count, 1, 'Reapplying migration must preserve history without duplicate baselines');

  let tests = await fs.readFile(path.join(root, 'sofia/database/test_alert_history.sql'), 'utf8');
  // The psql database-name guard is replaced by this engine's in-memory isolation.
  tests = tests.slice(tests.indexOf('\nBEGIN;')).split(/\r?\n/)
    .filter(line => !line.startsWith('\\')).join('\n');
  await db.exec(tests);
  const workflow = JSON.parse(await fs.readFile(path.join(root,
    'sofia/n8n/consultar_historico_alertas.json'), 'utf8'));
  assert.equal(workflow.active, false);
  const sqlNode = workflow.nodes.find(node => node.type === 'n8n-nodes-base.postgres');
  assert.equal(sqlNode.credentials, undefined, 'Export must not include credential identities');
  const end = new Date().toISOString();
  const start = new Date(Date.now() - 86400000).toISOString();
  await db.exec('SET ROLE sofia_runtime');
  const toolResult = await db.query(sqlNode.parameters.query, [
    '["REG_PARA"]', start, end, "' OR 1=1 --", '', 20,
  ]);
  assert.equal(toolResult.rows[0].context.available, 0, 'Regional input must remain a query parameter');
  await assert.rejects(db.query(sqlNode.parameters.query, [
    '["REG_PARA"]', '2026-11-06T10:00:00', end, '', '', 20,
  ]), /valid period/, 'Tool must reject ambiguous timestamps without a timezone');
  await db.exec('RESET ROLE');
  console.log('PASS: baseline, no retroactive recovery, idempotent migration, opening, change, recovery, reopening, duplicate polls, out-of-order sync, period bounds, pagination, scope isolation, restricted privileges.');
} finally {
  await db.close();
}
