# Parar uma consulta da SofIA

O botao com icone quadrado de stop (nome acessivel **Parar consulta**) aparece enquanto ha uma consulta em andamento, na pagina
dedicada e no widget. Ele interrompe a espera no navegador, descarta respostas
atrasadas e solicita ao Sentinel a parada da execucao correspondente.
O navegador nunca recebe a chave administrativa da API do n8n.

**Estado da entrega:** interface e integracao implementadas e testadas com
servicos simulados. Para parar a execucao real, configure os itens abaixo no
ambiente e publique a alteracao do workflow. Sem isso, a interface informa que
a parada no n8n nao foi confirmada; fechar a conexao HTTP nao significa parar
o processamento remoto.

## 1. Configuracao privada do Sentinel

No ambiente do processo que inicia o Sentinel:

| Variavel | Valor |
| --- | --- |
| `SENTINEL_SOFIA_N8N_WORKFLOW_ID` | ID exato do workflow principal SofIA V3, obtido na URL do editor |
| `SENTINEL_SOFIA_N8N_API_KEY` | Chave privada da API do n8n |
| `SENTINEL_SOFIA_N8N_API_URL` | Opcional: URL terminada em `/api/v1`; por padrao usa o mesmo servidor/tunel do webhook |

Exemplo de URL sem segredo: `http://127.0.0.1:15678/api/v1`.
Use o tunel privado existente. HTTP fora de localhost e redirecionamentos sao
rejeitados. A chave deve ficar no mecanismo privado de configuracao do servico,
sem Git, HTML, JavaScript, prompts ou mensagens de chat. Se usar cofre/DPAPI,
o inicializador deve resolver a referencia e disponibilizar a variavel ao
processo, como faz com os demais segredos; nao coloque uma referencia de cofre
diretamente no lugar do valor da chave.

Use uma identidade dedicada com acesso ao projeto/workflow da SofIA e somente
leitura de execucoes e parada (`execution:read`, `execution:stop`), quando a
edicao instalada permitir restringir esses escopos. Essas permissoes pertencem
ao integrador do Sentinel, nao ao modelo nem ao usuario do AD. O servidor
verifica o dono da consulta e o workflow antes de solicitar qualquer parada.

Confirme no playground **da instancia instalada** que existem os endpoints
`GET /api/v1/executions/{id}` e `POST /api/v1/executions/{id}/stop`.
Eles constam na [referencia oficial atual](https://docs.n8n.io/connect/n8n-api/executions).
Uma resposta 404/403 nao e tratada como sucesso e nao provoca exclusao de
execucoes ou reinicio de containers como alternativa.

## 2. Registrar a execucao antes de consultar o agente

No workflow principal SofIA V3, adicione um no **HTTP Request** imediatamente
apos `Webhook` e antes de `SofIA - Agente Principal`:

```text
Webhook -> Registrar execucao no Sentinel -> SofIA - Agente Principal
        -> Preparar resposta -> Respond to Webhook
```

Configure:

- Metodo: `POST`.
- URL: mesma origem privada do Sentinel ja usada nas consultas internas,
  com caminho `/api/internal/sofia/v1/executions/register`.
- Enviar corpo: JSON, com os campos abaixo.
- Timeout: 15000 ms. Sem repeticoes automaticas durante a validacao inicial.
- Autenticacao: assinatura HMAC do canal n8n -> Sentinel ja existente.

No modo Expression, o corpo inteiro pode ser:

```javascript
{{ {
  request_id: $('Webhook').first().json.body.request_id,
  execution_id: String($execution.id),
  workflow_id: String($workflow.id)
} }}
```

Assine os **mesmos bytes JSON enviados** usando o protocolo documentado em
[AUTENTICACAO_SERVICO_N8N.md](AUTENTICACAO_SERVICO_N8N.md):
`X-Sentinel-Key-Id`, `X-Sentinel-Timestamp`, `X-Sentinel-Nonce` e
`X-Sentinel-Signature`. A assinatura inclui metodo `POST`, o caminho exato
`/api/internal/sofia/v1/executions/register` e o SHA-256 do corpo.
Nao use o Header Auth do webhook no lugar do HMAC: sao canais diferentes.
Se o fluxo de assinatura existente gera uma string JSON, envie essa string como
corpo Raw com Content-Type `application/json`, evitando serializar novamente.

Mantenha as expressoes do prompt, da memoria e das regionais apontando para
`$('Webhook').first().json.body`, pois a saida do novo no contem apenas o recibo
de registro. Os campos `request_id` e `execution_id` sao metadados do integrador;
nao precisam ser enviados ao modelo.

Resposta de registro esperada: `{"registered":true,"cancelled":false}`.
Registros sem assinatura, sem consulta previa, de outro workflow ou tentando
trocar o ID de uma execucao ja vinculada sao rejeitados.

Publique o workflow e reinicie o processo do Sentinel para carregar o backend
e as variaveis. Nenhuma dessas mudancas foi aplicada automaticamente no Celeno
ou no Rigel durante o desenvolvimento local.

## 3. Validacao real

Antes de testar, diagnostique no Rigel, sem expor a chave:

```powershell
.\.venv31410\Scripts\python.exe -m sofia.execution_control
```

O resultado deve indicar `workflow_configured`, `api_key_configured` e
`configuration_valid` como verdadeiros. Isso verifica o ambiente deste comando;
nao comprova o ambiente herdado pelo processo web ja iniciado.
A chave da API e diferente do token Header Auth do webhook e da chave HMAC.

Com o ID de uma execucao da SofIA, pode-se testar apenas a leitura da API:

```powershell
.\.venv31410\Scripts\python.exe -m sofia.execution_control --execution-id 12345
```

Substitua 12345 pelo ID real. Este comando nao para execucoes, nao mostra
credenciais nem dados de conversa. Espera-se HTTP 200 e `workflow_matches: true`.
HTTP 401/403 exige revisar a chave e os acessos; 404 exige revisar a URL,
existencia do registro e endpoints da versao instalada. Nao confundir essas
falhas com cancelamento confirmado. O log do backend registra o motivo de uma
falha de parada com mensagens controladas, sem corpo da resposta ou chave.

1. Envie uma pergunta que leve alguns segundos para responder.
2. Durante a consulta, clique em **Parar**.
3. Confirme no n8n que aquela execucao ficou com status `canceled`.
4. Confirme que o Sentinel informa a parada e aceita uma nova pergunta.
5. Verifique que uma resposta atrasada nao aparece no chat.
6. Em outra sessao de usuario, confirme que a consulta original nao pode ser
   cancelada por quem nao a iniciou.

O registro SQLite em `instance/sofia_chat_requests.sqlite3` dura dez minutos
e funciona entre threads/processos que compartilham esse arquivo. Guarda
identificadores, dono e estado, sem texto de conversa ou credenciais. Em uma
implantacao com varios servidores Sentinel, use um registro compartilhado
antes de habilitar cancelamento entre essas instancias.

Cancelar o workflow nao desfaz mensagens ja gravadas, acoes ja concluidas nem
garante interromper uma inferencia que o Ollama ja recebeu. A validacao real
deve observar tambem o comportamento do modelo e dos subworkflows em andamento.
O controle nao reinicia nem descarrega modelos compartilhados, pois isso
afetaria consultas de outros usuarios.

## Verificacao local

```powershell
.\venv313\Scripts\python.exe -m unittest tests.unit.sofia_cancellation_test tests.unit.sofia_page_test tests.unit.sofia_n8n_client_test tests.unit.sofia_memory_scope_test
.\venv313\Scripts\python.exe -m tests.manual.sofia_cancel_browser_test
```
