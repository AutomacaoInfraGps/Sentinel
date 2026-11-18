# Auditoria de cobertura por tela - 18/11/2026

## Conclusao

NAO: o PostgreSQL operacional sentinel no Rigel ainda nao contem todos os dados
de todas as telas. Ha espelhos dos inventarios principais e dos cadastros de
contatos/admins, mas faltam dominios inteiros, campos tecnicos, historicos e
estados de interacao. Existir uma tabela de equipamentos nao torna completa a
persistencia da tela correspondente.

Esta verificacao cruza rotas, templates, coletores, campos publicados e SQL
001-017 do repositorio. Usa os resultados enviados pelo operador para registrar
o que foi homologado em producao. Nao houve conexao remota ao Rigel, consulta
ao banco de producao, execucao de coletores ou leitura de registros pessoais.
Os numeros abaixo sao ultimas conferencias recebidas, nao uma contagem ao vivo.
DDL/configuracoes criadas manualmente fora deste repositorio precisam conferencia
no servidor; nao e possivel provar ausencia dessas tabelas somente pelo codigo.

## Espelhos homologados

| Dominio | Ultima conferencia recebida | Alcance |
| --- | --- | --- |
| Regionais | 51 | Identidade/nome e vinculos de inventario; nao todos os metadados |
| Servidores | 76 | Cadastro e estado basico, nao inventario completo de hardware |
| Firewalls/licencas | 49 / 49 | Inventario, disponibilidade, prazo e evidencia de licencas |
| Switches | 166 | Inventario Zabbix/local, estado, manutencao e contagem de alertas |
| VPNs | 166 | Contexto SSH verificado, serial/VDOM/tunel, estado e coleta |
| Links | 88 | Cadastro automatico; ultima prova de coleta explicita em 83, nao 88 |
| UniFi | 1 controladora, 43 sites, 216 APs | Inventario/status/clientes/uptime, sem telemetria RF completa |
| WLANs | 188 | Configuracao nativa com ID, nome, bandas, ativo e ID da rede |
| Contatos SLA | 38 regionais, 127 vinculos | Diretor, gerente, apoio_1 e apoio_2 por regional |
| Monitor de Admins | 54 dispositivos, 227 observadas, 233 aprovadas | Baseline, observadas e divergencias separadas |

017 validada pelo operador: captura/ultima leitura automatica em
2026-11-18 08:20:34.876846 -03:00 com conteudo_ja_sincronizado=true. O cache dos
equipamentos continuava de 07:24:35: nova leitura nao significa nova consulta Forti.
18 contas tinham evidencia cache_sem_confirmacao_atual, 209 consulta_valida_declarada.

As telas principais continuam lendo JSON/XLSX/coletores. Gravar um espelho SQL
nao e migrar seus leitores. Exemplo: o sino usa load_operational_state e o
cadastro de e-mails continua editando a planilha do projeto SLA.

## Matriz por tela

| Tela/funcionalidade | Fonte efetiva encontrada | Cobertura no sentinel operacional | Falta ou observacao |
| --- | --- | --- | --- |
| Inicio / Servidores | GerenciadorRegionais, estrutura_regionais.json, dashboard | Parcial | Cadastro sincronizado; hardware detalhado, metricas e historico nao |
| Regionais / editar / detalhes | estrutura_regionais.json + snapshots dos dispositivos | Parcial | descricao, estado/UF e demais metadados nao entram no escritor regional atual; links legados manuais nao sao a carga de links automaticos |
| Mapa | output/mapa_monitoramento_cache.json + fontes operacionais | Parcial, por dominio | Agregado/topologia/associacoes e metadados de atualizacao nao tem espelho integral; nem todos os campos dos dispositivos estao no SQL |
| Fluxo Neural | Projecao filtrada do mapa + overlay data/unifi.json | Parcial | Reutiliza inventario; nome textual de rede/VLAN, transmissao e relacao WLAN-AP nao estao no catalogo WLAN SQL |
| Replicacao AD | load_data('replicacao') + JSON publico escolhido/normalizado | Sem migracao operacional especifica | Controladores, parceiros, tentativas, falhas, erros e ultima replicacao |
| Antenas UniFi | data/unifi.json | Parcial | Canal, utilizacao de canal, TX/RX proprio, retransmissao e evidencia necessaria para recalcular interferencia/risco |
| Maquinas Virtuais / relatorio | data/vms.json + consultas sob demanda | Sem migracao operacional especifica | Cadastro proprio, host/VM, discos, memoria, processos, servicos e eventos. Nao confundir com operacional.servidores |
| Links de Internet | links_internet_auto + consultas/estatisticas | Parcial | Trafego de entrada/saida e suas series; links manuais legados em estrutura_regionais.links nao foram importados |
| VPN IPsec | Estado operacional SSH com contexto verificado | Inventario/status cobertos na fonte migrada | Nao e inventario universal de todos os coletores/contextos ou historico de disponibilidade |
| Switches | Zabbix/cache + switches_metadata.json + scheduler | Parcial | Firmware consultado, horario de consulta, causas/detalhes de alertas e portas/uplinks; agendamentos/tentativas/logs em SQLite separado |
| Firewalls | Cache dashboard + catalogo FortiManager | Inventario/licencas cobertos | Avaliacao de firmware e catalogo de releases nao sao preservados integralmente como evidencia SQL; nao ha historico completo de eventos |
| Monitor de Admins | Cache + admin_baseline_file configurado | Estado atual espelhado | Nao ha trilha completa de ator/horario de cada aprovacao; eventos FAZ exibidos sob demanda nao sao os registros de divergencias SQL |
| Validade de Certificados | certificate_disk_report_acrab.json | Sem migracao operacional especifica | Metadados, emissor, vencimento e evidencia de coleta; nao importar chaves privadas |
| Cadastro de E-mails | XLSX externo, aba configurada | Cadastros preenchidos espelhados | Nao e cadastro mestre de pessoas, nao inclui historico completo das edicoes, nem troca o projeto SLA para SQL |
| Sino | Estado operacional + AlertAD + Revisao de Acessos + historico switches | Parcial pelas fontes | Lido/dispensado por usuario em output/notification_user_state.json; agregacao nao migrou para SQL |
| Relatorios de infraestrutura/preventiva | Arquivos gerados e output/*.html | Sem repositorio operacional de relatorios | Artefatos, indice, evidencias e historico de geracao nao estao no SQL de inventario |
| Dashboard hierarquico | Geracao de HTML e output/dados_dashboard.json | Parcial pelas fontes | Nao ha persistencia integral adicional desse painel |
| Executar completo | Orquestracao/coletas e status de execucao | Sem espelho integral | Filas, etapas, logs e resultados de execucao nao equivalem aos marcadores de sincronizacao |
| Revisao de Acessos | queue.sqlite3 + arquivos/evidencias de auditoria | Banco separado, nao migrado para sentinel | Fila/execucoes/documentos continuam no modulo proprio |
| SofIA | n8n, bancos proprios, JSON operacional, SQLite local de requisicoes | Arquitetura separada | Ha migracoes PostgreSQL proprias para alertas/historico/memoria; nao declarar que nao existe banco, nem que esta tudo no sentinel |
| Permissoes regionais | AD + regional_access_*.json | Sem migracao operacional especifica | Associacoes descobertas/aprovadas e trilha de alteracoes nao sao o cadastro de contatos SLA |
| Configuracoes / aparencia | environment.json, DPAPI, armazenamento do navegador | Fora do escopo de inventario | Segredos nao devem ser copiados para tabelas de inventario; preferencia de tema nao e dado operacional |
| Backup | Tela e exportacao atual | Nao equivale a backup PostgreSQL | /api/backup/exportar tem placeholder; backups pg_dump validados sao processo separado e precisam ser mantidos |

## Evidencias verificadas no codigo

1. Menu e alcance: templates/base.html:865-1033; rotas em web_config.py,
   blueprints de sofia e services/switch_update_v01/sentinel_backend.py.
2. Regionais: services/operational_server_postgres.py:106 escreve somente
   codigo/nome/presente_no_cadastro; templates/regional_form.html:168 e :188
   exibem estado e descricao. Nenhum escritor operacional persiste esses campos.
3. Hardware: web_config.py:11957 coleta via WinRM/IDRAC/SNMP; 002_server_catalog.sql
   define cadastro, sem tabelas de discos/memoria/CPU/servicos.
4. VMs: web_config.py:9098, :9372 e gerenciar_vms.py:547; nao ha migracao VM em 001-017.
5. AD: web_config.py:10125 escolhe/normaliza JSONs, nao le tabelas de replicacao.
6. Certificados: web_config.py:5363, :5414 e :5450; fonte e relatorio JSON.
7. APs: templates/antenas_simples.html:235-302 usa cu_total/cu_self_tx/cu_self_rx/
   tx_retry/canal. 010_ap_catalog.sql:50-66 e operational_ap_postgres.NATIVE_FIELDS
   nao contem essas metricas. Contagens/risco derivados podem ser recalculados,
   mas precisam primeiro persistir as evidencias que os alimentam.
8. WLAN: 012_wlan_catalog.sql:17-29 armazena networkconf_id, nao a entidade rede/VLAN
   ou associacoes de transmissao. services/map_wifi_overlay.py:33-43 usa rede textual
   e transmissao da lista de exibicao; identidade da configuracao nao e essa lista.
9. Links: templates/links_internet.html:593-613 mostra bandwidth_in/bandwidth_out;
   008_link_catalog.sql e operational_link_postgres.RECORD_KEYS nao os armazenam.
10. Switches: templates/switches.html:808-831 usa firmware_version/firmware_checked_at
    e status_reason; 004_switch_catalog.sql:20-50 nao inclui esses campos.
    services/switch_update_v01/scheduler.py:318 usa SQLite.
11. Admins: web_config.py:8719, :8966-9014 e scripts/database/sql/016-017;
    eventos FAZ nao equivalem a novas/removidas do cache. Relatorio de sincronizacao
    nao prova uma nova consulta ao equipamento ou nova alteracao de baseline.
12. Sino: web_config.py:5222 e notification_center.py:14; lido/dispensado e JSON.
13. SofIA: sofia/database/README.md documenta banco sofia separado de n8n, possivelmente
    na instancia do Celeno; migracao 010_alert_history.sql define eventos historicos.
    Sua aplicacao e retencao precisam auditoria na instancia correta, nao apenas
    conferencia das migracoes operacionais do Rigel. sofia/chat_requests.py:26 usa SQLite;
    sofia/audit.py:10 usa JSONL. operational_license_query.py tem leitor SQL especifico,
    o que nao transforma todos os leitores das telas em SQL.
14. Revisao de Acessos: services/access_review_v1/persistence.py:13 usa queue.sqlite3.
    AlertAD tambem tem persistencia SQLite propria em seu modulo persistence.py.
15. Permissoes: regional_access.py:36-38 define arquivos de mapeamento/descoberta/auditoria.
16. Backup: web_config.py:13300 retorna backup_sistema.zip como placeholder. O retorno
    de sucesso dessa rota nao comprova criacao de dump SQL. Nenhuma correcao de runtime
    foi feita nesta verificacao.

## Proximas etapas recomendadas

1. Cadastro e observacoes de VMs, com identidade confiavel e isolamento de credenciais.
2. Replicacao AD e metadados de certificados, com evidencia/data da coleta.
3. Completar regionais, hardware, telemetria RF, firmware/portas e trafego de links;
   reconciliar o cadastro manual/automatico de links sem fundir por nome.
4. Planejar historicos de disponibilidade/aprovacoes e estado de notificacoes,
   com retencao e autorizacao. Nao duplicar sem analise o historico separado da SofIA.
5. Revisar banco por banco e o plano de backup: sentinel, sofia/n8n e SQLite.
6. So depois avaliar troca de leitores das telas; nao desligar JSON/XLSX hoje.

Senhas, tokens, chaves privadas e vault DPAPI permanecem fora do inventario SQL.
Arquivos HTML/DOCX/XLSX/PDF e firmwares nao precisam virar blobs: pode-se manter
o artefato em armazenamento controlado e persistir metadados/caminho/hash no banco.
Dados derivados (contadores, cores, layouts) nao precisam tabelas duplicadas;
precisam fontes suficientes para recalculo, frescor e escopo correto.

## Conferencia complementar em producao

scripts/database/sql/audit_screen_coverage.sql e SOMENTE LEITURA. Retorna contagens,
metadados de tabelas e horarios de marcadores, sem dados pessoais ou credenciais.
Executar como conta autorizada a ler contatos/admins (por exemplo sentinel_admin),
nao ampliar grants de sentinel_api para rodar a auditoria.
Ele nao confirma equivalencia campo a campo com todos os JSONs e nao audita a
instancia separada de SofIA/n8n ou SQLite. APs/WLANs nao possuem flag uniforme de
presenca: total armazenado nao prova inventario atual completo. Horario de leitura
dos polls SLA/admins nao e horario de coleta nos dispositivos.
