# Implantação segura do Sentinel

## Obrigatório em produção

1. Publique o Sentinel somente por HTTPS, atrás do proxy reverso corporativo.
2. Defina `SENTINEL_HTTPS_ENABLED=true` para ativar cookie `Secure` e HSTS.
3. Defina uma chave aleatória e exclusiva em `SECRET_KEY`. Não compartilhe essa chave nem a inclua no Git.
4. Defina `SENTINEL_TRUSTED_HOSTS` com os hosts permitidos, separados por vírgula. Exemplo: `<fqdn-interno>,<ip-do-proxy>`.
5. Inicie pelo `run_web_service.py`, que usa Waitress. Não publique o servidor de desenvolvimento do Flask.
6. Restrinja a porta do Waitress no firewall para aceitar somente o proxy reverso ou a rede administrativa.
7. Mantenha `DEBUG` desativado e limite o acesso aos logs e à pasta `instance` à conta do serviço.

Exemplo de variáveis do serviço:

```text
SECRET_KEY=<valor aleatório com pelo menos 64 caracteres>
SENTINEL_HTTPS_ENABLED=true
SENTINEL_TRUST_PROXY=true
SENTINEL_TRUSTED_HOSTS=<fqdn-interno>,<ip-do-proxy>
AUTOMACAO_WEB_HOST=127.0.0.1
AUTOMACAO_WEB_PORT=5000
```

`SENTINEL_TRUST_PROXY=true` aceita os cabecalhos de IP e protocolo enviados por
um unico proxy reverso. Ative essa opcao somente quando o Waitress estiver em
`127.0.0.1`; manter a porta 5000 acessivel pela rede permitiria forjar esses
cabecalhos. O proxy deve substituir, e nao apenas preservar, os cabecalhos
`X-Forwarded-For` e `X-Forwarded-Proto` recebidos do cliente.
O `run_web_service.py` configura a confianca diretamente no Waitress e falha
fechado se esse modo for combinado com um listener fora do loopback.

As configurações das integrações ficam exclusivamente no `environment.json`,
que não deve ser versionado, copiado para executáveis ou incluído em imagens.
Restrinja sua leitura à conta do serviço e mantenha o `environment.example.json`
somente com valores fictícios.

## Canal técnico n8n

O segredo HMAC do canal entre n8n e Sentinel é uma credencial de serviço, não
uma configuração de integração comum. Defina-o no ambiente protegido do processo
do Sentinel e na credencial Crypto criptografada do n8n. Não o grave no
`environment.json`, em workflow exportado ou em script versionado.

```text
SENTINEL_N8N_KEY_ID=<identificador-da-chave>
SENTINEL_N8N_HMAC_SECRET=<segredo aleatório exclusivo>
SENTINEL_N8N_ALLOWED_NETWORKS=<ip-ou-rede-do-n8n-em-CIDR>
SENTINEL_N8N_MAX_CLOCK_SKEW_SECONDS=60
```

A lista de redes é obrigatória e deve usar o IP real do host n8n. Mantenha os
relógios sincronizados para validar a janela curta das requisições. Restrinja
também a porta no firewall do Windows ao host necessário.

O endpoint inicial `/api/internal/sofia/v1/health` não retorna dados
operacionais. Não habilite consultas internas enquanto o tráfego entre os hosts
não estiver protegido por TLS.

## Active Directory

- A senha é enviada ao processo PowerShell por entrada padrão e não aparece na linha de comando.
- A autenticação e a leitura de grupos usam o módulo `ActiveDirectory` e AD Web Services; a enumeração LDAP anônima em porta 389 está desativada.
- Grupos `GGS_SUPORTE_*` enxergam somente as regionais associadas.
- `Remote Desktop Users` e `Account Operators` têm visão ampla, mas não podem executar alterações administrativas no Sentinel.
- `GGS_SUPORTE_CORPORATIVO`, administradores do domínio e usuários da OU administrativa podem operar o Sentinel.
- Sessões expiram após uma hora. Alterações de grupo passam a valer no próximo login, no máximo após essa expiração.

## Validação após publicar

1. Acesse `https://<fqdn-interno>/login` e confirme o certificado válido.
2. Confirme que uma URL HTTP redireciona para HTTPS no proxy.
3. Teste um usuário regional e confirme que outra regional retorna HTTP 403.
4. Teste um membro de `Remote Desktop Users` e confirme que ele visualiza, mas não altera configurações.
5. Teste um operador autorizado, logout e expiração da sessão.
6. Revise os logs sem registrar senhas, tokens ou conteúdo enviado à SofIA.
