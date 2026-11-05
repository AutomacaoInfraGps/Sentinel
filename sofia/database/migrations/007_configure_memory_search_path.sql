\set ON_ERROR_STOP on

BEGIN;

ALTER ROLE sofia_memory IN DATABASE sofia
    SET search_path = sofia_memory, pg_catalog;

INSERT INTO sofia.schema_migrations (version, description)
VALUES (7, 'configure isolated memory search path')
ON CONFLICT (version) DO NOTHING;

COMMIT;
