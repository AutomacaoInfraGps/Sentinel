# Segurança da SofIA

## Princípio

A SofIA deve ser segura por padrão.

Ela pode entender a intenção do usuário, mas não deve decidir sozinha se uma ação pode ser executada.

## Riscos Considerados

- prompt injection;
- vazamento de dados internos;
- execução indevida de comandos;
- tentativa de burlar permissão;
- ação fora do escopo;
- alucinação da IA;
- roubo de sessão;
- replay de requisição;
- uso indevido de conta de serviço.

## Regras

Antes de qualquer ação real:

1. usuário autenticado;
2. sessão válida;
3. grupo/cargo autorizado;
4. ação permitida;
5. alvo dentro do escopo permitido;
6. classificação de risco;
7. confirmação ou aprovação quando necessário;
8. conta de serviço com privilégio mínimo;
9. auditoria completa.

## Ações Bloqueadas Atualmente

- reset de senha;
- desbloqueio de conta;
- alteração de grupo;
- criação ou exclusão de usuário;
- comandos em servidores;
- alterações em firewalls;
- alterações em Zabbix.

## Diretriz

Toda nova ferramenta deve ser allowlisted e testada.

Nenhum comando arbitrário vindo do usuário deve ser executado.
