\set ON_ERROR_STOP on

BEGIN;

SET LOCAL ROLE sofia_owner;

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

        IF source_id = '' OR length(source_id) > 200 THEN
            RAISE EXCEPTION 'invalid alert id' USING ERRCODE = '22023';
        END IF;
        IF severity_value NOT IN ('critical', 'important', 'success', 'info') THEN
            RAISE EXCEPTION 'invalid alert severity' USING ERRCODE = '22023';
        END IF;
        IF title_value = '' OR length(title_value) > 300 THEN
            RAISE EXCEPTION 'invalid alert title' USING ERRCODE = '22023';
        END IF;

        INSERT INTO sofia.alert_snapshots (
            source,
            source_alert_id,
            severity,
            title,
            regional,
            device,
            occurred_at,
            observed_at,
            active,
            content_sha256
        )
        VALUES (
            'sentinel',
            source_id,
            severity_value,
            title_value,
            nullif(btrim(item ->> 'regional'), ''),
            nullif(btrim(item ->> 'device'), ''),
            nullif(btrim(item ->> 'occurred_at'), '')::timestamptz,
            p_observed_at,
            true,
            encode(
                sha256(
                    convert_to(
                        concat_ws(
                            '|',
                            source_id,
                            severity_value,
                            title_value,
                            coalesce(item ->> 'regional', ''),
                            coalesce(item ->> 'device', ''),
                            coalesce(item ->> 'occurred_at', '')
                        ),
                        'UTF8'
                    )
                ),
                'hex'
            )
        )
        ON CONFLICT (source, source_alert_id) DO UPDATE SET
            severity = EXCLUDED.severity,
            title = EXCLUDED.title,
            regional = EXCLUDED.regional,
            device = EXCLUDED.device,
            occurred_at = EXCLUDED.occurred_at,
            observed_at = EXCLUDED.observed_at,
            active = true,
            content_sha256 = EXCLUDED.content_sha256;

        GET DIAGNOSTICS changed = ROW_COUNT;
        upsert_count := upsert_count + changed;
    END LOOP;

    UPDATE sofia.alert_snapshots AS snapshot
    SET active = false,
        observed_at = p_observed_at
    WHERE snapshot.source = 'sentinel'
      AND snapshot.active
      AND NOT EXISTS (
          SELECT 1
          FROM jsonb_array_elements(p_alerts) AS current_alert
          WHERE btrim(current_alert ->> 'id') = snapshot.source_alert_id
      );
    GET DIAGNOSTICS deactivate_count = ROW_COUNT;

    RETURN QUERY SELECT upsert_count, deactivate_count;
END;
$$;

RESET ROLE;

REVOKE ALL ON FUNCTION sofia.sync_alert_snapshots(jsonb, timestamptz) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION sofia.sync_alert_snapshots(jsonb, timestamptz)
    TO sofia_runtime;

REVOKE INSERT ON sofia.alert_snapshots FROM sofia_runtime;
REVOKE UPDATE ON sofia.alert_snapshots FROM sofia_runtime;

INSERT INTO sofia.schema_migrations (version, description)
VALUES (2, 'alert_snapshot_sync')
ON CONFLICT (version) DO NOTHING;

COMMIT;
