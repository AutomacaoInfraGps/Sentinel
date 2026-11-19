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
ALTER TABLE operacional.recebimentos_radios_unifi
    ADD COLUMN presente_na_captura boolean NOT NULL DEFAULT true,
    ADD COLUMN atualizado_em timestamptz;
ALTER TABLE operacional.configuracoes_radios_unifi
    ADD COLUMN presente_na_captura boolean NOT NULL DEFAULT true,
    ADD COLUMN atualizado_em timestamptz;
ALTER TABLE operacional.estatisticas_radios_unifi
    ADD COLUMN presente_na_captura boolean NOT NULL DEFAULT true,
    ADD COLUMN atualizado_em timestamptz;
CREATE TABLE operacional.sincronizacoes_radios_unifi (
    fonte_id varchar(120) PRIMARY KEY REFERENCES operacional.fontes_radios_unifi(id) ON DELETE RESTRICT,
    capturado_em timestamptz NOT NULL,
    publicacao_textual varchar(80) NOT NULL,
    arquivo_origem_sha256 varchar(64) NOT NULL CHECK (arquivo_origem_sha256 ~ '^[0-9a-f]{64}$'),
    projecao_sha256 varchar(64) NOT NULL CHECK (projecao_sha256 ~ '^[0-9a-f]{64}$'),
    digest_carga varchar(64) NOT NULL CHECK (digest_carga ~ '^[0-9a-f]{64}$'),
    aps integer NOT NULL CHECK (aps > 0),
    configuracoes integer NOT NULL CHECK (configuracoes >= 0),
    estatisticas integer NOT NULL CHECK (estatisticas >= 0),
    sincronizado_em timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);
REVOKE ALL ON operacional.sincronizacoes_radios_unifi FROM PUBLIC, sentinel_reader, sentinel_api;
GRANT SELECT ON operacional.sincronizacoes_radios_unifi TO sentinel_unifi_radios_reader;
GRANT SELECT, INSERT, UPDATE ON operacional.sincronizacoes_radios_unifi TO sentinel_collector;
GRANT UPDATE ON operacional.recebimentos_radios_unifi, operacional.configuracoes_radios_unifi,
    operacional.estatisticas_radios_unifi TO sentinel_collector;
COMMIT;
