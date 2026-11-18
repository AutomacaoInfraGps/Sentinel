\set ON_ERROR_STOP on
\pset pager off
BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL statement_timeout = '15s';
SET LOCAL lock_timeout = '2s';
DO $$
BEGIN
    IF current_database() <> 'sentinel' OR inet_server_port() IS DISTINCT FROM 5433 THEN
        RAISE EXCEPTION 'Instancia divergente. Auditoria cancelada.';
    END IF;
END
$$;

SELECT current_database() AS banco, inet_server_port() AS porta,
       CURRENT_TIMESTAMP AS conferido_em;

-- Counts only. No individual devices, users, contact names or addresses.
SELECT 'regionais' AS dominio, count(*) AS armazenados,
       count(*) FILTER (WHERE presente_no_cadastro) AS marcados_presentes
FROM operacional.regionais
UNION ALL SELECT 'servidores', count(*), count(*) FILTER (WHERE presente_no_snapshot) FROM operacional.servidores
UNION ALL SELECT 'firewalls', count(*), count(*) FILTER (WHERE presente_no_snapshot) FROM operacional.firewalls
UNION ALL SELECT 'licencas_firewall', count(*), count(*) FILTER (WHERE presente_no_snapshot) FROM operacional.licencas_firewall
UNION ALL SELECT 'switches', count(*), count(*) FILTER (WHERE presente_no_snapshot) FROM operacional.switches
UNION ALL SELECT 'vpns', count(*), count(*) FILTER (WHERE presente_no_snapshot) FROM operacional.vpns
UNION ALL SELECT 'links_internet', count(*), count(*) FILTER (WHERE presente_no_snapshot) FROM operacional.links_internet
UNION ALL SELECT 'controladoras_unifi', count(*), NULL::bigint FROM operacional.controladoras_unifi
UNION ALL SELECT 'sites_unifi', count(*), NULL::bigint FROM operacional.sites_unifi
UNION ALL SELECT 'aps_unifi', count(*), NULL::bigint FROM operacional.aps_unifi
UNION ALL SELECT 'wlans_unifi', count(*), NULL::bigint FROM operacional.wlans_unifi
UNION ALL SELECT 'regionais_contatos_sla', count(*), count(*) FILTER (WHERE presente_na_fonte) FROM operacional.regionais_contatos_sla
UNION ALL SELECT 'contatos_regionais_sla', count(*), count(*) FILTER (WHERE presente_na_fonte) FROM operacional.contatos_regionais_sla
UNION ALL SELECT 'dispositivos_monitor_admins', count(*), count(*) FILTER (WHERE presente_na_fonte) FROM operacional.dispositivos_monitor_admins
UNION ALL SELECT 'contas_admins_observadas', count(*), count(*) FILTER (WHERE presente_na_fonte) FROM operacional.contas_admins_observadas
UNION ALL SELECT 'baseline_admins_aprovada', count(*), count(*) FILTER (WHERE presente_na_fonte) FROM operacional.baseline_admins_aprovada
UNION ALL SELECT 'divergencias_monitor_admins', count(*), count(*) FILTER (WHERE presente_na_fonte) FROM operacional.divergencias_monitor_admins
ORDER BY dominio;

-- Per-device markers: min/max expose older observations concealed by a recent max.
SELECT 'firewalls' AS dominio, count(*) AS marcadores,
       min(coleta_publicada_em) AS origem_mais_antiga, max(coleta_publicada_em) AS origem_mais_recente,
       max(sincronizado_em) AS ultima_gravacao
FROM operacional.sincronizacoes
UNION ALL SELECT 'servidores', count(*), min(cadastro_publicado_em), max(cadastro_publicado_em), max(sincronizado_em)
FROM operacional.sincronizacoes_servidores
UNION ALL SELECT 'switches', count(*), min(publicado_em), max(publicado_em), max(sincronizado_em)
FROM operacional.sincronizacoes_switches
UNION ALL SELECT 'vpns', count(*), min(coletado_em), max(coletado_em), max(sincronizado_em)
FROM operacional.sincronizacoes_vpns
UNION ALL SELECT 'links', count(*), min(coletado_em), max(coletado_em), max(sincronizado_em)
FROM operacional.sincronizacoes_links
UNION ALL SELECT 'aps', count(*), min(coletado_em), max(coletado_em), max(sincronizado_em)
FROM operacional.sincronizacoes_aps
UNION ALL SELECT 'wlans', count(*), min(coletado_em), max(coletado_em), max(sincronizado_em)
FROM operacional.sincronizacoes_wlans
UNION ALL SELECT 'contatos_sla_leitura', count(*), min(lido_em), max(lido_em), max(sincronizado_em)
FROM operacional.sincronizacoes_contatos_sla
UNION ALL SELECT 'admins_leitura', count(*), min(lido_em), max(lido_em), max(sincronizado_em)
FROM operacional.sincronizacoes_monitor_admins
ORDER BY dominio;

SELECT count(*) AS links, count(*) FILTER (WHERE coletado_em IS NOT NULL) AS com_coleta_explicita
FROM operacional.links_internet WHERE presente_no_snapshot;
SELECT min(publicado_em) AS cache_admins_mais_antigo, max(publicado_em) AS cache_admins_mais_recente
FROM operacional.fontes_monitor_admins;
SELECT evidencia, count(*) AS contas FROM operacional.contas_admins_observadas
WHERE presente_na_fonte GROUP BY evidencia ORDER BY evidencia;

-- Actual deployed columns, including any manual additions outside this repository.
SELECT n.nspname AS esquema, c.relname AS tabela, a.attname AS coluna,
       pg_catalog.format_type(a.atttypid, a.atttypmod) AS tipo
FROM pg_catalog.pg_class c
JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
JOIN pg_catalog.pg_attribute a ON a.attrelid = c.oid
WHERE n.nspname = 'operacional' AND c.relkind IN ('r','p') AND a.attnum > 0 AND NOT a.attisdropped
ORDER BY c.relname, a.attnum;
COMMIT;
