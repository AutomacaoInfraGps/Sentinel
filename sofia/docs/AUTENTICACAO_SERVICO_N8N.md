# Autenticacao de Servico entre n8n e Sentinel

O canal interno do n8n usa uma identidade tecnica propria. Ele nao reutiliza
cookie do navegador, senha do Active Directory ou credencial pessoal.

## Rotas iniciais

```text
GET /api/internal/sofia/v1/health
GET /api/internal/sofia/v1/capabilities
GET /api/internal/sofia/v1/alerts
POST /api/internal/sofia/v1/regionals/query
```

As rotas retornam a disponibilidade da API, o contrato fechado de capacidades
e uma visao minima dos alertas ativos em modo somente leitura. A resposta de
alertas e limitada a 100 itens e nao inclui inventario completo, credenciais,
segredos ou dados de sessao de usuarios.

## Consulta regional

Ao encaminhar uma mensagem para o n8n, o Sentinel inclui
`sentinel_scope_token`. Esse token e assinado exclusivamente pelo Sentinel,
expira em cinco minutos e contem as regionais autorizadas para o usuario
logado. O n8n deve trata-lo como metadado opaco: nao deve decodificar, alterar,
armazenar nem incluir o token no prompt do Ollama.

Para listar somente o indice autorizado de regionais:

```json
{
  "sentinel_scope_token": "<token recebido do Sentinel>",
  "sections": []
}
```

Para consultar uma regional especifica:

```json
{
  "sentinel_scope_token": "<token recebido do Sentinel>",
  "regional": "REG_BAHIA",
  "sections": ["servidores", "links", "switches"]
}
```

As secoes sao opcionais e fechadas nessa allowlist. Sem `regional`, a resposta
traz apenas codigo, nome e estado para evitar excesso de contexto. Com uma
regional, a resposta sempre inclui os resumos e pode incluir os detalhes das
secoes solicitadas. Campos como senha, usuario tecnico, token, community SNMP,
cookie e `credential_ref` nunca sao projetados para essa API.

O corpo JSON deve ser serializado antes do calculo da assinatura, e os mesmos
bytes precisam ser enviados na requisicao. Alterar espacos ou a ordem dos
campos depois de assinar invalida o HMAC.

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
