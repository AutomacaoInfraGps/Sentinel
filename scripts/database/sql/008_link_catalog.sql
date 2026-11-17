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

CREATE TABLE operacional.links_internet (
    codigo_regional varchar(120) NOT NULL REFERENCES operacional.regionais(codigo)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    id_origem varchar(240) NOT NULL CHECK (id_origem = btrim(id_origem) AND id_origem <> ''),
    nome varchar(240) NOT NULL CHECK (nome = btrim(nome) AND nome <> ''),
    interface_monitorada varchar(240) NOT NULL CHECK (btrim(interface_monitorada) <> ''),
    fortigate_host varchar(253) NOT NULL CHECK (btrim(fortigate_host) <> ''),
    fortigate_porta integer CHECK (fortigate_porta BETWEEN 1 AND 65535),
    firewall_serial varchar(120),
    vdom varchar(120),
    provedor varchar(240),
    ip inet,
    mascara varchar(80),
    velocidade varchar(120),
    status varchar(40) NOT NULL CHECK (status IN (
        'online', 'offline', 'unknown', 'warning', 'inativo', 'maintenance', 'up', 'down', 'unavailable')),
    ativo boolean,
    origem_sync varchar(120),
    modo_verificacao varchar(120),
    sla_status varchar(120),
    link_mode_status varchar(120),
    sdwan_member_id varchar(240),
    prioridade integer CHECK (prioridade >= 0),
    packet_loss_percent double precision CHECK (packet_loss_percent BETWEEN 0 AND 100),
    verificado_em timestamptz,
    coletado_em timestamptz,
    verificacao_sem_fuso_na_origem boolean NOT NULL,
    arquivo_origem_sha256 varchar(64) NOT NULL CHECK (arquivo_origem_sha256 ~ '^[0-9a-f]{64}$'),
    fuso_verificacao_legada varchar(120) NOT NULL,
    fonte_cadastro varchar(40) NOT NULL DEFAULT 'links_internet_auto'
        CHECK (fonte_cadastro = 'links_internet_auto'),
    importado_em timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    presente_no_snapshot boolean NOT NULL DEFAULT true,
    PRIMARY KEY (codigo_regional, id_origem)
);

GRANT SELECT ON operacional.links_internet TO sentinel_reader;
GRANT SELECT, INSERT ON operacional.links_internet TO sentinel_collector;

COMMIT;
