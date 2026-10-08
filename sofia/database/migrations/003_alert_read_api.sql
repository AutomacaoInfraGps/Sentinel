\set ON_ERROR_STOP on

BEGIN;

SET LOCAL ROLE sofia_owner;

CREATE OR REPLACE FUNCTION sofia.get_alert_summary(
    p_regional text DEFAULT NULL
)
RETURNS TABLE (
    critical bigint,
    important bigint,
    info bigint,
    success bigint,
    total bigint,
    last_observed_at timestamptz
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, sofia
AS $$
DECLARE
    regional_filter text := nullif(btrim(p_regional), '');
BEGIN
    IF regional_filter IS NOT NULL AND length(regional_filter) > 120 THEN
        RAISE EXCEPTION 'regional exceeds the limit of 120 characters'
            USING ERRCODE = '22023';
    END IF;

    RETURN QUERY
    SELECT
        count(*) FILTER (WHERE snapshot.severity = 'critical'),
        count(*) FILTER (WHERE snapshot.severity = 'important'),
        count(*) FILTER (WHERE snapshot.severity = 'info'),
        count(*) FILTER (WHERE snapshot.severity = 'success'),
        count(*),
        max(snapshot.observed_at)
    FROM sofia.alert_snapshots AS snapshot
    WHERE snapshot.active
      AND (
          regional_filter IS NULL
          OR lower(snapshot.regional) = lower(regional_filter)
      );
END;
$$;

CREATE OR REPLACE FUNCTION sofia.list_active_alerts(
    p_regional text DEFAULT NULL,
    p_limit integer DEFAULT 20
)
RETURNS TABLE (
    severity text,
    title text,
    regional text,
    device text,
    occurred_at timestamptz,
    observed_at timestamptz
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, sofia
AS $$
DECLARE
    regional_filter text := nullif(btrim(p_regional), '');
BEGIN
    IF regional_filter IS NOT NULL AND length(regional_filter) > 120 THEN
        RAISE EXCEPTION 'regional exceeds the limit of 120 characters'
            USING ERRCODE = '22023';
    END IF;
    IF p_limit IS NULL OR p_limit < 1 OR p_limit > 50 THEN
        RAISE EXCEPTION 'limit must be between 1 and 50'
            USING ERRCODE = '22023';
    END IF;

    RETURN QUERY
    SELECT
        snapshot.severity,
        snapshot.title,
        snapshot.regional,
        snapshot.device,
        snapshot.occurred_at,
        snapshot.observed_at
    FROM sofia.alert_snapshots AS snapshot
    WHERE snapshot.active
      AND (
          regional_filter IS NULL
          OR lower(snapshot.regional) = lower(regional_filter)
      )
    ORDER BY
        CASE snapshot.severity
            WHEN 'critical' THEN 1
            WHEN 'important' THEN 2
            WHEN 'info' THEN 3
            ELSE 4
        END,
        snapshot.occurred_at DESC NULLS LAST,
        snapshot.observed_at DESC
    LIMIT p_limit;
END;
$$;

RESET ROLE;

REVOKE ALL ON FUNCTION sofia.get_alert_summary(text) FROM PUBLIC;
REVOKE ALL ON FUNCTION sofia.list_active_alerts(text, integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION sofia.get_alert_summary(text) TO sofia_runtime;
GRANT EXECUTE ON FUNCTION sofia.list_active_alerts(text, integer) TO sofia_runtime;

REVOKE SELECT ON sofia.alert_snapshots FROM sofia_runtime;

INSERT INTO sofia.schema_migrations (version, description)
VALUES (3, 'alert_read_api')
ON CONFLICT (version) DO NOTHING;

COMMIT;
