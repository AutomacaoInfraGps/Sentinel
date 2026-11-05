\set ON_ERROR_STOP on

BEGIN;

CREATE SCHEMA IF NOT EXISTS sofia_memory AUTHORIZATION sofia_owner;
REVOKE ALL ON SCHEMA sofia_memory FROM PUBLIC;
GRANT USAGE, CREATE ON SCHEMA sofia_memory TO sofia_memory;

ALTER DEFAULT PRIVILEGES FOR ROLE sofia_memory IN SCHEMA sofia_memory
    REVOKE ALL ON TABLES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE sofia_memory IN SCHEMA sofia_memory
    REVOKE ALL ON SEQUENCES FROM PUBLIC;

INSERT INTO sofia.schema_migrations (version, description)
VALUES (6, 'isolated n8n chat memory schema')
ON CONFLICT (version) DO NOTHING;

COMMIT;
