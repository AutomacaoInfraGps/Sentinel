# SofIA - Assistente do Sentinel

A SofIA e a assistente virtual do Sentinel. O objetivo e ajudar o usuario logado a consultar informacoes do ambiente e, no futuro, orquestrar acoes controladas com seguranca, permissao e auditoria.

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
- Validacao basica de permissao.
- Rate limit por usuario.
- Validacao de origem da requisicao.
- Logs de auditoria em JSONL.
- Respostas deterministicas, sem LLM externo.
- Consultas somente leitura sobre dados ja carregados no Sentinel.
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
