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

ALTER TABLE operacional.controladoras_unifi
    ALTER COLUMN arquivo_origem_sha256 DROP NOT NULL,
    ALTER COLUMN catalogo_regionais_sha256 DROP NOT NULL,
    ADD COLUMN atualizado_no_banco_em timestamptz;
ALTER TABLE operacional.sites_unifi
    ADD COLUMN coletado_em timestamptz,
    ADD COLUMN atualizado_no_banco_em timestamptz;
ALTER TABLE operacional.aps_unifi ADD COLUMN atualizado_no_banco_em timestamptz;

CREATE TABLE operacional.sincronizacoes_aps (
    controladora_id varchar(120) NOT NULL,
    mac varchar(17) NOT NULL,
    coletado_em timestamptz NOT NULL,
    conteudo_sha256 varchar(64) NOT NULL CHECK (conteudo_sha256 ~ '^[0-9a-f]{64}$'),
    sincronizado_em timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(controladora_id,mac),
    FOREIGN KEY(controladora_id,mac) REFERENCES operacional.aps_unifi(controladora_id,mac)
        ON UPDATE CASCADE ON DELETE RESTRICT
);
GRANT UPDATE ON operacional.controladoras_unifi, operacional.sites_unifi, operacional.aps_unifi TO sentinel_collector;
GRANT SELECT, INSERT, UPDATE ON operacional.sincronizacoes_aps TO sentinel_collector;
GRANT SELECT ON operacional.sincronizacoes_aps TO sentinel_reader;
COMMIT;
