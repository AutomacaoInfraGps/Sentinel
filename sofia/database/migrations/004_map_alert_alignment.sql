\set ON_ERROR_STOP on

BEGIN;

SET LOCAL ROLE sofia_owner;

ALTER TABLE sofia.alert_snapshots
    ADD COLUMN IF NOT EXISTS quantity integer NOT NULL DEFAULT 1;

ALTER TABLE sofia.alert_snapshots
    DROP CONSTRAINT IF EXISTS alert_snapshots_quantity_check;
ALTER TABLE sofia.alert_snapshots
    ADD CONSTRAINT alert_snapshots_quantity_check CHECK (quantity BETWEEN 1 AND 10000);

ALTER TABLE sofia.alert_snapshots
    DROP CONSTRAINT IF EXISTS alert_snapshots_severity_check;
ALTER TABLE sofia.alert_snapshots
    ADD CONSTRAINT alert_snapshots_severity_check CHECK (
        severity IN ('critical', 'high', 'medium', 'attention', 'important', 'success', 'info')
    );

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
            nullif(btrim(item ->> 'regional'), ''),
            nullif(btrim(item ->> 'device'), ''), quantity_value,
            nullif(btrim(item ->> 'occurred_at'), '')::timestamptz,
            p_observed_at, true,
            encode(sha256(convert_to(concat_ws('|', source_id, severity_value,
                title_value, coalesce(item ->> 'regional', ''),
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

    RETURN QUERY SELECT upsert_count, deactivate_count;
END;
$$;

DROP FUNCTION sofia.get_alert_summary(text);
CREATE FUNCTION sofia.get_alert_summary(p_regional text DEFAULT NULL)
RETURNS TABLE (
    critical bigint, high bigint, medium bigint, attention bigint,
    important bigint, info bigint, success bigint, total bigint,
    last_observed_at timestamptz, last_observed_at_brasilia text
)
LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path = pg_catalog, sofia
AS $$
DECLARE
    regional_filter text := nullif(btrim(p_regional), '');
BEGIN
    IF regional_filter IS NOT NULL AND length(regional_filter) > 120 THEN
        RAISE EXCEPTION 'regional exceeds the limit of 120 characters' USING ERRCODE = '22023';
    END IF;
    RETURN QUERY SELECT
        coalesce(sum(snapshot.quantity) FILTER (WHERE snapshot.severity = 'critical'), 0),
        coalesce(sum(snapshot.quantity) FILTER (WHERE snapshot.severity = 'high'), 0),
        coalesce(sum(snapshot.quantity) FILTER (WHERE snapshot.severity = 'medium'), 0),
        coalesce(sum(snapshot.quantity) FILTER (WHERE snapshot.severity = 'attention'), 0),
        coalesce(sum(snapshot.quantity) FILTER (WHERE snapshot.severity = 'important'), 0),
        coalesce(sum(snapshot.quantity) FILTER (WHERE snapshot.severity = 'info'), 0),
        coalesce(sum(snapshot.quantity) FILTER (WHERE snapshot.severity = 'success'), 0),
        coalesce(sum(snapshot.quantity), 0),
        max(snapshot.occurred_at),
        to_char(
            max(snapshot.occurred_at) AT TIME ZONE 'America/Sao_Paulo',
            'DD/MM/YYYY HH24:MI:SS'
        )
    FROM sofia.alert_snapshots AS snapshot
    WHERE snapshot.active AND (regional_filter IS NULL OR lower(snapshot.regional) = lower(regional_filter));
END;
$$;

DROP FUNCTION sofia.list_active_alerts(text, integer);
CREATE FUNCTION sofia.list_active_alerts(p_regional text DEFAULT NULL, p_limit integer DEFAULT 20)
RETURNS TABLE (
    severity text, title text, regional text, device text, quantity integer,
    occurred_at timestamptz, observed_at timestamptz
)
LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path = pg_catalog, sofia
AS $$
DECLARE
    regional_filter text := nullif(btrim(p_regional), '');
BEGIN
    IF regional_filter IS NOT NULL AND length(regional_filter) > 120 THEN
        RAISE EXCEPTION 'regional exceeds the limit of 120 characters' USING ERRCODE = '22023';
    END IF;
    IF p_limit IS NULL OR p_limit < 1 OR p_limit > 50 THEN
        RAISE EXCEPTION 'limit must be between 1 and 50' USING ERRCODE = '22023';
    END IF;
    RETURN QUERY SELECT snapshot.severity, snapshot.title, snapshot.regional,
        snapshot.device, snapshot.quantity, snapshot.occurred_at, snapshot.observed_at
    FROM sofia.alert_snapshots AS snapshot
    WHERE snapshot.active AND (regional_filter IS NULL OR lower(snapshot.regional) = lower(regional_filter))
    ORDER BY CASE snapshot.severity WHEN 'critical' THEN 1 WHEN 'high' THEN 2
        WHEN 'medium' THEN 3 WHEN 'attention' THEN 4 WHEN 'important' THEN 5
        WHEN 'info' THEN 6 ELSE 7 END,
        snapshot.occurred_at DESC NULLS LAST, snapshot.observed_at DESC
    LIMIT p_limit;
END;
$$;

RESET ROLE;

REVOKE ALL ON FUNCTION sofia.sync_alert_snapshots(jsonb, timestamptz) FROM PUBLIC;
REVOKE ALL ON FUNCTION sofia.get_alert_summary(text) FROM PUBLIC;
REVOKE ALL ON FUNCTION sofia.list_active_alerts(text, integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION sofia.sync_alert_snapshots(jsonb, timestamptz) TO sofia_runtime;
GRANT EXECUTE ON FUNCTION sofia.get_alert_summary(text) TO sofia_runtime;
GRANT EXECUTE ON FUNCTION sofia.list_active_alerts(text, integer) TO sofia_runtime;
REVOKE SELECT, INSERT, DELETE ON sofia.alert_snapshots FROM sofia_runtime;
REVOKE UPDATE ON sofia.alert_snapshots FROM sofia_runtime;
REVOKE UPDATE (
    severity, title, regional, device, occurred_at,
    observed_at, active, content_sha256
) ON sofia.alert_snapshots FROM sofia_runtime;

INSERT INTO sofia.schema_migrations (version, description)
VALUES (4, 'map_alert_alignment')
ON CONFLICT (version) DO NOTHING;

COMMIT;
