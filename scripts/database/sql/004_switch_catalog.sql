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

CREATE TABLE operacional.switches (
    fonte varchar(80) NOT NULL CHECK (fonte = 'sentinel_zabbix_principal'),
    tipo_origem varchar(10) NOT NULL CHECK (tipo_origem IN ('zabbix', 'local')),
    id_origem varchar(240) NOT NULL CHECK (id_origem = btrim(id_origem) AND id_origem <> ''),
    nome varchar(240) NOT NULL CHECK (nome = btrim(nome) AND nome <> ''),
    zabbix_host varchar(240),
    zabbix_nome varchar(240),
    codigo_regional varchar(120) REFERENCES operacional.regionais(codigo)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    regional_origem varchar(240),
    vinculo_regional varchar(20) NOT NULL
        CHECK (vinculo_regional IN ('vinculado', 'nao_encontrado', 'ambiguo', 'ausente')),
    endereco varchar(253),
    ip inet,
    modelo varchar(240),
    modelo_origem varchar(120),
    localizacao varchar(240),
    is_core boolean,
    core_origem varchar(120),
    status varchar(120),
    ultima_verificacao timestamptz,
    em_manutencao boolean,
    maintenance_status varchar(40),
    maintenance_type varchar(40),
    maintenance_id varchar(120),
    maintenance_scope varchar(120),
    alertas_ativos integer CHECK (alertas_ativos >= 0),
    arquivo_origem_sha256 varchar(64) NOT NULL CHECK (arquivo_origem_sha256 ~ '^[0-9a-f]{64}$'),
    catalogo_regionais_sha256 varchar(64) NOT NULL CHECK (catalogo_regionais_sha256 ~ '^[0-9a-f]{64}$'),
    importado_em timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    presente_no_snapshot boolean NOT NULL DEFAULT true,
    PRIMARY KEY (fonte, tipo_origem, id_origem),
    CONSTRAINT switch_vinculo_coerente CHECK (
        (codigo_regional IS NOT NULL AND vinculo_regional = 'vinculado') OR
        (codigo_regional IS NULL AND vinculo_regional <> 'vinculado')),
    CONSTRAINT switch_hostid_valido CHECK (
        tipo_origem <> 'zabbix' OR id_origem ~ '^[1-9][0-9]*$')
);

CREATE INDEX switches_regional_idx ON operacional.switches(codigo_regional);

GRANT SELECT ON operacional.switches TO sentinel_reader;
GRANT SELECT, INSERT ON operacional.switches TO sentinel_collector;

COMMIT;
