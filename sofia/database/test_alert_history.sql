\set ON_ERROR_STOP on

-- Mandatory guard: this suite performs isolated synthetic syncs, then rolls back.
-- NEVER run against the production database.
SELECT current_database() LIKE 'sofia_history_test_%' AS safe_database \gset
\if :safe_database
\else
    \echo 'REFUSED: use a disposable database named sofia_history_test_*'
    \quit 3
\endif

BEGIN;
SET LOCAL ROLE sofia_owner;
TRUNCATE sofia.alert_events, sofia.alert_snapshots RESTART IDENTITY;
UPDATE sofia.alert_history_state SET last_snapshot_at = NULL,
    tracking_started_at = clock_timestamp() - interval '2 hours';
SET LOCAL ROLE sofia_runtime;

DO $$
DECLARE
    first_time timestamptz := clock_timestamp() - interval '1 hour';
    first_alert jsonb := '[{"id":"history-test-1","regional":"REG_REGIONAL BELO HORIZONTE","severity":"medium","title":"Aps offline","quantity":1}]';
    second_alert jsonb := '[{"id":"history-test-1","regional":"REG_REGIONAL BELO HORIZONTE","severity":"medium","title":"Aps offline","quantity":2}]';
    result jsonb;
    current_total bigint;
BEGIN
    PERFORM sofia.sync_alert_snapshots(first_alert, first_time);
    PERFORM sofia.sync_alert_snapshots(first_alert, first_time + interval '1 minute');
    result := sofia.get_alert_history('["REG_REGIONAL_BELO_HORIZONTE"]', first_time, first_time + interval '10 minutes');
    IF result #>> '{summary,opened}' <> '1' OR result ->> 'available' <> '1' THEN
        RAISE EXCEPTION 'Unchanged polls must not duplicate opening';
    END IF;
    PERFORM sofia.sync_alert_snapshots(second_alert, first_time + interval '2 minutes');
    PERFORM sofia.sync_alert_snapshots('[]', first_time + interval '3 minutes');
    PERFORM sofia.sync_alert_snapshots('[]', first_time + interval '4 minutes');
    -- Out of order replay cannot reopen a recovered alert.
    PERFORM sofia.sync_alert_snapshots(first_alert, first_time + interval '1 minute');
    SELECT total INTO current_total FROM sofia.get_alert_summary('REG_REGIONAL_BELO_HORIZONTE');
    IF current_total <> 0 THEN RAISE EXCEPTION 'Recovered alert must be absent from current state'; END IF;
    result := sofia.get_alert_history('["REG_REGIONAL_BELO_HORIZONTE"]', first_time, first_time + interval '10 minutes');
    IF result #>> '{summary,opened}' <> '1' OR result #>> '{summary,recovered}' <> '1'
       OR result #>> '{summary,changed}' <> '1' OR result ->> 'available' <> '3' THEN
        RAISE EXCEPTION 'Opening/change/recovery history incorrect';
    END IF;
    IF result #>> '{events,0,previous_quantity}' <> '2' OR result #>> '{events,0,quantity}' <> '0' THEN
        RAISE EXCEPTION 'Recovery must retain previous aggregate quantity';
    END IF;
    -- End is exclusive; the recovery at exactly the end must not be included.
    result := sofia.get_alert_history('["REG_REGIONAL_BELO_HORIZONTE"]', first_time, first_time + interval '3 minutes');
    IF result #>> '{summary,recovered}' <> '0' THEN RAISE EXCEPTION 'Period end must be exclusive'; END IF;
    -- Different/empty scopes must never see this regional's history.
    result := sofia.get_alert_history('["REG_PARA"]', first_time, first_time + interval '10 minutes');
    IF result ->> 'available' <> '0' THEN RAISE EXCEPTION 'Regional scope leaked'; END IF;
    result := sofia.get_alert_history('[]', first_time, first_time + interval '10 minutes');
    IF result ->> 'available' <> '0' THEN RAISE EXCEPTION 'Empty scope must fail closed'; END IF;
    result := sofia.get_alert_history('["REG_REGIONAL_BELO_HORIZONTE"]', first_time, first_time + interval '10 minutes', 'REG_PARA');
    IF result ->> 'available' <> '0' THEN RAISE EXCEPTION 'Regional filter escaped scope'; END IF;
    result := sofia.get_alert_history('["REG_REGIONAL_BELO_HORIZONTE"]', first_time, first_time + interval '10 minutes', NULL, NULL, 1);
    IF result ->> 'returned' <> '1' OR result ->> 'truncated' <> 'true' OR result ->> 'available' <> '3' THEN
        RAISE EXCEPTION 'Pagination metadata incorrect';
    END IF;
    -- A later reopening is a new event, unlike a repeated snapshot.
    PERFORM sofia.sync_alert_snapshots(first_alert, first_time + interval '5 minutes');
    result := sofia.get_alert_history('["REG_REGIONAL_BELO_HORIZONTE"]', first_time, first_time + interval '10 minutes', NULL, 'opened');
    IF result ->> 'available' <> '2' THEN RAISE EXCEPTION 'Reopening missing'; END IF;
    BEGIN
        PERFORM sofia.get_alert_history('["REG_PARA"]', first_time, first_time + interval '32 days');
        RAISE EXCEPTION 'Unbounded period accepted';
    EXCEPTION WHEN invalid_parameter_value THEN NULL;
    END;
    BEGIN
        PERFORM sofia.get_alert_history('[null]', first_time, first_time + interval '1 hour');
        RAISE EXCEPTION 'Invalid scope accepted';
    EXCEPTION WHEN invalid_parameter_value THEN NULL;
    END;
    IF has_table_privilege(current_user, 'sofia.alert_events', 'SELECT')
       OR has_table_privilege(current_user, 'sofia.alert_events', 'INSERT')
       OR has_table_privilege(current_user, 'sofia.alert_events', 'UPDATE')
       OR has_table_privilege(current_user, 'sofia.alert_events', 'DELETE') THEN
        RAISE EXCEPTION 'Runtime has direct history access';
    END IF;
    IF has_schema_privilege(current_user, 'sofia', 'CREATE') THEN
        RAISE EXCEPTION 'Runtime can create operational objects';
    END IF;
END;
$$;
ROLLBACK;
\echo 'History integration checks passed; synthetic changes rolled back.'
