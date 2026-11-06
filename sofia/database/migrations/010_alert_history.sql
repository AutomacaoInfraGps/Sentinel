\set ON_ERROR_STOP on

BEGIN;
SET LOCAL ROLE sofia_owner;

-- Serializes migration against the sync function being replaced below.
LOCK TABLE sofia.alert_snapshots IN SHARE ROW EXCLUSIVE MODE;

CREATE TABLE IF NOT EXISTS sofia.alert_history_state (
    source text PRIMARY KEY CHECK (source = 'sentinel'),
    tracking_started_at timestamptz NOT NULL,
    last_snapshot_at timestamptz
);
INSERT INTO sofia.alert_history_state (source, tracking_started_at, last_snapshot_at)
SELECT 'sentinel', clock_timestamp(), max(observed_at)
FROM sofia.alert_snapshots WHERE source = 'sentinel'
ON CONFLICT (source) DO NOTHING;

CREATE TABLE IF NOT EXISTS sofia.alert_events (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    snapshot_id bigint NOT NULL REFERENCES sofia.alert_snapshots(id),
    event_type text NOT NULL CHECK (event_type IN ('baseline', 'opened', 'recovered', 'changed')),
    observed_at timestamptz NOT NULL,
    recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    regional text CHECK (regional IS NULL OR length(regional) <= 120),
    severity text NOT NULL CHECK (severity IN (
        'critical', 'high', 'medium', 'attention', 'important', 'info', 'success'
    )),
    title text NOT NULL CHECK (length(title) BETWEEN 1 AND 300),
    device text CHECK (device IS NULL OR length(device) <= 200),
    previous_quantity integer CHECK (previous_quantity BETWEEN 0 AND 10000),
    quantity integer NOT NULL CHECK (quantity BETWEEN 0 AND 10000)
);
CREATE INDEX IF NOT EXISTS alert_events_regional_time_idx
    ON sofia.alert_events (regional, observed_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS alert_events_time_idx
    ON sofia.alert_events (observed_at DESC, id DESC);

-- Existing inactive snapshots are NOT historical evidence of recovery time.
-- Baselines are explicit and never counted as newly opened incidents.
INSERT INTO sofia.alert_events (
    snapshot_id, event_type, observed_at, regional, severity, title, device, quantity
)
SELECT snapshot.id, 'baseline', state.tracking_started_at,
    snapshot.regional, snapshot.severity, snapshot.title, snapshot.device, snapshot.quantity
FROM sofia.alert_snapshots snapshot
JOIN sofia.alert_history_state state ON state.source = snapshot.source
WHERE snapshot.source = 'sentinel' AND snapshot.active
  AND NOT EXISTS (SELECT 1 FROM sofia.alert_events event WHERE event.snapshot_id = snapshot.id);

CREATE OR REPLACE FUNCTION sofia.record_alert_transition()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, sofia
AS $$
DECLARE
    transition text;
    old_quantity integer;
BEGIN
    IF NEW.source <> 'sentinel' THEN RETURN NEW; END IF;
    IF TG_OP = 'INSERT' THEN
        IF NOT NEW.active THEN RETURN NEW; END IF;
        transition := 'opened';
        old_quantity := 0;
    ELSE
        IF NOT OLD.active AND NEW.active THEN
            transition := 'opened';
            old_quantity := 0;
        ELSIF OLD.active AND NOT NEW.active THEN
            transition := 'recovered';
            old_quantity := OLD.quantity;
        ELSIF NEW.active AND (
            NEW.quantity IS DISTINCT FROM OLD.quantity OR
            NEW.severity IS DISTINCT FROM OLD.severity OR
            NEW.title IS DISTINCT FROM OLD.title OR
            NEW.device IS DISTINCT FROM OLD.device OR
            NEW.regional IS DISTINCT FROM OLD.regional
        ) THEN
            transition := 'changed';
            old_quantity := OLD.quantity;
        ELSE
            RETURN NEW;
        END IF;
    END IF;
    INSERT INTO sofia.alert_events (
        snapshot_id, event_type, observed_at, regional, severity, title,
        device, previous_quantity, quantity
    ) VALUES (
        NEW.id, transition, NEW.observed_at, NEW.regional, NEW.severity, NEW.title,
        NEW.device, old_quantity, CASE WHEN NEW.active THEN NEW.quantity ELSE 0 END
    );
    RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION sofia.record_alert_transition() FROM PUBLIC;
DROP TRIGGER IF EXISTS record_alert_transition ON sofia.alert_snapshots;
CREATE TRIGGER record_alert_transition
    AFTER INSERT OR UPDATE ON sofia.alert_snapshots
    FOR EACH ROW EXECUTE FUNCTION sofia.record_alert_transition();

CREATE OR REPLACE FUNCTION sofia.sync_alert_snapshots(
    p_alerts jsonb,
    p_observed_at timestamptz DEFAULT clock_timestamp()
)
RETURNS TABLE (upserted integer, deactivated integer)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, sofia
AS $$
DECLARE
    item jsonb;
    previous_snapshot_at timestamptz;
    source_id text;
    severity_value text;
    title_value text;
    quantity_value integer;
    changed integer;
    upsert_count integer := 0;
    deactivate_count integer := 0;
BEGIN
    IF p_alerts IS NULL OR jsonb_typeof(p_alerts) <> 'array' THEN
        RAISE EXCEPTION 'alerts must be a JSON array' USING ERRCODE = '22023';
    END IF;
    IF jsonb_array_length(p_alerts) > 100 THEN
        RAISE EXCEPTION 'alerts exceeds the limit of 100 items' USING ERRCODE = '22023';
    END IF;

    IF p_observed_at IS NULL OR NOT isfinite(p_observed_at)
       OR p_observed_at > clock_timestamp() + interval '5 minutes' THEN
        RAISE EXCEPTION 'invalid snapshot time' USING ERRCODE = '22023';
    END IF;
    -- One complete snapshot at a time. A late retry must never reopen an alert.
    SELECT last_snapshot_at INTO previous_snapshot_at
    FROM sofia.alert_history_state WHERE source = 'sentinel' FOR UPDATE;
    IF p_observed_at <= previous_snapshot_at THEN
        RETURN QUERY SELECT 0, 0;
        RETURN;
    END IF;
    IF EXISTS (
        SELECT 1 FROM jsonb_array_elements(p_alerts) value
        GROUP BY btrim(value ->> 'id') HAVING count(*) > 1
    ) THEN
        RAISE EXCEPTION 'duplicate alert id in snapshot' USING ERRCODE = '22023';
    END IF;

    FOR item IN SELECT value FROM jsonb_array_elements(p_alerts)
    LOOP
        IF jsonb_typeof(item) <> 'object' THEN
            RAISE EXCEPTION 'each alert must be a JSON object' USING ERRCODE = '22023';
        END IF;

        source_id := btrim(coalesce(item ->> 'id', ''));
        severity_value := lower(btrim(coalesce(item ->> 'severity', '')));
        title_value := btrim(coalesce(item ->> 'title', ''));
        BEGIN
            quantity_value := coalesce(nullif(btrim(item ->> 'quantity'), '')::integer, 1);
        EXCEPTION WHEN invalid_text_representation THEN
            RAISE EXCEPTION 'invalid alert quantity' USING ERRCODE = '22023';
        END;

        IF source_id = '' OR length(source_id) > 200 THEN
            RAISE EXCEPTION 'invalid alert id' USING ERRCODE = '22023';
        END IF;
        IF severity_value NOT IN ('critical', 'high', 'medium', 'attention', 'important', 'success', 'info') THEN
            RAISE EXCEPTION 'invalid alert severity' USING ERRCODE = '22023';
        END IF;
        IF title_value = '' OR length(title_value) > 300 THEN
            RAISE EXCEPTION 'invalid alert title' USING ERRCODE = '22023';
        END IF;
        IF quantity_value < 1 OR quantity_value > 10000 THEN
            RAISE EXCEPTION 'invalid alert quantity' USING ERRCODE = '22023';
        END IF;

        INSERT INTO sofia.alert_snapshots (
            source, source_alert_id, severity, title, regional, device,
            quantity, occurred_at, observed_at, active, content_sha256
        )
        VALUES (
            'sentinel', source_id, severity_value, title_value,
            nullif(sofia.normalize_regional_code(item ->> 'regional'), ''),
            nullif(btrim(item ->> 'device'), ''), quantity_value,
            nullif(btrim(item ->> 'occurred_at'), '')::timestamptz,
            p_observed_at, true,
            encode(sha256(convert_to(concat_ws('|', source_id, severity_value,
                title_value, sofia.normalize_regional_code(item ->> 'regional'),
                coalesce(item ->> 'device', ''), quantity_value::text,
                coalesce(item ->> 'occurred_at', '')), 'UTF8')), 'hex')
        )
        ON CONFLICT (source, source_alert_id) DO UPDATE SET
            severity = EXCLUDED.severity,
            title = EXCLUDED.title,
            regional = EXCLUDED.regional,
            device = EXCLUDED.device,
            quantity = EXCLUDED.quantity,
            occurred_at = EXCLUDED.occurred_at,
            observed_at = EXCLUDED.observed_at,
            active = true,
            content_sha256 = EXCLUDED.content_sha256;

        GET DIAGNOSTICS changed = ROW_COUNT;
        upsert_count := upsert_count + changed;
    END LOOP;

    UPDATE sofia.alert_snapshots AS snapshot
    SET active = false, observed_at = p_observed_at
    WHERE snapshot.source = 'sentinel' AND snapshot.active
      AND NOT EXISTS (
          SELECT 1 FROM jsonb_array_elements(p_alerts) AS current_alert
          WHERE btrim(current_alert ->> 'id') = snapshot.source_alert_id
      );
    GET DIAGNOSTICS deactivate_count = ROW_COUNT;

    UPDATE sofia.alert_history_state SET last_snapshot_at = p_observed_at
    WHERE source = 'sentinel';
    RETURN QUERY SELECT upsert_count, deactivate_count;
END;
$$;

CREATE OR REPLACE FUNCTION sofia.get_alert_history(
    p_allowed_regionals jsonb,
    p_start_at timestamptz,
    p_end_at timestamptz,
    p_regional text DEFAULT NULL,
    p_event_type text DEFAULT NULL,
    p_limit integer DEFAULT 20
)
RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path = pg_catalog, sofia
AS $$
DECLARE
    regional_filter text := nullif(sofia.normalize_regional_code(p_regional), '');
    event_filter text := nullif(btrim(p_event_type), '');
    result jsonb;
BEGIN
    IF p_allowed_regionals IS NULL OR jsonb_typeof(p_allowed_regionals) <> 'array' THEN
        RAISE EXCEPTION 'authorized regionals must be an array' USING ERRCODE = '22023';
    END IF;
    IF jsonb_array_length(p_allowed_regionals) > 200 OR EXISTS (
        SELECT 1 FROM jsonb_array_elements(p_allowed_regionals) value
        WHERE jsonb_typeof(value) <> 'string'
           OR length(sofia.normalize_regional_code(value #>> '{}')) NOT BETWEEN 1 AND 120
    ) THEN
        RAISE EXCEPTION 'invalid authorized regionals' USING ERRCODE = '22023';
    END IF;
    IF p_start_at IS NULL OR p_end_at IS NULL OR NOT isfinite(p_start_at)
       OR NOT isfinite(p_end_at) OR p_start_at >= p_end_at
       OR p_end_at - p_start_at > interval '31 days' THEN
        RAISE EXCEPTION 'history requires a valid period up to 31 days' USING ERRCODE = '22023';
    END IF;
    IF p_limit IS NULL OR p_limit NOT BETWEEN 1 AND 50
       OR (regional_filter IS NOT NULL AND length(regional_filter) > 120)
       OR (event_filter IS NOT NULL AND event_filter NOT IN ('baseline', 'opened', 'recovered', 'changed')) THEN
        RAISE EXCEPTION 'invalid history filter or limit' USING ERRCODE = '22023';
    END IF;

    WITH allowed AS (
        SELECT DISTINCT sofia.normalize_regional_code(value) AS regional
        FROM jsonb_array_elements_text(p_allowed_regionals)
    ), matching AS MATERIALIZED (
        SELECT event.id, event.event_type, event.observed_at, event.regional,
            event.severity, event.title, event.device, event.previous_quantity, event.quantity
        FROM sofia.alert_events event JOIN allowed USING (regional)
        WHERE event.observed_at >= p_start_at AND event.observed_at < p_end_at
          AND (regional_filter IS NULL OR event.regional = regional_filter)
          AND (CASE WHEN event_filter IS NULL THEN event.event_type <> 'baseline'
                    ELSE event.event_type = event_filter END)
    ), limited AS (
        SELECT * FROM matching ORDER BY observed_at DESC, id DESC LIMIT p_limit
    )
    SELECT jsonb_build_object(
        'source', 'Sentinel', 'mode', 'history', 'time_basis', 'observed_at',
        'period', jsonb_build_object('start_at', p_start_at, 'end_at', p_end_at),
        'tracking_started_at', state.tracking_started_at,
        'period_starts_before_tracking', p_start_at < state.tracking_started_at,
        'last_snapshot_at', state.last_snapshot_at,
        'snapshot_fresh', coalesce(state.last_snapshot_at >= statement_timestamp() - interval '5 minutes', false),
        'summary', (SELECT jsonb_build_object(
            'events', count(*),
            'opened', count(*) FILTER (WHERE event_type = 'opened'),
            'recovered', count(*) FILTER (WHERE event_type = 'recovered'),
            'changed', count(*) FILTER (WHERE event_type = 'changed'),
            'baseline', count(*) FILTER (WHERE event_type = 'baseline')
        ) FROM matching),
        'events', coalesce((SELECT jsonb_agg(to_jsonb(limited) ORDER BY observed_at DESC, id DESC) FROM limited), '[]'::jsonb),
        'returned', (SELECT count(*) FROM limited),
        'available', (SELECT count(*) FROM matching),
        'truncated', (SELECT count(*) > p_limit FROM matching)
    ) INTO result FROM sofia.alert_history_state state WHERE state.source = 'sentinel';
    RETURN result;
END;
$$;

REVOKE ALL ON TABLE sofia.alert_events, sofia.alert_history_state FROM PUBLIC, sofia_runtime;
REVOKE ALL ON SEQUENCE sofia.alert_events_id_seq FROM PUBLIC, sofia_runtime;
REVOKE ALL ON FUNCTION sofia.get_alert_history(jsonb, timestamptz, timestamptz, text, text, integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION sofia.get_alert_history(jsonb, timestamptz, timestamptz, text, text, integer) TO sofia_runtime;

INSERT INTO sofia.schema_migrations (version, description)
VALUES (10, 'observed alert transitions and scoped history reads')
ON CONFLICT (version) DO NOTHING;
RESET ROLE;
COMMIT;
