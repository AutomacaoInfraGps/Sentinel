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

ALTER TABLE operacional.switches
    ADD COLUMN atualizado_no_banco_em timestamptz,
    ALTER COLUMN arquivo_origem_sha256 DROP NOT NULL,
    ALTER COLUMN catalogo_regionais_sha256 DROP NOT NULL;

CREATE TABLE operacional.sincronizacoes_switches (
    fonte varchar(80) PRIMARY KEY CHECK (fonte = 'sentinel_zabbix_principal'),
    publicado_em timestamptz NOT NULL,
    conteudo_sha256 varchar(64) NOT NULL CHECK (conteudo_sha256 ~ '^[0-9a-f]{64}$'),
    inventario_completo boolean NOT NULL,
    sincronizado_em timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);

GRANT UPDATE ON operacional.switches TO sentinel_collector;
GRANT SELECT, INSERT, UPDATE ON operacional.sincronizacoes_switches TO sentinel_collector;
GRANT SELECT ON operacional.sincronizacoes_switches TO sentinel_reader;

COMMIT;
