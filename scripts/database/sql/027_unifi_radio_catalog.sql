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
CREATE ROLE sentinel_unifi_radios_reader NOLOGIN;
SET LOCAL ROLE sentinel_owner;

CREATE TABLE operacional.fontes_radios_unifi (
    id varchar(120) PRIMARY KEY CHECK (id = 'sentinel_radios_unifi_nativos'),
    versao integer NOT NULL CHECK (versao = 1),
    controladora_id varchar(120) NOT NULL REFERENCES operacional.controladoras_unifi(id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    host_origem varchar(253) NOT NULL CHECK (btrim(host_origem) <> ''),
    porta_origem integer NOT NULL CHECK (porta_origem BETWEEN 1 AND 65535),
    capturado_em timestamptz NOT NULL,
    publicacao_textual varchar(80) NOT NULL CHECK (btrim(publicacao_textual) <> ''),
    arquivo_origem_sha256 varchar(64) NOT NULL CHECK (arquivo_origem_sha256 ~ '^[0-9a-f]{64}$'),
    projecao_sha256 varchar(64) NOT NULL CHECK (projecao_sha256 ~ '^[0-9a-f]{64}$'),
    digest_carga varchar(64) NOT NULL CHECK (digest_carga ~ '^[0-9a-f]{64}$'),
    importado_em timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (id, controladora_id)
);

CREATE TABLE operacional.recebimentos_radios_unifi (
    fonte_id varchar(120) NOT NULL,
    controladora_id varchar(120) NOT NULL,
    mac varchar(17) NOT NULL,
    site_id_origem varchar(120) NOT NULL,
    recebido_em timestamptz NOT NULL,
    medido_em timestamptz CHECK (medido_em IS NULL),
    data_medicao_confirmada boolean NOT NULL DEFAULT false CHECK (NOT data_medicao_confirmada),
    ap_online_declarado boolean,
    configuracoes_situacao varchar(20) NOT NULL CHECK (configuracoes_situacao IN ('presente','ausente','nulo')),
    estatisticas_situacao varchar(20) NOT NULL CHECK (estatisticas_situacao IN ('presente','ausente','nulo')),
    quantidade_configuracoes integer NOT NULL CHECK (quantidade_configuracoes >= 0),
    quantidade_estatisticas integer NOT NULL CHECK (quantidade_estatisticas >= 0),
    importado_em timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (fonte_id, controladora_id, mac),
    FOREIGN KEY (fonte_id, controladora_id) REFERENCES operacional.fontes_radios_unifi(id, controladora_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    FOREIGN KEY (controladora_id, mac) REFERENCES operacional.aps_unifi(controladora_id, mac)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    FOREIGN KEY (controladora_id, site_id_origem) REFERENCES operacional.sites_unifi(controladora_id, id_origem)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CHECK (configuracoes_situacao = 'presente' OR quantidade_configuracoes = 0),
    CHECK (estatisticas_situacao = 'presente' OR quantidade_estatisticas = 0)
);

CREATE TABLE operacional.configuracoes_radios_unifi (
    fonte_id varchar(120) NOT NULL,
    controladora_id varchar(120) NOT NULL,
    mac varchar(17) NOT NULL,
    nome_interface varchar(120) NOT NULL CHECK (nome_interface ~ '^[A-Za-z0-9_.:-]+$'),
    banda_declarada varchar(120) CHECK (banda_declarada ~ '^[A-Za-z0-9_.:-]+$'),
    banda_situacao varchar(20) NOT NULL CHECK (banda_situacao IN ('informado','ausente','nulo','invalido')),
    canal_valor jsonb,
    canal_situacao varchar(20) NOT NULL CHECK (canal_situacao IN ('informado','ausente','nulo','invalido')),
    importado_em timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (fonte_id, controladora_id, mac, nome_interface),
    FOREIGN KEY (fonte_id, controladora_id, mac)
        REFERENCES operacional.recebimentos_radios_unifi(fonte_id, controladora_id, mac)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CHECK ((banda_situacao = 'informado') = (banda_declarada IS NOT NULL)),
    CHECK ((canal_situacao = 'informado') = (canal_valor IS NOT NULL)),
    CHECK (canal_valor IS NULL OR canal_valor = '"auto"'::jsonb OR CASE
        WHEN jsonb_typeof(canal_valor) IN ('string','number') AND (canal_valor #>> '{}') ~ '^[0-9]{1,4}$'
        THEN (canal_valor #>> '{}')::integer BETWEEN 0 AND 1000 ELSE false END)
);

CREATE TABLE operacional.estatisticas_radios_unifi (
    fonte_id varchar(120) NOT NULL,
    controladora_id varchar(120) NOT NULL,
    mac varchar(17) NOT NULL,
    nome_interface varchar(120) NOT NULL CHECK (nome_interface ~ '^[A-Za-z0-9_.:-]+$'),
    banda_declarada varchar(120) CHECK (banda_declarada ~ '^[A-Za-z0-9_.:-]+$'),
    banda_situacao varchar(20) NOT NULL CHECK (banda_situacao IN ('informado','ausente','nulo','invalido')),
    canal_valor jsonb,
    canal_situacao varchar(20) NOT NULL CHECK (canal_situacao IN ('informado','ausente','nulo','invalido')),
    cu_total double precision CHECK (cu_total BETWEEN 0 AND 100),
    cu_total_situacao varchar(20) NOT NULL CHECK (cu_total_situacao IN ('informado','ausente','nulo','invalido')),
    cu_self_tx double precision CHECK (cu_self_tx BETWEEN 0 AND 100),
    cu_self_tx_situacao varchar(20) NOT NULL CHECK (cu_self_tx_situacao IN ('informado','ausente','nulo','invalido')),
    cu_self_rx double precision CHECK (cu_self_rx BETWEEN 0 AND 100),
    cu_self_rx_situacao varchar(20) NOT NULL CHECK (cu_self_rx_situacao IN ('informado','ausente','nulo','invalido')),
    tx_retry double precision CHECK (tx_retry BETWEEN 0 AND 100),
    tx_retry_situacao varchar(20) NOT NULL CHECK (tx_retry_situacao IN ('informado','ausente','nulo','invalido')),
    importado_em timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (fonte_id, controladora_id, mac, nome_interface),
    FOREIGN KEY (fonte_id, controladora_id, mac)
        REFERENCES operacional.recebimentos_radios_unifi(fonte_id, controladora_id, mac)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CHECK ((banda_situacao = 'informado') = (banda_declarada IS NOT NULL)),
    CHECK ((canal_situacao = 'informado') = (canal_valor IS NOT NULL)),
    CHECK (canal_valor IS NULL OR canal_valor = '"auto"'::jsonb OR CASE
        WHEN jsonb_typeof(canal_valor) IN ('string','number') AND (canal_valor #>> '{}') ~ '^[0-9]{1,4}$'
        THEN (canal_valor #>> '{}')::integer BETWEEN 0 AND 1000 ELSE false END),
    CHECK ((cu_total_situacao = 'informado') = (cu_total IS NOT NULL)),
    CHECK ((cu_self_tx_situacao = 'informado') = (cu_self_tx IS NOT NULL)),
    CHECK ((cu_self_rx_situacao = 'informado') = (cu_self_rx IS NOT NULL)),
    CHECK ((tx_retry_situacao = 'informado') = (tx_retry IS NOT NULL))
);

REVOKE ALL ON operacional.fontes_radios_unifi, operacional.recebimentos_radios_unifi,
    operacional.configuracoes_radios_unifi, operacional.estatisticas_radios_unifi
    FROM PUBLIC, sentinel_reader, sentinel_api;
GRANT USAGE ON SCHEMA operacional TO sentinel_unifi_radios_reader;
GRANT SELECT ON operacional.fontes_radios_unifi, operacional.recebimentos_radios_unifi,
    operacional.configuracoes_radios_unifi, operacional.estatisticas_radios_unifi
    TO sentinel_unifi_radios_reader;
GRANT SELECT, INSERT ON operacional.fontes_radios_unifi, operacional.recebimentos_radios_unifi,
    operacional.configuracoes_radios_unifi, operacional.estatisticas_radios_unifi
    TO sentinel_collector;
COMMIT;
