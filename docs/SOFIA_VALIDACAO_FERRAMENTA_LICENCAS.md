# Validacao explicita da ferramenta de licencas

## Evidencias e limites

O export `SofIA - Agente Sentinel v3 (2).json` conserva o plano fixo usado no diagnostico. Esse plano consultou REG_TLSV_POA com sucesso. Ele nao comprova interpretacao natural nem pode permanecer em uso: qualquer chamada consultaria a mesma regional.

O erro original nao esta registrado nesse export. A segunda tentativa exibida tinha offset fracionario. Foi reproduzido localmente no motor n8n-workflow 2.41.1: a expressao antiga retorna um plano com offset=0, mas retorna undefined quando sua validacao lanca erro com offset fracionario. A funcao JavaScript simples usada nos testes anteriores propagava a excecao, portanto nao reproduzia esse detalhe do motor. Isso explica um mecanismo de falha, nao prova a causa da primeira tentativa real. O servidor executa n8n 2.41.4; ainda e necessario validar o workflow nele.

## Alteracao preparada

O agente continua nativo, com Ollama e memoria locais. O export fornecido usa qwen3:4b-instruct e esse modelo e preservado, sem nova troca. Somente Consultar licencas muda de destino para um adaptador local:

1. Expressao do plan monta valores usando $fromAI, sem validacao com throw.
2. Subworkflow SofIA Tool - Validar consulta de licencas valida o objeto em Edit Fields (Set), com try/catch dentro da expressao retornando um objeto validation. Nenhuma excecao de validacao deve escapar para virar undefined. Filtros, campos, recurso e paginacao continuam estritos; nao ha arredondamento ou coercao de valores invalidos.
3. Se houver uma unica regional autorizada mencionada na mensagem atual, o resolvedor preenche a omissao e remove somente uma busca que repita essa regional. Produtos nao sao apagados.
4. Apenas a saida valida chama o subworkflow autorizado ja existente, com plan e sentinel_scope_token.
5. A saida invalida retorna success=false, error_code=INVALID_TOOL_ARGUMENTS e uma mensagem sobre os argumentos, sem token e sem consultar o Sentinel. O agente pode corrigir a chamada dentro das iteracoes ja configuradas.

request_context e sentinel_scope_token sao expressoes fixas vindas do Webhook, nunca parametros $fromAI. A lista de regionais e uma ajuda de resolucao, nao concede acesso: o Sentinel continua verificando o token e impondo o escopo a cada consulta. O adaptador nao contem credenciais, SQL, comandos ou destinos HTTP. Nao ha alteracao em AD, acesso externo, RAG ou permissoes. RAG continua pendente.

A primeira versao do adaptador usava Code e foi rejeitada ao publicar: Unrecognized node type: n8n-nodes-base.code. Nao habilitar esse tipo nem alterar NODES_EXCLUDE para contornar. A versao corrigida usa apenas Execute Workflow Trigger, Set, IF e Execute Workflow. Os testes passam tambem com o motor local n8n-workflow 2.41.1, incluindo os casos invalidos que precisam retornar objeto de erro, nao undefined.

## Geracao local

```powershell
.\venv313\Scripts\python.exe -m sofia.n8n.build_license_tool_bridge `
  --main "$env:USERPROFILE\Downloads\SofIA - Agente Sentinel v3 (2).json" `
  --expected-id I4l72qvM1AoWvJhi
```

Arquivos privados em instance/sofia-workflows:

- sofia-license-validation-tool.json: novo adaptador, sem credenciais e com ID proprio.
- sofia-main-license-bridge-update.json: copia do export recebido, substituindo somente a configuracao da ferramenta de licencas e removendo metadados de versao/publicacao. ID, webhook, memoria, modelo, demais nos e conexoes do principal sao preservados; active=false exige publicacao manual.
- sofia-main-before-license-bridge-<hash>.json: backup exato do export recebido. Contem o plano fixo de diagnostico; restaurar esse backup nao restaura o comportamento dinamico anterior.

Os JSONs gerados nao sao publicados automaticamente. Se houver mudancas remotas posteriores ao export, obter novo export e regenerar antes de importar para nao sobrescreve-las.

## Aplicacao manual

Fazer a troca em janela curta sem consultas em andamento. A importacao do principal o desativa ate a publicacao; o chat pode ficar indisponivel nesse intervalo.

No PowerShell de desenvolvimento, na raiz do projeto:

```powershell
scp .\instance\sofia-workflows\sofia-license-validation-tool.json .\instance\sofia-workflows\sofia-main-license-bridge-update.json administrador@10.254.12.66:/tmp/
```

No Celeno:

```bash
sudo docker cp /tmp/sofia-license-validation-tool.json sofia-n8n-1:/tmp/sofia-license-validation-tool.json
sudo docker cp /tmp/sofia-main-license-bridge-update.json sofia-n8n-1:/tmp/sofia-main-license-bridge-update.json
sudo docker exec -u node sofia-n8n-1 n8n import:workflow --input=/tmp/sofia-license-validation-tool.json
sudo docker exec -u node sofia-n8n-1 n8n import:workflow --input=/tmp/sofia-main-license-bridge-update.json
```

Nao repetir chown/chmod que ja foram negados pelo ambiente. Se a importacao nao conseguir ler um arquivo, interromper e diagnosticar sem enfraquecer o isolamento Docker.

No editor, recarregar os workflows. Conferir o novo adaptador, seu destino original autorizado e os dois ramos do IF. Publicar primeiro SofIA Tool - Validar consulta de licencas: neste ambiente, a chamada da ferramenta ao adaptador importado inativo foi rejeitada com "Workflow is not active and cannot be executed." No principal existente, Consultar licencas deve apontar ao novo adaptador e receber plan dinamico, request_context fixo e sentinel_scope_token fixo. Publicar tambem o principal existente I4l72qvM1AoWvJhi, nao a copia Candidate. O adaptador inicia por Execute Workflow Trigger e nao cria webhook ou nova entrada publica.

## Aceite real

Se o principal ja recebeu a atualizacao e apenas o adaptador foi rejeitado por conter Code, copiar e reimportar somente sofia-license-validation-tool.json, que preserva o ID do adaptador. Recarregar o editor e publicar esse subworkflow. Nao reimportar o principal novamente nem alterar credenciais para esta correcao. Confirmar que os nos Validar argumentos e Retornar erro de argumentos agora sao Edit Fields (Set).

Em conversa nova, perguntar naturalmente pelos dias da licenca da Nutricar e depois "E da TLSV POA?". Conferir as consultas retornadas: regional correta, search sem repetir a regional, fields=[days_remaining], view=list e offset inteiro. Conferir que a resposta final usa uma chamada desta interacao.

Um plano invalido deve retornar erro de argumentos, nunca afirmar ausencia de licenca. Esse tratamento nao garante que o modelo corrigira o erro, chamara a ferramenta ou interpretara todas as paginas corretamente. Ainda sao criterios de aceite real. O fluxo de alertas e o inventario geral nao foram alterados nesta correcao.

## Referencias

- [n8n WorkflowToolService: execucao e parametros de subworkflow](https://github.com/n8n-io/n8n/blob/n8n%402.41.4/packages/%40n8n/nodes-langchain/nodes/tools/ToolWorkflow/v2/utils/WorkflowToolService.ts)
- [n8n: parametros preenchidos com $fromAI](https://docs.n8n.io/advanced-ai/examples/using-the-fromai-function/)
