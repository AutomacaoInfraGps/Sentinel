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

CREATE TABLE operacional.vpns (
    firewall_serial varchar(120) NOT NULL CHECK (firewall_serial ~ '^[A-Za-z0-9_.-]+$'),
    vdom varchar(120) NOT NULL CHECK (vdom ~ '^[A-Za-z0-9_.-]+$'
        AND lower(vdom) NOT IN ('global', 'unknown')),
    tunel varchar(240) NOT NULL CHECK (tunel = btrim(tunel) AND tunel <> ''),
    dispositivo_nome varchar(240),
    dispositivo_namespace varchar(240) NOT NULL CHECK (
        left(dispositivo_namespace, 14) = 'fortigate_ssh:' AND length(dispositivo_namespace) > 14),
    codigo_regional varchar(120) REFERENCES operacional.regionais(codigo)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    regional_origem varchar(120),
    vinculo_regional varchar(20) NOT NULL CHECK (
        vinculo_regional IN ('vinculado', 'nao_encontrado', 'ausente')),
    status varchar(20) NOT NULL CHECK (status IN ('online', 'offline')),
    coletado_em timestamptz NOT NULL,
    via_coleta varchar(40) NOT NULL CHECK (via_coleta = 'fortigate_ssh'),
    vdom_origem varchar(40) NOT NULL CHECK (
        vdom_origem IN ('resposta_equipamento', 'vdom_desabilitado')),
    interface varchar(240),
    hora_verificacao_legada varchar(8),
    arquivo_origem_sha256 varchar(64) NOT NULL CHECK (arquivo_origem_sha256 ~ '^[0-9a-f]{64}$'),
    catalogo_regionais_sha256 varchar(64) NOT NULL CHECK (catalogo_regionais_sha256 ~ '^[0-9a-f]{64}$'),
    importado_em timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    presente_no_snapshot boolean NOT NULL DEFAULT true,
    PRIMARY KEY (firewall_serial, vdom, tunel),
    CONSTRAINT vpn_vinculo_coerente CHECK (
        (codigo_regional IS NOT NULL AND vinculo_regional = 'vinculado') OR
        (codigo_regional IS NULL AND vinculo_regional <> 'vinculado')),
    CONSTRAINT vpn_vdom_origem_coerente CHECK (
        vdom_origem <> 'vdom_desabilitado' OR vdom = 'root')
);

CREATE INDEX vpns_regional_idx ON operacional.vpns(codigo_regional);
GRANT SELECT ON operacional.vpns TO sentinel_reader;
GRANT SELECT, INSERT ON operacional.vpns TO sentinel_collector;

COMMIT;
