# Seguranca da SofIA

## Principio

A SofIA deve ser segura por padrao.

Ela pode entender a intencao do usuario, mas nao deve decidir sozinha se uma acao pode ser executada.

## Riscos Considerados

- prompt injection;
- vazamento de dados internos;
- execucao indevida de comandos;
- tentativa de burlar permissao;
- acao fora do escopo;
- alucinacao da IA;
- roubo de sessao;
- replay de requisicao;
- uso indevido de conta de servico.

## Regras

Antes de qualquer acao real:

1. usuario autenticado;
2. sessao valida;
3. grupo/cargo autorizado;
4. acao permitida;
5. alvo dentro do escopo permitido;
6. classificacao de risco;
7. confirmacao ou aprovacao quando necessario;
8. conta de servico com privilegio minimo;
9. auditoria completa.

## Acoes Bloqueadas Atualmente

- reset de senha;
- desbloqueio de conta;
- alteracao de grupo;
- criacao ou exclusao de usuario;
- comandos em servidores;
- alteracoes em firewalls;
- alteracoes em Zabbix.

## Diretriz

Toda nova ferramenta deve ser allowlisted e testada.

Nenhum comando arbitrario vindo do usuario deve ser executado.
