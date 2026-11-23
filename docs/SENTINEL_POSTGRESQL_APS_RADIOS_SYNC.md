# Sincronizacao manual RF UniFi (028)

Etapa manual homologada no Rigel em 19/11/2026. Automatizacao opcional ativada
em 19/11 e recorrencia/conteudo confirmados em 23/11/2026, conforme evidencias
abaixo. Nao muda coletores ou leitores das telas.
Pre-requisito: 027 e carga inicial conferidas integralmente.

## Sequencia de homologacao

1. Publicar os arquivos e fazer pull no Rigel. Criar novo pg_dump custom e
   conferir codigo de saida, tamanho e pg_restore --list. O backup anterior
   a 027 nao contem os dados RF carregados depois dele.
2. Executar scripts/database/sql/028_unifi_radio_shadow_sync.sql com psql -X,
   ON_ERROR_STOP=1 e sentinel_admin, banco sentinel, loopback porta 5433.
   Exige data_directory E:/Sentinel/PostgreSQL/data. Nao reiniciar servicos.
3. Inicializar o marcador com a MESMA captura congelada da carga inicial.
   Isso confere as linhas atuais contra a evidencia inicial, sem tentar
   reconstruir hashes JSON a partir de tipos numericos do PostgreSQL.

```powershell
& 'C:\Automacao\.venv31410\Scripts\python.exe' `
    'C:\Automacao\scripts\database\sync_ap_radio_catalog.py' `
    --source 'E:\Sentinel\PostgreSQL\backups\carga-radios-unifi-20261119-152903-923\radios-unifi.json'
```

Esperado: conferencia_sem_gravacao; destino_compativel, fonte_inicial_compativel
e conteudo_atual_confere true; conteudo_ja_sincronizado false;
ultima_captura_sincronizada null. Contagens presentes/preservadas: 216
recebimentos, 453 configuracoes e 425 estatisticas. Todos os bloqueios de
antiguidade, conflito e base divergente devem estar false/zero.

Somente apos revisar a conferencia, acrescentar --apply e --expected-digest
dae75c115929e5e9bb6a20035b85f93cdffec2d9f0df742667aca2f828426e79
ao mesmo comando. Repetir sem --apply para confirmar conteudo_ja_sincronizado
true e ultima_captura_sincronizada correspondente a captura inicial. A primeira
sincronizacao so grava o marcador se as linhas RF ja conferem.

4. Depois de homologar a inicializacao, gerar OUTRA captura com
   capture_ap_radio_catalog.py --capture em pasta nova restrita, sem sobrescrever
   a inicial. Conferir com sync_ap_radio_catalog.py --source desse novo arquivo;
   revisar digest/contagens/bloqueios, aplicar explicitamente com seu digest e
   repetir a conferencia. Nao repetir import_ap_radio_catalog.py --apply.

## Garantias e limites

- Fonte inicial imutavel; marcador separado guarda ultima captura sincronizada.
- Captura igual e idempotente. Captura nova com linhas iguais atualiza somente
  o marcador, sem reescrever o conjunto RF.
- Registros ausentes recebem presente_na_captura=false, nao DELETE. O ultimo
  valor fica preservado; isso nao e historico completo nem prova radio inexistente.
- Recebimentos antigos por AP ou mudancas no mesmo recebimento sao recusados.
  Reaparecimento de AP ausente exige recebimento mais recente.
- Publicacao sem fuso e comparada apenas como declarada, sem converter para UTC.
  Troca entre publicacao com/sem fuso exige revisao. Publicacao/captura regressiva
  ou mesmo horario com conteudo diferente tambem bloqueia gravacao.
- Configuracoes e estatisticas continuam separadas; nenhum vinculo pela banda,
  posicao ou nome de AP. Metricas ausentes continuam NULL, zero informado e zero.
  Recebimento nao vira data de medicao, que permanece desconhecida.
- Destino/controladora/site/MAC existentes devem conferir; nenhum vinculo e
  corrigido automaticamente. Pais sao protegidos por locks SHARE curtos.
- Mesmo advisory lock da carga inicial; uma transacao, timeouts, parametros SQL
  e leitura integral de retorno. Sucesso somente apos commit do contexto.
- Permissoes adicionais UPDATE limitadas as tres tabelas RF e ao marcador;
  sem DELETE, sem permissao nova de escrita no inventario ou na fonte inicial.
- Testes locais sinteticos, incluindo falha de commit e mensagens sanitizadas.
  DDL ainda nao executado em PostgreSQL local; validacao real sera no Rigel.

## Homologacao manual concluida

Backup anterior a 028: sentinel-antes-sync-radios-unifi-20261119-161808-165.dump,
236781 bytes, listagem validada. Migracao 028 terminou com COMMIT.
Marcador inicializado com a captura original e conferencia integral positiva.

Nova captura: sync-radios-unifi-20261119-162148-160/radios-unifi.json,
digest 2136bda6e05a934c2256a61b2d160758f323fd5d953b923540ee10cf043fe245.
Apos aplicacao, conferencia somente leitura confirmou conteudo_atual_confere e
conteudo_ja_sincronizado true; ultima captura 2026-11-19T16:21:48.958530-03:00,
216 recebimentos, 453 configuracoes e 425 estatisticas presentes/preservadas.
Sem conflitos, regressao de horarios ou mudanca de vinculos; 16 tx_retry ausentes.

## Automatizacao opcional homologada

services/operational_ap_radios.py e iniciado por run_web_service.py em thread
daemon, independente das requisicoes HTTP. Cada ciclo espera 300 segundos apos
terminar; um processo usa trava de arquivo e a transacao usa o advisory lock RF.
Nao necessita nova migracao alem da 028 ja aplicada.

Desabilitado por padrao. Somente RIGEL com enabled booleano true no arquivo
instance/operational-postgres-ap-radios-shadow.json permite leitura da fonte e
conexao SQL. Flag ausente/invalida/string true nao habilita. Aceita BOM UTF-8
do PowerShell. Nao criar essa flag em outra maquina.

O worker le data/unifi.json, monta a mesma captura validada em memoria e faz
leitura dupla para detectar alteracao. Nao consulta APs/controladora, nao executa
coletor nem exporta uma nova captura bruta em disco. Usa o escritor manual ja
homologado, sem relaxar os bloqueios por identidade/horarios/conflitos. Mudancas
legitimas de site exigem revisao; o worker nao corrige vinculos para passar.

Antes de ativar, apos pull, executar somente leitura:

```powershell
& 'C:\Automacao\.venv31410\Scripts\python.exe' `
    'C:\Automacao\scripts\database\sync_ap_radio_catalog.py' --current
```

--current nao permite --apply. Mostra a flag configurada, nao a saude da thread.
Cada leitura gera um capturado_em novo: conteudo_ja_sincronizado=false pode ser
normal mesmo com conteudo_atual_confere=true. Revisar todos os bloqueios antes
de habilitar; dados novos podem legitimamente diferir dos persistidos.

Somente apos essa conferencia, habilitar {"enabled":true} na flag e combinar
reinicio do servico web em janela sem checklist/jobs ativos. Nao reiniciar PG.
Publicar codigo por si so nao habilita; processo antigo precisa carregar o worker.

Apos commit, status atomico e sanitizado e publicado em
output/ap_radios_postgres_sync_status.json, com modo, contagens, hashes,
capturado_em, confirmado_em_utc e sincronizacao_automatica_radios=true. Sem
nomes, MACs, IPs ou respostas brutas. Conferir primeira publicacao e avancos de
capturado_em/confirmado_em_utc em dois ciclos separados por pelo menos 5 minutos.
Nova captura nao significa nova medicao: sem_data_de_medicao continua preservado.

Falha deixa o ultimo status de sucesso intacto; nao confundir arquivo antigo
com ciclo recente. Warning sanitizado: falha_sincronizacao_radios_unifi, procurar
tambem logs/web_task_stderr.log. Se SQL confirmar mas publicacao do status falhar,
proximo ciclo reconcilia normalmente; nao repetir carga inicial.

Para interromper proximos ciclos, mudar a flag para {"enabled":false}; flag e
revalidada antes da conexao e antes de sair da transacao. Nao desfaz commits ja
concluidos. Preservar dados SQL e fontes/capturas anteriores.

## Evidencias de recorrencia e conteudo (23/11/2026)

Saidas de producao fornecidas pelo operador:

- Primeiro ciclo automatico: capturado_em 2026-11-19T19:29:16.272814+00:00;
  confirmado_em_utc 2026-11-19T19:29:19.761217+00:00, modo sincronizado.
- Ciclo posterior: capturado_em 2026-11-23T10:52:22.721724+00:00;
  confirmado_em_utc 2026-11-23T10:52:27.430181+00:00, modo sincronizado e
  sincronizacao_automatica_radios=true. Confirma nova execucao apos o primeiro
  ciclo; nao demonstra ausencia de falhas em todos os ciclos intermediarios.
- Conferencia --current em 2026-11-23T10:54:48.865336+00:00: destino e fonte
  compativeis, conteudo_atual_confere=true; zero sites/APs ausentes, mudancas
  de site, conflitos ou regressao de publicacao/captura/recebimento.
- 216 recebimentos, 453 configuracoes e 425 estatisticas presentes/preservadas;
  39 sites, 409 tx_retry informados e 16 ausentes. Os 216 APs seguem sem data
  de medicao confirmada; nao houve associacao automatica entre as tabelas.

Na conferencia, ultima_captura_sincronizada=2026-11-23T07:52:22.721724-03:00
e conteudo_ja_sincronizado=false. Este false corresponde ao novo envelope de
captura gerado pelo --current, nao a divergencia das linhas: a igualdade integral
do conteudo foi confirmada separadamente. Nao repetir --apply por esse motivo.

Etapa RF encerrada com base nessas evidencias, sem nova migracao ou alteracao
de dados nesta verificacao. As telas continuam lendo suas fontes anteriores.
