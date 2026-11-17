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

CREATE TABLE operacional.controladoras_unifi (
    id varchar(120) PRIMARY KEY CHECK (id = btrim(id) AND id <> ''),
    host varchar(253) NOT NULL CHECK (host = btrim(host) AND host <> ''),
    porta integer NOT NULL CHECK (porta BETWEEN 1 AND 65535),
    publicacao_fonte_em timestamptz,
    publicacao_sem_fuso_na_origem boolean NOT NULL,
    arquivo_origem_sha256 varchar(64) NOT NULL CHECK (arquivo_origem_sha256 ~ '^[0-9a-f]{64}$'),
    catalogo_regionais_sha256 varchar(64) NOT NULL CHECK (catalogo_regionais_sha256 ~ '^[0-9a-f]{64}$'),
    fuso_publicacao_legada varchar(120) NOT NULL,
    importado_em timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE operacional.sites_unifi (
    controladora_id varchar(120) NOT NULL REFERENCES operacional.controladoras_unifi(id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    id_origem varchar(120) NOT NULL CHECK (id_origem ~ '^[A-Za-z0-9_.-]+$'),
    nome varchar(240) NOT NULL CHECK (nome = btrim(nome) AND nome <> ''),
    codigo_regional varchar(120) REFERENCES operacional.regionais(codigo)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    vinculo_regional varchar(80) NOT NULL CHECK (vinculo_regional IN (
        'alias_explicito', 'identidade_normalizada_unica', 'identidade_unica_com_alias_desatualizado',
        'alias_sem_regional', 'destino_alias_ausente', 'sem_referencia', 'ambiguo', 'nao_encontrado')),
    CONSTRAINT site_unifi_vinculo_coerente CHECK ((codigo_regional IS NOT NULL) =
        (vinculo_regional IN ('alias_explicito', 'identidade_normalizada_unica',
                             'identidade_unica_com_alias_desatualizado'))),
    importado_em timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (controladora_id, id_origem)
);
CREATE INDEX sites_unifi_regional_idx ON operacional.sites_unifi(codigo_regional);

CREATE TABLE operacional.aps_unifi (
    controladora_id varchar(120) NOT NULL,
    mac varchar(17) NOT NULL CHECK (mac ~ '^([0-9a-f]{2}:){5}[0-9a-f]{2}$'
        AND mac NOT IN ('00:00:00:00:00:00', 'ff:ff:ff:ff:ff:ff')),
    site_id varchar(120) NOT NULL,
    nome varchar(240) NOT NULL CHECK (nome = btrim(nome) AND nome <> ''),
    ip inet,
    modelo_codigo varchar(240),
    modelo varchar(240),
    firmware varchar(240),
    status varchar(40) NOT NULL CHECK (status IN ('online', 'offline', 'warning', 'unknown', 'maintenance', 'inativo')),
    clientes integer CHECK (clientes >= 0),
    uptime_segundos bigint CHECK (uptime_segundos >= 0),
    coletado_em timestamptz,
    em_manutencao boolean,
    importado_em timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (controladora_id, mac),
    FOREIGN KEY (controladora_id, site_id) REFERENCES operacional.sites_unifi(controladora_id, id_origem)
        ON UPDATE CASCADE ON DELETE RESTRICT
);
CREATE INDEX aps_unifi_site_idx ON operacional.aps_unifi(controladora_id, site_id);

GRANT SELECT ON operacional.controladoras_unifi, operacional.sites_unifi, operacional.aps_unifi
    TO sentinel_reader;
GRANT SELECT, INSERT ON operacional.controladoras_unifi, operacional.sites_unifi, operacional.aps_unifi
    TO sentinel_collector;

COMMIT;
