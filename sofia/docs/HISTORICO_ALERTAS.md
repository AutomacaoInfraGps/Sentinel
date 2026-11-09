# Estado atual e historico de alertas

## Comportamento

As funcoes atuais `get_alert_summary` e `list_active_alerts` continuam lendo o
estado ativo. A migracao 010 adiciona um registro separado de transicoes:

- `baseline`: alerta ja ativo quando o acompanhamento foi instalado;
- `opened`: alerta observado ativo pela primeira vez ou depois de recuperado;
- `changed`: mudanca de quantidade ou dos campos operacionais de um alerta ativo;
- `recovered`: alerta deixou de aparecer num snapshot completo e valido.

Os horarios sao de observacao do Sentinel, nao o instante exato da queda ou da
recuperacao do dispositivo. Alertas sao agregados por categoria/regional, muitas
vezes sem dispositivo identificado. `quantity` nao identifica equipamentos.
Os contadores de `summary` do historico contam eventos, nao equipamentos nem a
soma das quantidades. Um mesmo agregado pode abrir varias vezes.

Nao ha reconstrucao retroativa: snapshots antigos inativos nao geram eventos.
Baselines ficam fora da consulta historica padrao. Leituras identicas nao
duplicam eventos; sincronizacoes antigas/repetidas sao ignoradas; transacao e
bloqueio da linha de controle serializam os snapshots completos.

A API do Sentinel passa a recusar snapshots vencidos ou com mais de 100 alertas,
em vez de enviar um subconjunto que poderia provocar falsas recuperacoes.
No workflow de sincronizacao, mantenha **On Error: Stop Workflow** e sincronize
somente respostas HTTP 200 com `success=true`, `snapshot.fresh=true` e
`truncated=false`. Nao converter uma falha de coleta em array vazio.
Ausencia pode significar supressao por manutencao: o historico demonstra a
transicao observada do alerta, nao prova sozinho a recuperacao fisica do link.

## Privilegios e consulta

`sofia_runtime` continua sem CREATE e sem acesso direto as tabelas do historico.
Ele usa somente a funcao fechada `sofia.get_alert_history`. A gravacao ocorre
automaticamente pelo trigger durante a sincronizacao controlada. O modelo nao
recebe ferramenta de escrita. Nenhuma porta, credencial ou acesso de rede novo
e necessario para esta entrega.

Assinatura da consulta:

```sql
SELECT sofia.get_alert_history(
    $1::jsonb, $2::timestamptz, $3::timestamptz,
    nullif($4::text, ''), nullif($5::text, ''), $6::integer
) AS context;
```

Parametros: regionais autorizadas, inicio inclusivo, fim exclusivo, regional
opcional, tipo de evento opcional e limite de 1 a 50. Periodo maximo de 31 dias.
Escopo vazio retorna vazio. A regional de filtro precisa estar no escopo;
nunca ha fallback para todas as regionais. Os valores sao parametrizados.

A resposta inclui `tracking_started_at`, `period_starts_before_tracking`,
`last_snapshot_at`, `snapshot_fresh`, resumo, eventos, contadores e `truncated`.
`truncated` refere-se a paginacao, nao comprova cobertura continua de coleta.
Quedas e recuperacoes entre duas coletas podem nao ser observadas. Falhas de
sincronizacao tambem deixam lacunas; nao declarar historico completo com base
apenas em uma lista vazia.

## Contexto temporal autenticado

O Sentinel envia `body.query_context` com `query_started_at` e
`previous_answered_message_started_at`. O segundo campo corresponde ao inicio
da ultima mensagem respondida com sucesso nessa conversa, usuario e escopo;
nao comprova que uma ferramenta operacional foi consultada naquela mensagem.
Mensagens com erro/canceladas nao avancam o marcador. Respostas fora de ordem
nao retrocedem o horario. Nova conversa ou novo escopo nao reutilizam o cursor.
O cursor contem somente metadados, expira em 24 horas e nao contem prompts.

Para "desde minha ultima pergunta", use essa referencia se presente e avise se
o periodo comeca antes do acompanhamento. Se ausente ou ambiguo, peca o periodo;
nao invente um horario a partir da memoria textual.

## Workflow n8n pronto para importar

Arquivo: `sofia/n8n/consultar_historico_alertas.json`.

1. Importe como novo workflow **SofIA Tool - Consultar Historico de Alertas**.
2. No no Postgres, escolha a credencial operacional `sofia_runtime`, nunca a de
   memoria e nunca postgres. O arquivo nao inclui credenciais ou IDs privados.
3. Salve e publique. A importacao local nao altera o n8n do Celeno.
4. No agente principal, adicione **Call n8n Workflow Tool** e selecione esse workflow.
5. Descricao sugerida:

```text
Consulta aberturas, recuperacoes e mudancas de alertas observadas pelo Sentinel
em um periodo. Use para perguntas de historico, recorrencia, alertas que ja
normalizaram ou mudancas desde outra pergunta. Para estado atual, use a ferramenta
de alertas ativos. Retorna eventos agregados, cobertura temporal e paginacao.
Nunca interpretar historico vazio como ausencia de alertas ativos.
```

Mapeie `allowed_regionals` como expressao fixa, fora do controle da IA:

```javascript
{{ $('Webhook').first().json.body.allowed_regionals }}
```

Os demais campos podem usar `$fromAI`:

```javascript
{{ $fromAI('start_at', 'Inicio inclusivo em ISO 8601 com fuso. Use o periodo pedido; para desde minha ultima pergunta use previous_answered_message_started_at do contexto autenticado. Nao invente quando ausente.', 'string') }}
{{ $fromAI('end_at', 'Fim exclusivo em ISO 8601 com fuso. Para ate agora use query_started_at do contexto autenticado.', 'string') }}
{{ $fromAI('regional', 'Codigo exato de uma regional autorizada; vazio para todo o escopo autorizado.', 'string', '') }}
{{ $fromAI('event_type', 'opened para novos, recovered para recuperados, changed para mudancas; vazio para todos esses eventos. baseline somente quando solicitado o estado inicial.', 'string', '') }}
{{ $fromAI('limit', 'Limite entre 1 e 50 eventos. Use 20 por padrao.', 'number', 20) }}
```

Acrescente ao User Message, preservando os blocos atuais, a referencia temporal:

```javascript
REFERENCIA TEMPORAL DO SENTINEL:
${JSON.stringify($('Webhook').first().json.body.query_context ?? {})}
```

O trecho acima fica dentro da template string JavaScript existente no prompt.
Os nomes `query_started_at` e `previous_answered_message_started_at` sao
referencias internas; nao precisam ser repetidos na resposta.

Acrescente estas regras ao System Message:

```text
- Diferencie estado atual de historico. Consulte a ferramenta apropriada a cada
  pergunta operacional; nao use memoria de conversa como fonte de estado atual.
- Para eventos no periodo, use a ferramenta de historico. Para dizer que um
  alerta continua ativo agora, consulte tambem a ferramenta de estado atual.
- Uma lista de eventos vazia nao significa que nao existem alertas ativos.
- Os horarios historicos representam observacoes do Sentinel, nao instantes
  exatos de queda ou recuperacao. Recuperacao significa ausencia no snapshot
  valido seguinte; nao conclua a causa ou a recuperacao fisica sem evidencia.
- Nao apresente baseline como alerta novo. Nao confunda contagem de eventos
  com quantidade de equipamentos ou ocorrencias agregadas.
- Se o periodo comecar antes de tracking_started_at, informe que o historico
  disponivel comeca naquela data. Se snapshot_fresh=false, informe a defasagem.
- Se truncated=true, apresente como resultado parcial, sem alegar lista completa.
- Use o fuso America/Sao_Paulo nas respostas. Nao invente periodos ou prometa
  monitoramento proativo: esta entrega responde a consultas solicitadas.
```

## Validacao e implantacao

Primeiro validar em banco descartavel. `test_alert_history.sql` RECUSA bancos
cujo nome nao comeca com `sofia_history_test_`. O arquivo faz sincronizacoes
sinteticas e termina com ROLLBACK; nao deve ser executado no banco de producao.
Aplicar no banco de teste somente 001, 002, 003, 004, 009 e 010; as migracoes de
memoria 005-008 configuram a credencial para o banco sofia e nao pertencem a este teste.
Nao apagar nem recriar roles compartilhadas para executar os testes.

A suite `tests/manual/sofia_history_sql_test.mjs` executa a mesma verificacao
em PostgreSQL embarcado PGlite, sem producao, mais baseline e reaplicacao.
A dependencia e somente de desenvolvimento; nao entra no runtime do Sentinel.
Use `PGLITE_MODULE` com o URL file:// do modulo instalado ou instale PGlite no
ambiente de desenvolvimento. Nenhum dado real e enviado ao engine de teste.

Primeiro implantar as alteracoes Python no Rigel, reiniciar o processo web e
confirmar que falhas HTTP da sincronizacao interrompem o workflow antes do SQL.
Essa protecao deve estar ativa antes de iniciar a gravacao historica.

No Celeno, guardar backup privado de `sofia` antes de aplicar 010, usando
`pg_dump -Fc`. Aplicar a migracao como administrador PostgreSQL, apos a 009,
preferencialmente com a sincronizacao parada durante a alteracao. Ela e
transacional e pode ser reaplicada sem apagar os eventos.

Executar `verify_alert_history.sql` em producao para verificar os metadados e
privilegios sem alterar dados. Todos os indicadores de acesso direto devem ser
falsos. A verificacao de REG_PARA pode retornar zero eventos enquanto nao
houver transicoes reais apos a instalacao; isso nao indica falha.

Publicar a nova ferramenta e as regras do agente no n8n. Testar com dados reais observados:
estado ativo e historico precisam ser consultados separadamente.

Historico persistente nao e treinamento do modelo. Nesta entrega nao existe
purga automatica nem avisos proativos. Definir a politica de retencao e a rotina
administrativa antes de uso prolongado; o runtime nao recebe DELETE nos eventos.
