# SofIA - Assistente do Sentinel

A SofIA e a assistente virtual do Sentinel. O objetivo e ajudar o usuario logado a consultar informacoes do ambiente e, no futuro, orquestrar acoes controladas com seguranca, permissao e auditoria.

## Direcao alinhada em 12/11/2026

O objetivo acordado e retomar um **AI Agent local com memoria, ferramentas autorizadas e RAG**, sem acesso externo durante a operacao. A comunicacao interna necessaria com Ollama, memoria e Sentinel permanece controlada. O servidor atual e temporario e nao define o limite de capacidade pretendido. Mudancas dessa arquitetura precisam de alinhamento explicito. Consulte [Arquitetura alvo da SofIA](../docs/SOFIA_ARQUITETURA_ALVO.md) antes de preparar novas alteracoes.

As secoes seguintes descrevem a implementacao existente e o historico, nao uma publicacao dessa retomada. O gerador atual de planos JSON nao implementa a arquitetura alvo. RAG continua no escopo aprovado e ainda precisa ser integrado e homologado.

O gerador separado `n8n/build_agent_workflow.py` prepara uma copia desativada com AI Agent, memoria e ferramentas, sem sobrescrever o workflow atual. Consulte [Homologacao do agente local](../docs/SOFIA_AGENTE_LOCAL_HOMOLOGACAO.md) antes de importar ou executar o candidato. A recuperacao RAG ainda nao esta conectada.

O usuario autorizou depois a troca do workflow atual, preservando ID, webhook, pagina e permissoes. O modo explicito `--update-existing --expected-id` prepara essa atualizacao e um backup local, sem publicar automaticamente. Consulte [Atualizacao do agente local](../docs/SOFIA_AGENTE_LOCAL_ATUALIZACAO.md). Nao e necessario criar uma pagina nova para essa estrategia.

## Arquitetura atual — revisão de 10/11/2026

O chat autenticado chama o n8n por `routes.py` e `n8n_client.py`. O nó `Interpretar pedido` consulta o Ollama local para produzir um plano JSON ou uma resposta social. O nó `Validar plano` confere a estrutura e os filtros. As consultas passam pelo subworkflow e pelo endpoint `/api/internal/sofia/v1/assistant/query`.

O Sentinel valida o plano e o escopo assinado, consulta o inventário e formata contagens e listas em `query_response.py`. A resposta operacional usa os dados da coleta. O modelo redige as respostas sociais. A memória curta fica no Postgres isolado, com sessões `:v4`.

### Mapa de arquivos

| Arquivo ou pasta | Uso no fluxo atual |
| --- | --- |
| `routes.py`, `n8n_client.py` | Chat autenticado e chamada ao webhook |
| `chat_requests.py`, `execution_control.py` | Resultados assíncronos e cancelamento |
| `user_context.py`, `memory_scope.py`, `scope_token.py` | Identidade e escopo da conversa e das consultas |
| `permissions.py`, `service_auth.py`, `audit.py` | Autorização, autenticação de serviço e auditoria |
| `service_routes.py`, `query_response.py` | API de consulta controlada, validação e redação operacional |
| `operational_inventory.py`, `map_alerts.py`, `tools_sentinel.py` | Fontes e adaptadores de consulta, incluindo rotas anteriores |
| `n8n/plan_prompt.txt` | Instruções do modelo usadas pelo gerador de workflow |
| `n8n/validate_plan.js` | Fonte da expressão de validação instalada no n8n |
| `n8n/build_readonly_workflows.py` | Geração dos candidatos privados de workflows |
| `database/` | Migrações e verificações do Postgres |
| `engine.py` | Motor histórico do MVP, ainda importado por testes. O chat atual chama `n8n_client.py` |
| `knowledge/` | Documentos locais e material do MVP. A consulta RAG ainda precisa de integração ao fluxo controlado |

### Código local, Git e n8n

O VS Code exibe os arquivos desta cópia do repositório. Alterações locais precisam de revisão, commit e push para serem versionadas. O Rigel precisa receber a revisão e reiniciar o serviço para carregar mudanças Python.

Editar `plan_prompt.txt` modifica a fonte usada na próxima geração. Para aplicar essas instruções no n8n, gere os candidatos, revise as diferenças e importe e publique a versão desejada. Editar uma expressão diretamente no editor do n8n salva a configuração no Celeno. Essa edição precisa ser reconciliada com o gerador local para ser reproduzível.

Os candidatos ficam em `instance/sofia-workflows/`, ignorada pelo Git. Exports podem conter dados sensíveis e devem permanecer privados. Uma nova geração parte dos exports fornecidos e pode sobrescrever ajustes manuais quando importada. Use exports atuais e preserve um backup antes de atualizar.

A redação de contagens e listas fica em `query_response.py`. Alterar essa redação exige implantar o código no Rigel. O prompt do modelo permanece responsável pela interpretação e pela conversa social.

### Estado da revisão

O usuário confirmou contagem e listagem de APs offline, consultas de switches e VPNs e totais de APs e servidores no fluxo controlado. A redação mais natural foi implementada e testada localmente e ainda depende de implantação no Rigel. A personalização de identidade requer nova homologação. Histórico de abertura e recuperação, RAG e replicação AD ainda precisam de adaptadores no fluxo controlado.

O guia de implantação contém os comandos e a lista de verificações. [Workflow controlado](../docs/SOFIA_WORKFLOW_CONTROLADO.md)

## Referência histórica do MVP

As seções abaixo preservam o desenho anterior baseado em `engine.py`. Use o mapa acima para localizar a implementação atual e o guia de implantação para atualizar os workflows.

## Principio Principal

A SofIA nao deve executar uma acao real apenas porque o usuario pediu.

O modelo correto e:

```text
Usuario logado
  -> Chat SofIA
  -> API Flask
  -> Autenticacao
  -> Autorizacao/RBAC
  -> Orquestrador
  -> Ferramentas permitidas
  -> Auditoria
```

Regra de ouro:

```text
IA entende a intencao.
Sistema valida permissao.
Executor realiza a acao.
Auditoria registra tudo.
```

## Estado Atual

A versao atual e um MVP seguro e somente leitura.

Ela ja possui:

- Widget de chat no Sentinel.
- Rota autenticada `POST /api/sofia/chat`.
- Uso do usuario ja logado no Flask.
- Identidade AD preservada no modelo de usuario (`dn` e `groups`).
- Validacao basica de permissao.
- Rate limit por usuario.
- Validacao de origem da requisicao.
- Logs de auditoria em JSONL.
- Respostas deterministicas, sem LLM externo.
- Consultas somente leitura sobre dados ja carregados no Sentinel.
- API interna regional com escopo assinado, projecao sanitizada e consulta sob demanda.
- Historico da conversa preservado no navegador durante a sessao da aba.

Ela ainda nao executa:

- Reset de senha.
- Desbloqueio de conta.
- Alteracao de grupos.
- Comandos em servidores.
- Acoes no Active Directory.
- Acoes em FortiGate, FortiManager, FortiAnalyzer ou Zabbix.

## Estrutura da Pasta

```text
sofia/
|-- __init__.py          # Registro do blueprint Flask
|-- routes.py            # API autenticada da SofIA
|-- engine.py            # Orquestracao deterministica do MVP
|-- permissions.py       # Fronteira de autorizacao
|-- permissions_matrix.json
|-- tools_sentinel.py    # Ferramentas read-only para dados do Sentinel
|-- audit.py             # Auditoria em logs/sofia_audit.jsonl
|-- README.md            # Documentacao do modulo
|-- ARQUITETURA_FASES_3_4.md # Evolucao segura com LLM, n8n, WhatsApp e acoes
|-- PERMISSOES.md
|-- PERGUNTAS_SUPORTADAS.md
|-- knowledge/           # Base de conhecimento por tema
```

Arquivos relacionados fora da pasta:

```text
templates/components/sofia_chat.html
static/sofia/sofia.js
static/sofia/sofia.css
environment.json
logs/sofia_audit.jsonl
```

## Ativacao

A SofIA e ativada por configuracao local:

```json
{
  "sofia": {
    "enabled": true
  }
}
```

O arquivo `environment.json` deve permanecer local e ignorado pelo Git.

O resumo de alertas usa um webhook privado do n8n por um tunel SSH local. As
credenciais ficam em variaveis de ambiente da maquina, nunca no repositorio:

```text
SENTINEL_SOFIA_N8N_WEBHOOK_URL=http://127.0.0.1:15678/webhook/sofia-alertas-v1
SENTINEL_SOFIA_N8N_WEBHOOK_TOKEN=<token exclusivo do webhook>
```

No Rigel, `scripts/run_sofia_n8n_tunnel.ps1` mantem o encaminhamento local
`127.0.0.1:15678` para o n8n no Celeno. O script deve ser executado por uma
tarefa agendada com a mesma conta proprietaria da chave SSH.

## Seguranca

Antes de qualquer acao futura, a SofIA deve validar:

1. O usuario esta logado?
2. A sessao e valida?
3. O usuario pertence ao grupo autorizado?
4. A acao e permitida para esse cargo/grupo?
5. O alvo esta dentro da OU ou escopo permitido?
6. A acao e de baixo, medio, alto ou critico risco?
7. Precisa de confirmacao, MFA ou aprovacao humana?
8. A execucao usa conta de servico com privilegio minimo?
9. O evento foi auditado?

Para acoes de Active Directory, a conta de servico da SofIA nunca deve ser Domain Admin. Ela deve receber delegacao minima por OU, por exemplo apenas resetar senha e forcar troca no proximo logon quando essa funcao for liberada.

As permissoes humanas e tecnicas ficam em:

```text
sofia/PERMISSOES.md
sofia/permissions_matrix.json
```

Atualmente apenas acoes de baixo risco estao habilitadas. Acoes de AD, execucao e alteracao permanecem desabilitadas.

O plano oficial para evoluir a SofIA com LLM, n8n, WhatsApp e ações reais está
documentado em:

```text
sofia/ARQUITETURA_FASES_3_4.md
```

Esse documento define as fronteiras de confiança, identidade por canal,
confirmação humana, executor isolado, conta técnica, auditoria e critérios que
devem ser atendidos antes de qualquer ação de escrita.

A autenticacao do canal tecnico entre n8n e Sentinel esta documentada em:

```text
sofia/docs/AUTENTICACAO_SERVICO_N8N.md
```

O modelo autenticado preserva a OU no `dn` e os grupos retornados pelo AD. Esses
campos formam a identidade usada pela futura autorizacao por escopo, mas ainda
nao concedem capacidades enquanto as regras correspondentes nao forem
implementadas em `permissions.py`.

## Capacidades Atuais

Hoje a SofIA responde perguntas sobre:

- Quantidade de regionais.
- Resumo de uma regional.
- Servidores e VMs.
- Switches.
- Links de internet.
- Alertas de switches no Zabbix.
- Dashboard do Sentinel.
- VPNs/IPsec apenas como resposta informativa, ainda sem consulta real habilitada.

O agente n8n/Ollama nao recebe os arquivos JSON nem acessa o cofre. Para
consultas regionais, ele usa `POST /api/internal/sofia/v1/regionals/query` com
um token curto emitido pelo Sentinel. Isso limita a resposta ao escopo do
usuario e evita enviar todo o inventario para o contexto do modelo.

O catalogo detalhado fica em:

```text
sofia/PERGUNTAS_SUPORTADAS.md
```

A base de conhecimento por tema fica em:

```text
sofia/knowledge/
```

Exemplos:

```text
Quantas regionais temos?
Resumo da regional ABC
Como estao os servidores da regional Macae?
Tem switches com alerta?
Como estao os links de internet?
```

## Auditoria

Os eventos sao registrados em:

```text
logs/sofia_audit.jsonl
```

O log registra metadados, nao o conteudo integral da conversa:

- timestamp
- usuario
- acao
- status
- tamanho da mensagem
- endereco remoto
- detalhe resumido quando aplicavel

Isso reduz risco de vazamento de informacoes sensiveis em log.

O historico visual do chat fica apenas no `sessionStorage` do navegador, separado por usuario logado. Ele serve para nao perder a conversa ao navegar entre paginas do Sentinel e pode ser limpo pelo botao de lixeira no widget.

## Roadmap

### Fase 1 - MVP Seguro

Objetivo: chat interno sem execucao de acoes reais.

- Chat no Flask.
- Usuario logado reaproveitado.
- Respostas sobre o Sentinel.
- Logs basicos.
- Permissoes basicas.
- Sem acoes no AD.

Status: em andamento.

### Fase 2 - Consulta AD

Objetivo: permitir consulta controlada e read-only ao Active Directory.

- Buscar usuario.
- Ver grupos.
- Ver OU.
- Ver status bloqueado.
- Ver expiracao de senha.
- Ver informacoes basicas permitidas.

Sem alteracao de conta nessa fase.

### Fase 3 - Acoes Simples com Controle

Objetivo: liberar operacoes de medio risco com validacao forte.

- Reset de senha.
- Desbloqueio de conta.
- Forcar troca de senha no proximo logon.
- Validacao por grupo/cargo.
- Validacao por OU.
- Confirmacao obrigatoria.
- Auditoria completa.

### Fase 4 - Aprovacao e Integracoes

Objetivo: ampliar a operacao com aprovacao humana e integracoes.

- Abertura de chamados.
- Envio de e-mail.
- Notificacao para gestao/acessos.
- Aprovacao humana para alto risco.
- Integracao com Zabbix, FortiAnalyzer e demais fontes internas.

### Fase 5 - Agente Corporativo

Objetivo: tornar a SofIA uma camada de atendimento e automacao governada.

- Base de conhecimento interna.
- Memoria controlada.
- Painel de auditoria.
- Gestao de permissoes pela interface.
- Fluxos automatizados aprovados.

## Regras Para Desenvolvimento

Ao adicionar uma nova capacidade:

1. Criar a intencao no `engine.py`.
2. Validar permissao em `permissions.py`.
3. Usar ferramenta allowlisted.
4. Nunca executar comando arbitrario vindo do usuario.
5. Registrar auditoria.
6. Retornar mensagem clara para o usuario.
7. Para acoes reais, exigir confirmacao e/ou aprovacao.

## Nao Fazer

- Nao dar autonomia direta para a IA.
- Nao executar comandos livres gerados por prompt.
- Nao usar credenciais pessoais.
- Nao armazenar conversa completa em logs sem necessidade.
- Nao consultar ou alterar AD sem RBAC.
- Nao misturar decisao de permissao dentro do modelo de IA.
- Nao versionar `environment.json`, tokens, secrets ou chaves.

## Proximo Passo Recomendado

Antes de liberar qualquer acao real, evoluir a Fase 1:

- Criar uma pequena base de conhecimento interna.
- Mapear perguntas frequentes.
- Melhorar respostas estruturadas.
- Criar testes para `engine.py`.
- Criar uma matriz inicial de permissoes para futuras consultas AD.

## Testes

Os testes unitarios da SofIA ficam em:

```text
tests/unit/test_sofia_engine.py
```

Para executar:

```powershell
.\venv\Scripts\python.exe -m unittest tests.unit.test_sofia_engine
```

Esses testes validam:

- saudacao;
- total de regionais;
- resumo de regional;
- status de links;
- alertas de switches;
- respostas explicativas via `sofia/knowledge/`;
- regras basicas de seguranca explicativa.
- matriz de permissoes;
- bloqueio de acoes futuras/desabilitadas.
