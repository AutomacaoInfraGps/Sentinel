# Permissoes da SofIA

Este documento define como a SofIA deve tratar permissoes, riscos e escopos.

## Regra Principal

A SofIA nao decide permissao sozinha.

Ela pode entender a intencao do usuario, mas a autorizacao deve ser feita pelo backend do Sentinel.

```text
Usuario pede
  -> SofIA interpreta
  -> permissions.py valida
  -> matriz de permissoes define risco/estado
  -> ferramenta executa somente se permitido
  -> auditoria registra
```

## Estado Atual

Hoje somente acoes de baixo risco e somente leitura estao habilitadas:

- `chat:basic`
- `sentinel:read`
- `knowledge:read`

Todas as acoes de Active Directory, execucao, alteracao e integracao externa devem permanecer desabilitadas ate existirem:

- RBAC por grupo/cargo;
- escopo por OU/regional;
- confirmacao obrigatoria;
- aprovacao humana quando necessario;
- auditoria completa;
- conta de servico com privilegio minimo.

## Niveis de Risco

### Baixo

Consulta ou explicacao sem alteracao de ambiente.

Exemplos:

- responder duvida;
- consultar resumo de links;
- consultar servidores;
- explicar dashboard.

### Medio

Acao operacional reversivel ou controlada.

Exemplos futuros:

- desbloquear conta;
- resetar senha;
- forcar troca no proximo logon.

### Alto

Acao que altera acesso, grupo, permissao ou configuracao sensivel.

Exemplos futuros:

- adicionar usuario em grupo;
- alterar permissoes;
- modificar configuracao de infraestrutura.

### Critico

Acao que nao deve ser executada diretamente pela SofIA.

Exemplos:

- Domain Admins;
- Enterprise Admins;
- execucao arbitraria de comandos;
- alteracao ampla em firewall;
- exclusao de usuario.

## Acoes Atuais

| Acao | Status | Risco | Observacao |
| --- | --- | --- | --- |
| `chat:basic` | habilitada | baixo | Permite conversar com a SofIA. |
| `sentinel:read` | habilitada | baixo | Permite consultar dados ja carregados no Sentinel. |
| `knowledge:read` | habilitada | baixo | Permite respostas explicativas da base `knowledge/`. |

## Acoes Planejadas

| Acao | Status | Risco | Observacao |
| --- | --- | --- | --- |
| `ad:user:read` | desabilitada | baixo | Consulta read-only de usuario no AD. |
| `ad:group:read` | desabilitada | baixo | Consulta grupos de usuario. |
| `ad:password:reset` | desabilitada | medio | Exigira confirmacao, OU permitida e auditoria. |
| `ad:user:unlock` | desabilitada | medio | Exigira confirmacao e escopo por OU. |
| `ad:user:force_password_change` | desabilitada | medio | Exigira confirmacao. |
| `ad:group:add_member` | desabilitada | alto | Exigira aprovacao humana. |
| `ticket:create` | desabilitada | baixo | Abertura de chamados futura. |
| `notify:email` | desabilitada | baixo | Envio de notificacao futura. |
| `command:execute` | bloqueada | critico | Nao deve aceitar comando arbitrario. |

## Escopo

No futuro, uma permissao podera depender de:

- grupo AD do solicitante;
- cargo;
- regional;
- OU do alvo;
- tipo de acao;
- risco;
- aprovacao pendente.

## Arquivo Estruturado

A matriz tecnica inicial fica em:

```text
sofia/permissions_matrix.json
```

O arquivo `permissions.py` deve ler essa matriz e permitir apenas acoes habilitadas.

## Regra de Manutencao

Toda nova capacidade da SofIA deve nascer com:

- nome da acao;
- risco;
- status habilitado/desabilitado;
- se exige confirmacao;
- se exige aprovacao;
- escopo;
- regra de auditoria.
