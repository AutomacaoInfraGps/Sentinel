\set ON_ERROR_STOP on

BEGIN;

-- Apply only after the n8n memory node uses the isolated sofia_memory role.
REVOKE CREATE ON SCHEMA sofia FROM sofia_runtime;

INSERT INTO sofia.schema_migrations (version, description)
VALUES (7, 'revoke shared schema create from runtime')
ON CONFLICT (version) DO NOTHING;

COMMIT;
