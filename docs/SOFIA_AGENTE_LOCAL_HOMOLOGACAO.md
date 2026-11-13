# Candidato de AI Agent local

Decisao posterior: o usuario autorizou [atualizar o workflow existente](SOFIA_AGENTE_LOCAL_ATUALIZACAO.md), sem exigir uma nova pagina ou ambiente como requisito. Este documento preserva o historico da copia independente; seguir o guia de atualizacao para a troca aprovada. O candidato nao deve ser publicado junto para substituir o chat.

Este candidato implementa a primeira etapa da [arquitetura alinhada](SOFIA_ARQUITETURA_ALVO.md): AI Agent, modelo local, memoria e ferramentas de leitura. RAG continua obrigatorio no escopo, mas ainda nao esta implementado neste candidato. Nao publicar como se a migracao ou a recuperacao documental estivessem concluidas.

## Arquivos

- `sofia/n8n/build_agent_workflow.py`: gerador separado do gerador antigo de planos.
- `sofia/n8n/agent_prompt.txt`: instrucoes de conversa, evidencia e limites do agente.
- `instance/sofia-workflows/sofia-agent-local-candidate.json`: candidato privado gerado, ignorado pelo Git.
- `tests/unit/sofia_agent_workflow_test.py`: testes de estrutura, expressoes e seguranca do transporte.

O gerador recebeu o export principal atual, o export atual do inventario e o export anterior apenas para recuperar tipo, versao e referencia de credencial do modelo Ollama. Nenhum prompt ou expressao dos exports e executado pelo gerador. O subworkflow de inventario nao e modificado.

## O que o candidato contem

AI Agent 3.1, Ollama local usando a credencial referenciada no export antigo, memoria Postgres 1.4 usando a credencial isolada do export atual, e tres ferramentas workflow: alertas atuais, licencas e inventario. As tres usam o subworkflow existente `tJ1f4rJJ4aH9ATT5`. Alertas e licencas possuem recurso fixo. O modelo preenche apenas argumentos de consulta; o token de escopo vem do Webhook e nao de fromAI.

O caminho `plan` do subworkflow chama `/api/internal/sofia/v1/assistant/query`. O contrato conferido no backend local e `success`, `reply`, `query`, `matched`, `displayed`, `next_offset`, `fresh` e `updated_at` no nivel principal, nao dentro de `data`. Os argumentos da ferramenta permanecem estruturados, mas a resposta final do agente e texto natural. A etapa final entrega somente `reply`, respeitando o limite de 8000 caracteres aceito pelo cliente atual.

O modelo inicial e o operacional ja presente no export anterior, qwen3:4b-instruct. O contexto foi configurado em 8192 e a saida maxima em 2048, sem download ou carregamento automatico de modelos. Esses valores sao parametros iniciais para medir no ambiente real, nao prova de qualidade ou dimensionamento definitivo de hardware. Nao ha fallback em nuvem ou modelo social secundario.

A memoria usa chave derivada pelo Sentinel, vinculada a usuario, conversa e escopo, com sufixo `:agent-lab-v1` e janela de quatro interacoes. Ela nao le as sessoes `:v4`. A tabela fica fixa em `sofia_chat_history` e a credencial precisa continuar com o search_path isolado de `sofia_memory`, conforme as migracoes 006 e 007. Conferir isso antes da primeira execucao.

## Limites da copia

O usuario confirmou o ID atribuido pelo n8n a copia importada: `zxUluLOm3QCDKhVj`. Esse e o ID de homologacao, nao o ID autorizado da producao. A URL do webhook da copia e a instancia Sentinel de homologacao ainda precisam ser confirmadas antes de preparar configuracao executavel. Nao substituir as variaveis do servico atual apenas com base nesse ID.

O candidato nao possui ID do workflow de producao, fica inativo e tem caminho de webhook novo. As referencias a credenciais sao preservadas, mas seus valores secretos nao foram lidos. Conferir no n8n se a credencial Ollama aponta para o servico interno esperado e se as versoes dos nos continuam disponiveis.

O registro assinado e o cancelamento continuam na cadeia. Como o Sentinel aceita somente o ID configurado em `SENTINEL_SOFIA_N8N_WORKFLOW_ID`, uma copia com ID novo recebe rejeicao ate existir configuracao separada de homologacao. Isso e intencional. Nao remover essa verificacao, nao reutilizar o ID de producao e nao trocar as variaveis do servico de producao para testar a copia.

O subworkflow compartilhado faz leituras reais autorizadas, nao utiliza fixtures. Testes de integracao so devem ocorrer com solicitacoes e tokens emitidos pelo Sentinel de homologacao. Nao colar tokens manualmente em expressoes, memoria ou mensagens do agente. O agente nao recebe ferramentas de shell, SQL livre, navegador ou HTTP arbitrario. Nao conectar containers a internet para executar esta etapa.

## Proximo passo no n8n

1. Importar o JSON como workflow novo, mantendo-o desativado. Confirmar que o workflow atual permanece intacto e ativo.
2. Conferir visualmente o AI Agent e as conexoes de modelo, memoria e tres ferramentas.
3. Conferir referencias de credenciais, destino interno do Ollama, tabela/search_path da memoria e subworkflow de consulta. Nao enviar segredos em capturas de tela.
4. Preparar uma configuracao separada de Sentinel para homologacao, com webhook e ID da copia e com registro/cancelamento funcionando. Esta etapa precisa ser combinada antes de publicar ou executar pelo chat.
5. Testar conversa natural e tool calling real no n8n. Confirmar pelos passos intermediarios quando uma ferramenta foi executada. Testes simulados locais nao comprovam compatibilidade ou interpretacao do modelo.
6. Validar escopo, mudanca de regional/recurso, licencas, alertas, paginacao, memoria e cancelamento. Somente depois avaliar publicacao e dimensionamento de modelo/hardware.

O passo 1 permite revisar a estrutura e nao autoriza os passos de publicacao. Se o editor informar incompatibilidade de no ou modelo, registrar o erro sem substituir a arquitetura por um planejador HTTP.

## RAG na etapa seguinte

Antes de conectar uma ferramenta RAG, definir os documentos e seus donos, permissoes por usuario/regional, processamento e indice locais, atualizacao/remocao de documentos, fontes e controle de instrucoes maliciosas nos trechos. A permissao deve ser aplicada antes de fornecer documentos ao modelo. RAG explica procedimentos; inventario consulta o estado atual. Memoria nao substitui nenhum dos dois.

## Validacao local

```powershell
.\venv313\Scripts\python.exe -m unittest tests.unit.sofia_agent_workflow_test
```

Os testes nao acessam Docker, n8n, Ollama ou banco reais. Usam exports sinteticos e Node para avaliar expressoes. A geracao com os exports reais confere formato e dependencias declaradas, sem executar seus nos.

## Referencias

- [Parametros de ferramentas com fromAI](https://docs.n8n.io/advanced-ai/examples/using-the-fromai-function/)
- [Memoria Postgres do n8n](https://docs.n8n.io/integrations/builtin/cluster-nodes/sub-nodes/n8n-nodes-langchain.memorypostgreschat/)
