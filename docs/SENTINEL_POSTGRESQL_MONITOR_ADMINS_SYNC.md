# Sincronizacao paralela do Monitor de Admins (017)

## Fonte de verdade e limites

O JSON da baseline continua sendo a fonte das aprovacoes. O espelho SQL nunca
aprova usuarios, altera configuracao dos equipamentos ou escreve nesse JSON.
Monitor, botoes, regras de comparacao, consultas Forti e notificacoes seguem
os leitores/escritores atuais. Nenhuma consulta SQL foi inserida nas requisicoes.

Um worker opcional em run_web_service.py verifica os arquivos a cada 300 segundos,
inclusive uma vez na partida. Nao faz chamadas aos equipamentos. So trabalha
no RIGEL com instance/operational-postgres-admins-shadow.json habilitado:

```json
{"enabled":true,"source_timezone":"America/Sao_Paulo"}
```

O arquivo de exemplo esta desabilitado. Sem configuracao habilitada, o worker
nao le fontes nem abre conexao SQL. Precisa rodar na conta Windows com a credencial
DPAPI de sentinel_collector provisionada. Nao mudar a conta do servico.

## Evidencias, presenca e ausencia

017 acrescenta presente_na_fonte nas quatro tabelas de dispositivos/contas e
um marcador por origem, sem DELETE. Linhas historicas ficam retidas.

- Dispositivos: a uniao cache + baseline e o conjunto presente. Equipamentos
  exclusivos da baseline continuam sem identidade/regional inventada. Ausencia
  da uniao marca somente a linha como fora da fonte; demais atributos sao o
  ultimo estado conhecido. Para consultas atuais filtrar presente_na_fonte.
- Observadas: somente uma consulta declarada valida COM ultima_coleta_valida
  explicita pode marcar contas ausentes da lista como fora da fonte. Isso e
  presenca na ultima lista valida, nao comprovacao de exclusao no equipamento.
- Em consultas indisponiveis, parciais, desconhecidas ou sem horario, manter
  contas conhecidas. Reclassificar evidencia como cache_sem_confirmacao_atual;
  as contas retornadas no cache tambem sao preservadas/upsertadas. A coluna
  consulta_valida permanece NULL quando a origem nao declara, inclusive FMG legado.
- A quantidade de observadas no banco pode superar a lista do recibo devido a
  essa retencao. Nao interpretar diferenca como sucesso/falha ou conta removida.
- Baseline: espelhar exclusivamente as entradas do JSON lido/validado. Entradas
  ausentes ficam presente_na_fonte=false; nao inferir aprovacao a partir de contas
  observadas. Uma alteracao da baseline e decisao na fonte, nao do sincronizador.
- Divergencias: espelhar os campos novos/removidos/remocoes_pendentes do cache,
  sem recalcular diferencas ou substituir as regras de duas coletas do Sentinel.
  Mudanca da baseline nao reescreve artificialmente um cache coletado antes dela.

Falhas de leitura, JSON invalido/duplicado, listas invalidas, baseline/cache
global vazio, contradicoes ou fonte alterada durante a operacao bloqueiam a
sincronizacao. Nao inferir ausencia a partir desses erros.

Horario SQL de importacao/leitura nao e horario de aprovacao. Esta etapa nao
cria trilha completa de quem aprovou cada usuario, nem versiona cada mudanca
dos atributos. Registros fora da fonte preservam a ultima evidencia conhecida.
Uma futura tela SQL deve juntar contas ao dispositivo, filtrar presenca atual
e exibir a evidencia; nunca apresentar cache antigo como consulta nova.

## Consistencia e privilegios

Captura rele os quatro arquivos apos montar a projecao e verifica estabilidade.
Usa baseline configurada em fortianalyzer.admin_baseline_file (padrao relativo
admin_baseline.json), cache de admins, cache de firewalls e catalogo regional.
Fuso legado e explicito na captura; depois fica preso ao recibo e a fonte SQL.

Digest normalizado inclui configuracao/caminho real da baseline, fuso, hashes
do cache/baseline, horario da publicacao e todos os registros tipados. Nao muda
so pelo horario de leitura ou por estados de monitoramento irrelevantes nos
arquivos de regionais/firewalls. Os vinculos derivados continuam no digest.

Recibos atomicos contem somente versao, fuso, captura e hashes. Nao contem nomes
de contas, dados brutos, caminhos ou motivos dos equipamentos. Ao carregar um
recibo congelado, as fontes atuais sao lidas e revalidadas, nao reconstruidas
de dados sensiveis no recibo. Alteracao significativa exige nova captura/revisao;
nao editar digest para forcar aplicacao. O recibo nao e assinatura criptografica.

Transacao READ COMMITTED, locks compativeis com os grants, advisory lock compartilhado
com o bootstrap e lock de processo entre CLI e worker. Configuracao divergente,
cache mais antigo que a publicacao ja importada, captura antiga e conflito de
conteudo no mesmo horario sao recusados/ignorados sem recuar o marcador. Ultima
coleta valida individual tambem nao pode regredir nem desaparecer em um novo
registro de cache. Na ausencia completa do equipamento, mantem o historico.

Fontes verificadas antes dos upserts e novamente antes do marcador/commit.
Leituras de dispositivo e baseline conferidas por consultas de linhas, com
retencao adicional permitida apenas nas observacoes sem coleta completa.
Sucesso e impresso somente apos commit. Falha de SQL preserva recibo para
diagnostico; logs mostram somente codigo fixo/SQLSTATE, nunca valores brutos.

Nao e transacao distribuida com os JSONs. Uma edicao apos a ultima verificacao
pode convergir na proxima leitura; uma mudanca que aparece e desaparece entre
polls nao forma historico SQL completo. Advisory lock nao bloqueia escritores
externos que nao sigam o protocolo.

017 concede UPDATE nas tabelas especificas e SELECT/INSERT/UPDATE no marcador
ao coletor, sem DELETE. Leitura do marcador vai apenas para sentinel_admins_reader.
PUBLIC/sentinel_api/sentinel_reader continuam sem acesso a contas administrativas.
Papel SQL tecnico nao aplica escopo regional AD de usuarios da aplicacao.

## Homologacao gradual no Rigel

1. Publicar TODOS os novos arquivos. Conferir sync_admin_catalog.py --help.
2. Fazer novo backup custom do banco ja carregado e validar pg_restore --list.
3. Aplicar somente 017_admin_monitor_shadow_sync.sql como sentinel_admin,
   psql -X com ON_ERROR_STOP=1 em sentinel, loopback:5433. Confirmar COMMIT.
4. Reiniciar somente Sentinel usando restart_web_service.ps1. Nao habilitar o
   worker ainda; a ausencia do arquivo de configuracao mantem o espelho desligado.
5. Capturar sem SQL:

```powershell
& 'C:\Automacao\.venv31410\Scripts\python.exe' `
    'C:\Automacao\scripts\database\sync_admin_catalog.py' `
    --capture --source-timezone America/Sao_Paulo
```

6. Rodar o comando sem argumentos para conferencia SQL sem gravacao. Conferir
   contas/evidencias e dispositivos, inclusive os tres identificadores pendentes
   ja conhecidos. Marcador inicialmente NULL e conteudo_ja_sincronizado=false.
7. Congelar output/admins_postgres_publication.json em arquivo de backup restrito;
   conferir novamente com --publication COPIA.json. O recibo depende da revisao
   atual dos arquivos. Se ocorreu nova coleta/edicao, recapturar e revisar.
8. Aplicar somente esse recibo com --publication COPIA.json --apply
   --expected-digest HASH_EXATO_REVISADO. Repetir sem --apply para validar true.
9. Somente apos conferir o ciclo manual, criar o arquivo de configuracao opt-in
   com enabled=true e source_timezone explicito. Reiniciar apenas Sentinel.
10. Aguardar nova captura e conferir sem --publication/--apply. Nova leitura com
    conteudo_ja_sincronizado=true comprova o ciclo automatico; digest pode continuar
    igual. Consultas reais com falha devem continuar mostrando evidencia antiga.
    Mudancas reais futuras na baseline precisam homologacao propria; nao alterar
    acessos aprovados apenas para testar o sincronizador.

Nao repetir 016 ou a carga inicial. Para interromper novas tentativas, mudar
enabled para false; transacao ja em andamento pode terminar. Nao apagar marcador
ou dados para contornar uma validacao.

## Testes

operational_admin_shadow_test.py usa fontes sinteticas, mocks SQL e runner AST,
sem importar web_config, consultar AD/Forti, abrir credenciais reais ou gravar
em PostgreSQL. Cobre recibos, fontes mutaveis, baseline separada, retencao em
falhas, ausencia somente com evidencia, monotonicidade, pinagem, atomicidade,
conferencia, rollback/commit e opt-in. Nao substitui a validacao da migracao em
PostgreSQL real no Rigel.
