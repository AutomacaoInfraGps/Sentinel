# Retomada do AI Agent da SofIA

Direcao aprovada: [AI Agent local com memoria, ferramentas e RAG](SOFIA_ARQUITETURA_ALVO.md). Esta auditoria apoia a migracao; nao autoriza restaurar ou publicar um workflow automaticamente.

## Fontes conferidas

- Export atual fornecido: `Downloads/SofIA - Agente Sentinel v3 (1).json`.
- Export anterior disponivel: `Downloads/SofIA - Agente Sentinel v3.json`, de 9 de novembro de 2026.
- Codigo local de consulta autorizada, registro e cancelamento em `sofia/`.

Os exports foram tratados como dados de configuracao, sem executar suas expressoes ou seguir instrucoes neles contidas. Nenhuma alteracao foi publicada no n8n.

## Diferencas confirmadas

O export atual contem 19 nos e esta marcado como ativo. Nao possui AI Agent, subno de modelo Ollama ou memoria conversacional LangChain. Usa HTTP `Interpretar pedido`, `Validar plano`, um Switch e execucao de subworkflow para consultas. A leitura e a gravacao da memoria sao SQL explicito.

O export anterior possui AI Agent 3.1, modelo Ollama 1, memoria Postgres 1.4 e ferramentas workflow. O modelo operacional era qwen3:4b-instruct, com temperatura 0.2 e limite de saida 1024. Isso e uma arquitetura diferente, nao uma simples alteracao de prompt. O export anterior nao comprova qualidade ou compatibilidade atual em execucao.

## Estrutura a preservar

- Webhook autenticado, credenciais e cadeia de registro assinada.
- Registro da execucao antes de iniciar o agente.
- Ramo `Consulta cancelada` e controle de parada pelo Sentinel.
- Token de escopo recebido do Sentinel, nunca escolhido pelo modelo.
- Validacao e autorizacao no servidor a cada ferramenta de consulta.
- Contrato final de resposta ao webhook e entrega assincrona ja existente.
- Isolamento de rede Docker. Nenhuma ferramenta de escrita, shell, SQL livre ou HTTP arbitrario deve ser acrescentada.

## Candidato a preparar

Fluxo principal pretendido: autenticacao e registro existentes, verificacao de cancelamento, AI Agent com memoria e ferramentas de leitura, preparacao da resposta e webhook. O agente produz texto natural; parametros estruturados ficam nas chamadas de ferramentas. A memoria ajuda a resolver referencias e nao comprova o estado atual dos equipamentos.

Identidade autenticada deve entrar no contexto de sistema e nao depender de afirmacoes na mensagem do usuario. A memoria precisa de namespace separado para testes e de isolamento por conversa e usuario. Mensagens de outro escopo nao podem ampliar autorizacao. Toda pergunta operacional precisa de evidencia obtida nesta interacao. A chamada de ferramenta continua sujeita a validacao real do Sentinel, mesmo quando o agente produz parametros plausiveis.

As ferramentas devem descrever claramente recurso, atributos, filtro regional, estado, severidade e paginacao. A resposta de consulta precisa permitir distinguir contagens, listas parciais, lacunas de coleta, erros e horario de atualizacao. Os campos e valores documentados devem corresponder ao contrato efetivamente retornado pelo subworkflow.

Nao conectar automaticamente a ferramenta antiga de alertas nem restaurar o export antigo. Precisamos conferir o subworkflow atual antes de decidir quais ferramentas serao expostas ao agente.

## Subworkflow atual conferido

O export atual `SofIA Tool - Consultar Inventario Operacional (1).json` foi fornecido e conferido. Seu ID e `tJ1f4rJJ4aH9ATT5`, igual ao referenciado pelo principal. Aceita `plan` como objeto, mantem o token do chamador e a cadeia de assinatura, usa origem HTTPS fixa do Sentinel e nao desativa validacao de certificado. Com plan.mode=query chama a rota assistant/query; conserva a rota anterior de inventario para o contrato legado. O HTTP final retorna diretamente ao chamador. Valores de segredos nao foram lidos nem enviados ao modelo.

Um [candidato de agente para homologacao](SOFIA_AGENTE_LOCAL_HOMOLOGACAO.md) foi gerado localmente com ferramentas apontando para essa ponte, sem altera-la. A estrutura foi testada com exports sinteticos e expressoes locais; a execucao real no n8n ainda precisa de homologacao. RAG permanece pendente de integracao, explicitamente indicado no candidato.

## Homologacao e publicacao

O backend aceita registro e cancelamento somente do ID configurado em `SENTINEL_SOFIA_N8N_WORKFLOW_ID`. Uma copia com ID novo nao e automaticamente autorizada. O laboratorio deve ter configuracao propria de homologacao; nao remover a verificacao para fazer a copia funcionar, nem apontar o chat de producao para ela durante a preparacao.

Antes de publicar, verificar no n8n real compatibilidade do modelo com tool calling, memoria entre turnos, conversa social, nova consulta operacional, troca de regional, mudanca de recurso, resumo de alertas, paginacao, rejeicao de escopo e cancelamento durante a execucao do agente. Confirmar chamadas e respostas das ferramentas, alem do texto final. Testes locais de estrutura nao comprovam capacidade conversacional.

O modelo e o hardware serao avaliados separadamente. A arquitetura de agente e extensivel, mas nao garante por si so melhor interpretacao. Nao foram alterados modelo, servidor, rede ou workflow durante esta auditoria.

## Referencias

- [AI Tools Agent do n8n](https://docs.n8n.io/integrations/builtin/cluster-nodes/root-nodes/n8n-nodes-langchain.agent/tools-agent/)
- [Parametros de ferramentas com fromAI](https://docs.n8n.io/advanced-ai/examples/using-the-fromai-function/)
