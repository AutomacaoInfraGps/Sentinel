# Banco da SofIA

## Separacao

O banco `sofia` e separado do banco interno `n8n`. Ele pode usar a mesma
instancia PostgreSQL do Celeno, mas possui banco, proprietario e credencial de
runtime proprios:

- `sofia_owner`: `NOLOGIN`, proprietario do schema e das tabelas;
- `sofia_runtime`: `LOGIN`, usado pelo n8n somente para as operacoes permitidas;
- `sofia_memory`: `LOGIN`, usado exclusivamente pelo no de memoria do n8n;
- `n8n`: continua exclusivo para o funcionamento interno do n8n.

O PostgreSQL nao deve publicar a porta 5432 na rede. O acesso do n8n ocorre pela
rede Docker privada.

## Dados da primeira fase

- `alert_snapshots`: estado minimo dos alertas, sem payload bruto ou mensagem
  completa;
- `audit_events`: trilha append-only para eventos de seguranca e autorizacao;
- `llm_interactions`: apenas metadados, intencao normalizada e resultado. Prompt
  e resposta completos nao sao armazenados;
- `sofia_chat_history`: memoria curta do agente, separada por `conversation_id`.
  Esta tabela armazena o texto das interacoes para permitir continuidade entre
  mensagens e, por isso, deve ter retencao limitada e acesso restrito;
- `schema_migrations`: versao aplicada.

O usuario `sofia_runtime` nao possui `DELETE`. Ele pode atualizar somente os
snapshots por meio da funcao `sync_alert_snapshots`; ele nao pode alterar a
auditoria nem escrever diretamente na tabela de snapshots.

A unica excecao de exclusao e `sofia_chat_history`, necessaria para limpar a
memoria de uma sessao. O runtime nao recebe `CREATE` no schema: a tabela de
memoria e criada previamente pela migracao `005_chat_memory.sql`.

A partir da migracao `006_isolated_chat_memory.sql`, o no Postgres Chat Memory
deve usar a credencial `sofia_memory`. Essa conta recebe `CREATE` somente no
schema isolado `sofia_memory`, pois o no executa `CREATE TABLE IF NOT EXISTS`
ao inicializar. Ela nao recebe `USAGE` no schema operacional `sofia`. O nome da
tabela no workflow deve ser fixo e nunca pode vir do prompt ou de `$fromAI`.
Apos validar a nova credencial no workflow, aplique
`007_revoke_shared_memory_create.sql` para retirar o grant temporario de
`sofia_runtime` sem interromper o chat durante a troca.

A funcao aceita no maximo 100 alertas, valida os campos, calcula SHA-256 dentro
do PostgreSQL e desativa snapshots ausentes na leitura atual. O JSON recebido
nao e persistido.

A leitura tambem ocorre por uma API SQL fechada. `get_alert_summary` devolve
somente contagens e a data da ultima observacao. `list_active_alerts` devolve no
maximo 50 alertas com os campos operacionais minimos e pode limitar o resultado
por regional. O usuario de runtime nao possui `SELECT` direto em
`alert_snapshots`.

A migracao `004_map_alert_alignment.sql` alinha o snapshot com o agregado exibido
no mapa. Cada alerta inclui `quantity`, e o resumo soma as ocorrencias nas faixas
`critical`, `high`, `medium` e `attention` em vez de contar dispositivos.

## Criacao segura

Execute a preparacao com o administrador PostgreSQL do container. Nao coloque a
senha em comando, Compose, Git ou historico do shell.

```sql
CREATE ROLE sofia_owner NOLOGIN;
CREATE ROLE sofia_runtime LOGIN;
CREATE ROLE sofia_memory LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
\password sofia_runtime
\password sofia_memory
CREATE DATABASE sofia OWNER sofia_owner ENCODING 'UTF8' TEMPLATE template0;
REVOKE ALL ON DATABASE sofia FROM PUBLIC;
GRANT CONNECT ON DATABASE sofia TO sofia_runtime;
GRANT CONNECT ON DATABASE sofia TO sofia_memory;
```

O comando `\password` solicita a senha de forma interativa. Armazene-a em um
Docker secret separado e na credencial PostgreSQL criptografada do n8n.

Depois, conectado ao banco `sofia` como administrador, aplique os arquivos de
`migrations/` em ordem. Cada migracao usa `ON_ERROR_STOP` e transacao; qualquer
erro cancela a alteracao inteira. Na atualizacao de uma instalacao existente,
aplique a `006`, troque e teste a credencial de memoria no n8n e somente entao
aplique a `007`.

Antes de aplicar a migracao `006`, crie `sofia_memory` e defina sua senha de
forma interativa. No n8n, crie uma credencial PostgreSQL exclusiva com banco
`sofia`, usuario `sofia_memory` e schema `sofia_memory`. Nao reutilize essa
credencial em ferramentas do agente.

Antes de liberar um workflow, confira que `sofia_runtime` e `sofia_memory` nao
sao membros de `sofia_owner`, nao sao superusuarios e nao possuem permissao
sobre o banco `n8n`.
