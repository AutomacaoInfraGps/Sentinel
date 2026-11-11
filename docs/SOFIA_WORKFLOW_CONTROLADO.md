# SofIA com consulta controlada e entrega assíncrona

## Fluxo preparado

O modelo interpreta o pedido em um plano JSON pequeno. O Sentinel valida o plano, aplica o escopo assinado e monta a resposta operacional usando o inventário. Cada plano de consulta passa obrigatoriamente pelo endpoint `/api/internal/sofia/v1/assistant/query`.

Os recursos disponíveis são alertas atuais, firewalls, licenças, links, VPNs, servidores, APs, switches, Wi-Fi e regionais autorizadas. O modelo escolhe recurso, filtros, campos e paginação. Contagens e listas são formatadas pelo servidor. Conversas sociais recebem uma resposta curta do modelo.

O contexto enviado ao modelo contém identidade autenticada, até quatro mensagens curtas e o último plano de consulta. A memória usa a tabela isolada existente com o sufixo de sessão `:v4`. Isso inicia um contexto novo para este fluxo. O histórico visual já salvo no navegador continua disponível.

O chat recebe HTTP 202 e acompanha o resultado com requisições curtas. A mesma aba do navegador retoma o acompanhamento após recarregamento ou navegação pelo Sentinel. O botão de parada usa o controle de execução existente.

## Arquivos locais

Os candidatos gerados ficam em `instance/sofia-workflows/sofia-main-controlled.json` e `instance/sofia-workflows/sofia-inventory-controlled.json`. A pasta é ignorada pelo Git. Os candidatos mantêm os IDs dos workflows, o caminho do webhook e as referências às credenciais dos exports fornecidos.

Para gerar novamente na máquina de desenvolvimento, a partir da raiz do repositório, execute no PowerShell.

```powershell
.\venv313\Scripts\python.exe -m sofia.n8n.build_readonly_workflows `
  --main "$env:USERPROFILE\Downloads\SofIA - Agente Sentinel v3.json" `
  --inventory "$env:USERPROFILE\Downloads\SofIA Tool - Consultar Inventário Operacional.json"
```

## Primeiro aplicar a revisão no Rigel

Para uma revisão apenas das instruções de identidade e conversa, o gerador também escreve `instance/sofia-workflows/interpretar-pedido-expression.txt`. Copie seu conteúdo com `.Trim()` para o campo Body em modo Expression do nó `Interpretar pedido`, mantendo o formato Raw e o Content Type `application/json`. Salve e publique o workflow principal. O arquivo incorpora `plan_prompt.txt` e o contrato JSON do modelo. A troca desse campo aplica o prompt revisado ao workflow existente.

A homologação de identidade deve incluir uma conversa nova com um criador configurado, um usuário comum e uma mensagem que declare uma identidade diferente. Confira o `user_context` autenticado no corpo enviado ao modelo e a resposta produzida em cada caso. Os testes automatizados verificam a transmissão desse contexto e a validade das expressões. O comportamento conversacional precisa de verificação com o Ollama em execução.

Disponibilize esta revisão no Rigel pelo fluxo de versionamento usado no projeto. Depois execute em `C:\Automacao`.

```powershell
.\.venv31410\Scripts\python.exe -m unittest `
  tests.unit.sofia_async_chat_test `
  tests.unit.sofia_query_response_test `
  tests.unit.sofia_service_auth_test `
  tests.unit.sofia_cancellation_test `
  tests.unit.sofia_operational_inventory_test

powershell -ExecutionPolicy Bypass -File .\restart_web_service.ps1

Invoke-WebRequest http://127.0.0.1:5000/login -UseBasicParsing -TimeoutSec 15 |
  Select-Object StatusCode
```

O novo endpoint deve estar disponível antes da publicação dos candidatos. A tabela SQLite de resultados é criada pelo próprio Sentinel no banco de controle de consultas.

## Depois atualizar os dois workflows no Celeno

Os arquivos possuem os IDs dos workflows existentes. A importação por CLI atualiza esses registros e os deixa desativados. Exporte uma cópia atual antes de importar e publique primeiro o subworkflow. A documentação oficial descreve a atualização por ID e a desativação durante a importação. [CLI do n8n](https://docs.n8n.io/deploy/host-n8n/configure-n8n/use-the-command-line.md)

Na máquina de desenvolvimento, copie os candidatos com PowerShell.

```powershell
scp .\instance\sofia-workflows\sofia-inventory-controlled.json .\instance\sofia-workflows\sofia-main-controlled.json administrador@10.254.12.66:/tmp/
```

No terminal SSH do Celeno, primeiro guarde os workflows atuais.

```bash
sudo docker exec -u node sofia-n8n-1 sh -c 'umask 077; n8n export:workflow --id=I4l72qvM1AoWvJhi --output=/tmp/sofia-main-before.json'
sudo docker exec -u node sofia-n8n-1 sh -c 'umask 077; n8n export:workflow --id=tJ1f4rJJ4aH9ATT5 --output=/tmp/sofia-inventory-before.json'
backup_sofia_dir=$(mktemp -d "$HOME/sofia-workflows-$(date +%Y%m%d-%H%M%S)-XXXXXX")
sudo docker cp sofia-n8n-1:/tmp/sofia-main-before.json "$backup_sofia_dir/main.json"
sudo docker cp sofia-n8n-1:/tmp/sofia-inventory-before.json "$backup_sofia_dir/inventory.json"
sudo chmod 600 "$backup_sofia_dir/main.json" "$backup_sofia_dir/inventory.json"
echo "$backup_sofia_dir"
```

Copie os candidatos para o container e importe em ordem.

```bash
chmod 600 /tmp/sofia-main-controlled.json /tmp/sofia-inventory-controlled.json
sudo docker cp /tmp/sofia-inventory-controlled.json sofia-n8n-1:/tmp/sofia-inventory-controlled.json
sudo docker cp /tmp/sofia-main-controlled.json sofia-n8n-1:/tmp/sofia-main-controlled.json
sudo docker exec -u root sofia-n8n-1 chown node:node /tmp/sofia-inventory-controlled.json /tmp/sofia-main-controlled.json
sudo docker exec -u root sofia-n8n-1 chmod 600 /tmp/sofia-inventory-controlled.json /tmp/sofia-main-controlled.json
sudo docker exec -u node sofia-n8n-1 n8n import:workflow --input=/tmp/sofia-inventory-controlled.json
sudo docker exec -u node sofia-n8n-1 n8n import:workflow --input=/tmp/sofia-main-controlled.json
```

Na interface do n8n, recarregue a página. Abra e publique `SofIA Tool - Consultar Inventário Operacional`. Depois abra e publique `SofIA - Agente Sentinel v3`.

Confira as credenciais dos nós Crypto e Postgres antes de publicar. O Postgres usa a credencial isolada da memória. O endpoint do modelo é `http://ollama:11434/api/chat`. A assinatura HMAC cobre o método, caminho, timestamp, nonce e hash do corpo exato enviado.

## Homologação no Sentinel

O gerador separa as chaves de fechamento dos objetos JavaScript para respeitar o delimitador `}}` das expressões do n8n. A regressão verifica todos os parâmetros gerados. Também foi validada com `@n8n/tournament` 1.13.0, a versão declarada no n8n 2.41.4. [Interpretador do n8n](https://github.com/n8n-io/n8n/blob/n8n%402.41.4/packages/%40n8n/tournament/package.json)

Faça consultas em uma conversa nova e confira os resultados nas telas correspondentes.

1. Envie uma saudação. A execução deve passar pelo modelo e pela gravação de conversa.
2. Pergunte quantos switches estão em manutenção. A execução deve passar por `Executar consulta autorizada` e pelo endpoint do Sentinel. Uma contagem positiva deve aparecer mesmo quando a consulta usa apenas resumo.
3. Peça APs offline com nome, IP e regional. Confira os nomes e a indicação de lista parcial, quando houver.
4. Peça modelos e firmware de Araras usando o nome natural.
5. Peça licenças a vencer e as respectivas regionais.
6. Recarregue a página durante uma consulta. O resultado deve chegar pela consulta pendente, com uma única execução no n8n.
7. Interrompa uma consulta. Confira o estado cancelado no n8n e a mensagem `Consulta cancelada.` no Sentinel.
8. Confira que um usuário de escopo restrito recebe somente dados autorizados.

O fluxo principal deve executar `Interpretar pedido` uma vez por mensagem. A consulta operacional usa o subworkflow regular. Registre os tempos desse nó e da execução completa para comparar com os testes anteriores. A latência no Celeno ainda precisa ser medida após a publicação.

## Limites desta revisão

- O plano aceita uma consulta por mensagem, até 50 registros por página e oito campos por item. Respostas extensas indicam lista parcial e o próximo deslocamento, sem descartar itens silenciosamente.
- Existem dois trabalhadores assíncronos por processo web. O timeout da chamada ao n8n é de 480 segundos. O acompanhamento no navegador tem limite de nove minutos.
- As respostas ficam no SQLite por até dez minutos, com expurgo nas operações seguintes. O polling confere usuário, conversa e escopo atual. O armazenamento local depende das permissões de arquivo do serviço.
- Reiniciar o processo web interrompe seus trabalhadores. As consultas pendentes terão de ser reenviadas após o erro ou vencimento do prazo. O controle atual permite solicitar o cancelamento da execução registrada no n8n.
- O token de escopo continua sujeito à validade existente de cinco minutos. Uma interpretação que ultrapasse esse prazo exige nova solicitação.
- Histórico de abertura e recuperação de alertas, RAG e replicação AD estão fora dos adaptadores deste candidato. O planejador deve informar essa limitação quando solicitado.

## Retorno à versão anterior

Use os arquivos `inventory.json` e `main.json` do diretório de backup. Copie-os para o container e execute `n8n import:workflow --input=...` em cada arquivo. Publique o subworkflow e depois o principal. Os IDs e o caminho do webhook permitem retornar ao fluxo anterior. A API síncrona do Sentinel continua disponível para os chamadores existentes.
