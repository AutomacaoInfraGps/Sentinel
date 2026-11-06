\set ON_ERROR_STOP on
BEGIN READ ONLY;
SELECT version, description FROM sofia.schema_migrations WHERE version = 10;
SELECT source, tracking_started_at, last_snapshot_at FROM sofia.alert_history_state;
SELECT event_type, count(*) AS events FROM sofia.alert_events GROUP BY event_type ORDER BY event_type;
SET LOCAL ROLE sofia_runtime;
SELECT sofia.get_alert_history(
    '["REG_PARA"]'::jsonb, statement_timestamp() - interval '24 hours', statement_timestamp(),
    'REG_PARA', NULL, 20
) AS history;
SELECT has_table_privilege(current_user, 'sofia.alert_events', 'SELECT') AS direct_read,
    has_table_privilege(current_user, 'sofia.alert_events', 'INSERT') AS direct_insert,
    has_table_privilege(current_user, 'sofia.alert_events', 'UPDATE') AS direct_update,
    has_table_privilege(current_user, 'sofia.alert_events', 'DELETE') AS direct_delete,
    has_schema_privilege(current_user, 'sofia', 'CREATE') AS schema_create;
ROLLBACK;
