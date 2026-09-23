# Perguntas Suportadas pela SofIA

Este documento registra o que a SofIA entende hoje e o que esta planejado para as proximas fases.

O objetivo e manter uma lista clara entre:

- perguntas ja implementadas;
- perguntas planejadas;
- acoes bloqueadas por seguranca;
- fontes usadas para responder.

## Estado Atual

A SofIA atual e deterministica, somente leitura e nao usa LLM externo.

Motor principal:

```text
sofia/engine.py
```

Para perguntas explicativas, o `engine.py` tambem pode ler a base:

```text
sofia/knowledge/
```

Fontes de dados:

```text
sofia/tools_sentinel.py
estrutura_regionais.json
cache de switches/Zabbix carregado pelo Sentinel
```

## Saudacao

Status: implementado.

Exemplos:

```text
Oi
Ola
Bom dia
Boa tarde
```

Resposta esperada:

```text
Ola, eu sou a SofIA, assistente virtual do Sentinel. Como posso te ajudar?
```

## Ajuda Guiada

Status: implementado.

Quando a SofIA nao entende uma pergunta com seguranca, ela nao tenta inventar resposta. Ela informa que ainda nao entendeu e mostra exemplos reais de perguntas suportadas.

Exemplos de situacoes:

```text
Qual e a cor do sistema?
Me mostre algo que nao existe
Faz uma acao que ainda nao foi liberada
```

Resposta esperada:

- avisa que nao entendeu a pergunta com seguranca;
- sugere perguntas sobre regionais, servidores, links, switches, dashboard e seguranca;
- reforca que a SofIA esta em modo somente leitura.

## Regionais

Status: implementado.

Exemplos:

```text
Quantas regionais temos?
Resumo da regional ABC
Como esta a regional Macae?
Me mostra a regional Campinas
```

O que a SofIA responde:

- total de regionais cadastradas;
- resumo geral de uma regional quando ela identifica o nome/codigo;
- resumo combinado de servidores, links e switches da regional.

Funcoes usadas:

```text
total_regionais()
identificar_regional()
nome_regional()
resumo_servidores()
resumo_links()
resumo_switches()
```

## Servidores e VMs

Status: implementado.

Exemplos:

```text
Como estao os servidores?
Servidores da regional ABC
Tem VM offline na Macae?
Resumo das VMs
```

O que a SofIA responde:

- total de servidores/VMs;
- quantidade online;
- quantidade offline;
- quantidade em warning;
- quantidade inativa;
- quantidade sem status.

Funcoes usadas:

```text
resumo_servidores()
identificar_regional()
nome_regional()
```

## Switches

Status: implementado.

Exemplos:

```text
Como estao os switches?
Switches da regional ABC
Tem switch offline?
Tem alerta de switch?
```

O que a SofIA responde:

- total de switches;
- quantidade online;
- quantidade offline;
- quantidade em warning;
- quantidade inativa;
- quantidade sem status.

Funcoes usadas:

```text
resumo_switches()
alertas_switches_ativos()
identificar_regional()
nome_regional()
```

## Links de Internet

Status: implementado.

Exemplos:

```text
Como estao os links?
Links da regional ABC
Tem link offline?
Resumo dos links de internet
```

O que a SofIA responde:

- total de links;
- quantidade online;
- quantidade offline;
- quantidade inativa;
- quantidade sem status.

Funcoes usadas:

```text
resumo_links()
identificar_regional()
nome_regional()
```

## Zabbix e Alertas

Status: implementado para alertas de switches em cache.

Exemplos:

```text
Tem alertas no Zabbix?
Tem problema de switch?
Alertas da regional ABC
```

O que a SofIA responde:

- se existem alertas ativos de switches no cache;
- lista curta com switch, regional e resumo do alerta.

Funcoes usadas:

```text
alertas_switches_ativos()
identificar_regional()
nome_regional()
```

## Dashboard do Sentinel

Status: implementado com resposta explicativa baseada em `sofia/knowledge/dashboard.md`.

Exemplos:

```text
Me explica o dashboard
Quais telas o Sentinel tem?
O que significa o painel?
```

O que a SofIA responde:

- explica a finalidade do dashboard;
- lista os principais temas que o Sentinel consolida;
- mantem a resposta em modo somente leitura.

## VPNs / IPsec

Status: planejado.

Exemplos:

```text
Como estao as VPNs?
VPN da regional ABC
Tem IPsec offline?
```

Resposta atual:

```text
A consulta real de VPNs ainda nao esta habilitada nesta versao da SofIA.
```

## Acoes Bloqueadas Hoje

Status: bloqueado por seguranca.

A SofIA ainda nao deve executar:

- reset de senha;
- desbloqueio de conta;
- alteracao de grupo no AD;
- criacao de usuario;
- exclusao de usuario;
- comando em servidor;
- alteracao em firewall;
- alteracao em Zabbix;
- qualquer comando arbitrario.

Essas acoes dependem de RBAC, validacao por OU, confirmacao, aprovacao e auditoria completa.

## Perguntas Planejadas

### Active Directory Read-only

Status: planejado.

Exemplos:

```text
Consultar usuario joao.silva
O usuario esta bloqueado?
Quais grupos esse usuario possui?
Qual OU desse usuario?
Quando a senha expira?
```

### Base de Conhecimento

Status: planejado.

Exemplos:

```text
Como faco reset de senha manual?
Qual o procedimento para link offline?
Como validar alerta de switch?
Como funciona o dashboard de certificados?
```

### Chamados

Status: planejado.

Exemplos:

```text
Abrir chamado para link offline
Consultar chamado
Registrar incidente
```

## Regra de Manutencao

Sempre que uma nova intencao for criada em `engine.py`, atualizar este documento.

Sempre que uma nova ferramenta for criada em `tools_sentinel.py` ou em outro modulo da SofIA, registrar:

- nome da capacidade;
- exemplos de pergunta;
- fonte de dados;
- risco;
- status de permissao.
