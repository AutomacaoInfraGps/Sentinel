# Autenticacao de Servico entre n8n e Sentinel

O canal interno do n8n usa uma identidade tecnica propria. Ele nao reutiliza
cookie do navegador, senha do Active Directory ou credencial pessoal.

## Rotas iniciais

```text
GET /api/internal/sofia/v1/health
GET /api/internal/sofia/v1/capabilities
GET /api/internal/sofia/v1/alerts
```

As rotas retornam a disponibilidade da API, o contrato fechado de capacidades
e uma visao minima dos alertas ativos em modo somente leitura. A resposta de
alertas e limitada a 100 itens e nao inclui inventario completo, credenciais,
segredos ou dados de sessao de usuarios.

## Controles

- HMAC-SHA256 sobre metodo, caminho, timestamp, nonce e hash do corpo;
- chave identificada e rotacionavel;
- janela de tempo curta;
- nonce persistente de uso unico contra replay;
- lista obrigatoria de redes de origem;
- comparacao de assinatura em tempo constante;
- falha fechada quando segredo ou protecao de replay estao indisponiveis;
- auditoria sem registrar segredo, assinatura ou corpo da requisicao.

## Variaveis locais do Sentinel

```text
SENTINEL_N8N_KEY_ID
SENTINEL_N8N_HMAC_SECRET
SENTINEL_N8N_ALLOWED_NETWORKS
SENTINEL_N8N_MAX_CLOCK_SKEW_SECONDS
SENTINEL_N8N_NONCE_DB
```

Os valores nao devem ser adicionados ao Git. O segredo deve ter ao menos 32
caracteres aleatorios e deve ser diferente das chaves Flask, n8n e PostgreSQL.

## Formato assinado

```text
METODO_HTTP
CAMINHO_COM_QUERY_STRING
TIMESTAMP_UNIX
NONCE
SHA256_DO_CORPO
```

O resultado e assinado com HMAC-SHA256 e enviado em hexadecimal no cabecalho
`X-Sentinel-Signature`. O n8n tambem envia `X-Sentinel-Key-Id`,
`X-Sentinel-Timestamp` e `X-Sentinel-Nonce`.

TLS continua obrigatorio antes de transportar consultas ou dados operacionais.
A assinatura autentica e protege a integridade, mas nao cifra o trafego.
