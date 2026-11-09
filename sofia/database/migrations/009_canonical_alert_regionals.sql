\set ON_ERROR_STOP on

BEGIN;
SET LOCAL ROLE sofia_owner;

-- Match regional_access.normalize_regional_code; retain accents and REG_ prefix.
CREATE OR REPLACE FUNCTION sofia.normalize_regional_code(p_value text)
RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE
SET search_path = pg_catalog
AS $$
    SELECT regexp_replace(
        regexp_replace(
            replace(upper(regexp_replace(coalesce(p_value, ''),
                '^[[:space:]]+|[[:space:]]+$', '', 'g')), '&', ''),
            '[[:space:]-]+', '_', 'g'),
        '_+', '_', 'g');
$$;
REVOKE ALL ON FUNCTION sofia.normalize_regional_code(text) FROM PUBLIC;

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

    RETURN QUERY SELECT upsert_count, deactivate_count;
END;
$$;

CREATE OR REPLACE FUNCTION sofia.get_alert_summary(p_regional text DEFAULT NULL)
RETURNS TABLE (
    critical bigint, high bigint, medium bigint, attention bigint,
    important bigint, info bigint, success bigint, total bigint,
    last_observed_at timestamptz, last_observed_at_brasilia text
)
LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path = pg_catalog, sofia
AS $$
DECLARE
    regional_filter text := nullif(sofia.normalize_regional_code(p_regional), '');
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

CREATE OR REPLACE FUNCTION sofia.list_active_alerts(p_regional text DEFAULT NULL, p_limit integer DEFAULT 20)
RETURNS TABLE (
    severity text, title text, regional text, device text, quantity integer,
    occurred_at timestamptz, observed_at timestamptz
)
LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path = pg_catalog, sofia
AS $$
DECLARE
    regional_filter text := nullif(sofia.normalize_regional_code(p_regional), '');
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

-- Keep source_alert_id unchanged so the next sync updates the same alert.
-- Hash the canonical stored payload, using the same fields as sync_alert_snapshots.
UPDATE sofia.alert_snapshots
SET regional = nullif(sofia.normalize_regional_code(regional), ''),
    content_sha256 = encode(sha256(convert_to(concat_ws('|', source_alert_id,
        severity, title, sofia.normalize_regional_code(regional),
        coalesce(device, ''), quantity::text, coalesce(occurred_at::text, '')),
        'UTF8')), 'hex')
WHERE source = 'sentinel'
  AND regional IS DISTINCT FROM nullif(sofia.normalize_regional_code(regional), '');

RESET ROLE;
INSERT INTO sofia.schema_migrations (version, description)
VALUES (9, 'canonical regional codes for alert sync and reads')
ON CONFLICT (version) DO NOTHING;
COMMIT;
