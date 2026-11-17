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

CREATE TABLE operacional.wlans_unifi (
    controladora_id varchar(120) NOT NULL,
    site_id varchar(120) NOT NULL,
    id_origem varchar(120) NOT NULL CHECK (id_origem ~ '^[A-Za-z0-9_.:-]+$'),
    nome varchar(240) NOT NULL CHECK (btrim(nome) <> ''),
    networkconf_id varchar(120) CHECK (networkconf_id ~ '^[A-Za-z0-9_.:-]+$'),
    ativo boolean,
    bandas text[] NOT NULL,
    coletado_em timestamptz NOT NULL,
    origem varchar(40) NOT NULL CHECK (origem = 'configuracao_unifi'),
    arquivo_origem_sha256 varchar(64) NOT NULL CHECK (arquivo_origem_sha256 ~ '^[0-9a-f]{64}$'),
    catalogo_regionais_sha256 varchar(64) NOT NULL CHECK (catalogo_regionais_sha256 ~ '^[0-9a-f]{64}$'),
    importado_em timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (controladora_id,site_id,id_origem),
    FOREIGN KEY (controladora_id,site_id) REFERENCES operacional.sites_unifi(controladora_id,id_origem)
        ON UPDATE CASCADE ON DELETE RESTRICT
);

GRANT SELECT ON operacional.wlans_unifi TO sentinel_reader;
GRANT SELECT, INSERT ON operacional.wlans_unifi TO sentinel_collector;
COMMIT;
