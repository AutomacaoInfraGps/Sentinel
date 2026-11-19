\set ON_ERROR_STOP on
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
DO $$
BEGIN
    IF current_database() <> 'sentinel'
       OR inet_server_port() IS DISTINCT FROM 5433
       OR replace(current_setting('data_directory'), chr(92), '/') <> 'E:/Sentinel/PostgreSQL/data'
    THEN
        RAISE EXCEPTION 'Instancia divergente. Migracao cancelada.';
    END IF;
END
$$;
SET LOCAL ROLE sentinel_owner;
ALTER TABLE operacional.inventario_firmware_switches
    DROP CONSTRAINT inventario_firmware_switches_fonte_id_ordem_key;
ALTER TABLE operacional.inventario_firmware_switches
    ADD COLUMN presente_na_captura boolean NOT NULL DEFAULT true,
    ADD COLUMN atualizado_em timestamptz;
CREATE TABLE operacional.sincronizacoes_firmware_switches (
    fonte_id varchar(120) PRIMARY KEY REFERENCES operacional.fontes_firmware_switches(id) ON DELETE RESTRICT,
    capturado_em timestamptz NOT NULL,
    digest_carga varchar(64) NOT NULL CHECK (digest_carga ~ '^[0-9a-f]{64}$'),
    inventario_projetado_sha256 varchar(64) NOT NULL CHECK (inventario_projetado_sha256 ~ '^[0-9a-f]{64}$'),
    cache_status_sha256 varchar(64) NOT NULL CHECK (cache_status_sha256 ~ '^[0-9a-f]{64}$'),
    registros integer NOT NULL CHECK (registros > 0),
    sincronizado_em timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);
REVOKE ALL ON operacional.sincronizacoes_firmware_switches FROM PUBLIC, sentinel_reader, sentinel_api;
GRANT SELECT ON operacional.sincronizacoes_firmware_switches TO sentinel_firmware_reader;
GRANT SELECT, INSERT, UPDATE ON operacional.sincronizacoes_firmware_switches TO sentinel_collector;
GRANT UPDATE ON operacional.inventario_firmware_switches TO sentinel_collector;
COMMIT;
