# Implantação segura do Sentinel

## Obrigatório em produção

1. Publique o Sentinel somente por HTTPS, atrás do proxy reverso corporativo.
2. Defina `SENTINEL_HTTPS_ENABLED=true` para ativar cookie `Secure` e HSTS.
3. Defina uma chave aleatória e exclusiva em `SECRET_KEY`. Não compartilhe essa chave nem a inclua no Git.
4. Defina `SENTINEL_TRUSTED_HOSTS` com os hosts permitidos, separados por vírgula. Exemplo: `sentinel.galaxia.local,10.254.12.63`.
5. Inicie pelo `run_web_service.py`, que usa Waitress. Não publique o servidor de desenvolvimento do Flask.
6. Restrinja a porta do Waitress no firewall para aceitar somente o proxy reverso ou a rede administrativa.
7. Mantenha `DEBUG` desativado e limite o acesso aos logs e à pasta `instance` à conta do serviço.

Exemplo de variáveis do serviço:

```text
SECRET_KEY=<valor aleatório com pelo menos 64 caracteres>
SENTINEL_HTTPS_ENABLED=true
SENTINEL_TRUSTED_HOSTS=sentinel.galaxia.local,10.254.12.63
SENTINEL_SESSION_TIMEOUT_MINUTES=0
AUTOMACAO_WEB_HOST=127.0.0.1
AUTOMACAO_WEB_PORT=5000
```

## Active Directory

- A senha é enviada ao processo PowerShell por entrada padrão e não aparece na linha de comando.
- A autenticação e a leitura de grupos usam o módulo `ActiveDirectory` e AD Web Services; a enumeração LDAP anônima em porta 389 está desativada.
- Grupos `GGS_SUPORTE_*` enxergam somente as regionais associadas.
- `Remote Desktop Users` e `Account Operators` têm visão ampla, mas não podem executar alterações administrativas no Sentinel.
- `GGS_SUPORTE_CORPORATIVO`, administradores do domínio e usuários da OU administrativa podem operar o Sentinel.
- Com `SENTINEL_SESSION_TIMEOUT_MINUTES=0`, a sessão não expira por inatividade e permanece ativa até logout, fechamento do navegador ou reinício do serviço. Um valor maior que zero reativa a expiração em minutos.

## Validação após publicar

1. Acesse `https://sentinel.galaxia.local/login` e confirme o certificado válido.
2. Confirme que uma URL HTTP redireciona para HTTPS no proxy.
3. Teste um usuário regional e confirme que outra regional retorna HTTP 403.
4. Teste um membro de `Remote Desktop Users` e confirme que ele visualiza, mas não altera configurações.
5. Teste um operador autorizado, logout e expiração da sessão.
6. Revise os logs sem registrar senhas, tokens ou conteúdo enviado à SofIA.
