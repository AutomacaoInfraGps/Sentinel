\set ON_ERROR_STOP on
BEGIN READ ONLY;

DO $$
DECLARE item record;
BEGIN
    FOR item IN SELECT * FROM (VALUES
        ('REG_REGIONAL BELO HORIZONTE', 'REG_REGIONAL_BELO_HORIZONTE'),
        ('REG_TLSV POA', 'REG_TLSV_POA'),
        ('REG_TRADE&TALENTOS', 'REG_TRADETALENTOS'),
        (' REG_CAMPINAS--02 ', 'REG_CAMPINAS_02'),
        ('REG_GLOBAL_SEGURANÇA', 'REG_GLOBAL_SEGURANÇA'),
        ('REG_GALAXIA', 'REG_GALAXIA')
    ) AS cases(input, expected)
    LOOP
        IF sofia.normalize_regional_code(item.input) IS DISTINCT FROM item.expected THEN
            RAISE EXCEPTION 'Regional normalization mismatch: %', item.input;
        END IF;
    END LOOP;
    IF EXISTS (
        SELECT 1 FROM sofia.alert_snapshots
        WHERE source = 'sentinel' AND regional IS DISTINCT FROM
            nullif(sofia.normalize_regional_code(regional), '')
    ) THEN
        RAISE EXCEPTION 'Non-canonical Sentinel snapshot regional codes remain';
    END IF;
END;
$$;

-- Run using the real read-only role, not just the database administrator.
SET LOCAL ROLE sofia_runtime;
SELECT * FROM sofia.list_active_alerts('REG_REGIONAL_BELO_HORIZONTE', 50);
SELECT * FROM sofia.get_alert_summary('REG_REGIONAL_BELO_HORIZONTE');
SELECT has_schema_privilege(current_user, 'sofia', 'CREATE') AS runtime_can_create,
       has_table_privilege(current_user, 'sofia.alert_snapshots', 'UPDATE') AS runtime_can_update;
ROLLBACK;
