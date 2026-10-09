# Banco da SofIA

## Separacao

O banco `sofia` e separado do banco interno `n8n`. Ele pode usar a mesma
instancia PostgreSQL do Celeno, mas possui banco, proprietario e credencial de
runtime proprios:

- `sofia_owner`: `NOLOGIN`, proprietario do schema e das tabelas;
- `sofia_runtime`: `LOGIN`, usado pelo n8n somente para as operacoes permitidas;
- `n8n`: continua exclusivo para o funcionamento interno do n8n.

O PostgreSQL nao deve publicar a porta 5432 na rede. O acesso do n8n ocorre pela
rede Docker privada.

## Dados da primeira fase

- `alert_snapshots`: estado minimo dos alertas, sem payload bruto ou mensagem
  completa;
- `audit_events`: trilha append-only para eventos de seguranca e autorizacao;
- `llm_interactions`: apenas metadados, intencao normalizada e resultado. Prompt
  e resposta completos nao sao armazenados;
- `schema_migrations`: versao aplicada.

O usuario `sofia_runtime` nao possui `DELETE`. Ele pode atualizar somente os
snapshots por meio da funcao `sync_alert_snapshots`; ele nao pode alterar a
auditoria nem escrever diretamente na tabela de snapshots.

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
\password sofia_runtime
CREATE DATABASE sofia OWNER sofia_owner ENCODING 'UTF8' TEMPLATE template0;
REVOKE ALL ON DATABASE sofia FROM PUBLIC;
GRANT CONNECT ON DATABASE sofia TO sofia_runtime;
```

O comando `\password` solicita a senha de forma interativa. Armazene-a em um
Docker secret separado e na credencial PostgreSQL criptografada do n8n.

Depois, conectado ao banco `sofia` como administrador, aplique os arquivos de
`migrations/` em ordem. Cada migração usa `ON_ERROR_STOP` e transacao; qualquer
erro cancela a alteracao inteira.

Antes de liberar um workflow, confira que `sofia_runtime` nao e membro de
`sofia_owner`, nao e superusuario e nao possui permissao sobre o banco `n8n`.
