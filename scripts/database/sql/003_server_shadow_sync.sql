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

ALTER TABLE operacional.regionais
    ADD COLUMN presente_no_cadastro boolean NOT NULL DEFAULT false;

ALTER TABLE operacional.servidores
    ADD COLUMN presente_no_snapshot boolean NOT NULL DEFAULT true,
    ADD COLUMN atualizado_no_banco_em timestamptz,
    ALTER COLUMN arquivo_origem_sha256 DROP NOT NULL;

CREATE TABLE operacional.sincronizacoes_servidores (
    fonte varchar(40) PRIMARY KEY CHECK (fonte = 'estrutura_regionais'),
    cadastro_publicado_em timestamptz NOT NULL,
    conteudo_sha256 varchar(64) NOT NULL CHECK (conteudo_sha256 ~ '^[0-9a-f]{64}$'),
    sincronizado_em timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);

GRANT UPDATE ON operacional.servidores TO sentinel_collector;
GRANT SELECT, INSERT, UPDATE ON operacional.sincronizacoes_servidores TO sentinel_collector;
GRANT SELECT ON operacional.sincronizacoes_servidores TO sentinel_reader;

COMMIT;
