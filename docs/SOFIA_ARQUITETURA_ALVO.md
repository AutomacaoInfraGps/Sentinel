# Arquitetura alinhada da SofIA

Decisao alinhada com Roosevelt em 12/11/2026. Este documento orienta as proximas alteracoes da SofIA. Ele descreve o destino aprovado, nao uma implantacao ja realizada.

## Direcao acordada

A SofIA sera um AI Agent local, com memoria conversacional, ferramentas autorizadas e RAG sobre conhecimento interno. A prioridade e capacidade de interpretacao, continuidade da conversa e respostas fundamentadas. O servidor atual e temporario; suas limitacoes de desempenho nao justificam substituir silenciosamente essa arquitetura por um planejador de JSON.

Modelo, tamanho de contexto, armazenamento de recuperacao e hardware serao escolhidos por avaliacao. Um agente ou modelo maior nao garante qualidade por si so. Alteracoes de arquitetura precisam de alinhamento explicito com o usuario antes da implementacao correspondente.

## Componentes

1. Sentinel autentica o usuario, define identidade e permissoes, registra e acompanha a solicitacao.
2. n8n orquestra o AI Agent, o modelo Ollama local, a memoria e as ferramentas permitidas.
3. Memoria persistente mantem referencias da conversa, com isolamento por usuario e sessao. Nao substitui consultas atuais nem comprova fatos operacionais.
4. Ferramentas de leitura consultam dados atuais por APIs controladas. Escopo, validacao e auditoria permanecem no servidor. O modelo nao escolhe tokens, identidades, destinos HTTP ou permissoes.
5. RAG recupera documentacao e procedimentos internos autorizados antes de responder, com identificacao das fontes. A verificacao de acesso precede a entrega dos trechos ao modelo. Documentos recuperados sao dados, nao instrucoes de sistema nem autorizacao para executar acoes.
6. O agente redige a resposta natural a partir das evidencias. Deve distinguir coleta atual, conhecimento documental e historico de conversa e informar lacunas sem inventar fatos.

RAG integra o objetivo aprovado. Sua implementacao sera incremental, mas nao deve desaparecer do escopo durante a retomada do agente. Antes da integracao ser verificada, a interface e a documentacao nao devem apresenta-lo como disponivel.

## Isolamento e seguranca

Neste alinhamento, isolamento significa ausencia de acesso externo/internet durante a operacao. Continua necessaria comunicacao interna explicitamente autorizada entre n8n, Ollama, memoria, recuperacao documental e Sentinel. Nao significa conceder ao modelo uma ferramenta generica de rede.

Preservar a rede Docker interna existente. Nao conectar o Ollama principal ou o agente a uma rede externa para resolver downloads. Instalacao ou atualizacao de modelos e dependencias exige procedimento separado e aprovado. Nao usar modelos em nuvem, embeddings remotos, buscas externas ou provedores de fallback externos sem nova autorizacao explicita.

Nao disponibilizar shell, SQL livre, navegador, HTTP arbitrario ou ferramentas de escrita ao agente nesta etapa. Chamadas internas precisam de destinos e operacoes fixos e autorizacao real. A identidade de criador personaliza a conversa, sem elevar permissoes. Segredos nao devem entrar no prompt, memoria ou indice RAG.

## Estado atual e migracao

O export atual fornecido em `SofIA - Agente Sentinel v3 (1).json` ainda usa o planejador HTTP e memoria SQL manual. O export anterior possui um AI Agent com ferramentas e memoria, mas nao deve ser restaurado automaticamente. A comparacao esta em [Auditoria da retomada](SOFIA_AGENT_RESTORE_AUDIT.md).

Os scripts de contratos JSON, revisao e planejamento em etapas permanecem como historico experimental. Seus resultados nao autorizam substituir a arquitetura definida aqui. O gerador `sofia/n8n/build_readonly_workflows.py` ainda gera o fluxo controlado existente e nao implementa esta retomada.

Primeiro conferir o export atual do subworkflow referenciado por `Executar consulta autorizada`, ID `tJ1f4rJJ4aH9ATT5`. Depois preparar o candidato de agente preservando autenticacao, consulta autorizada, registro, cancelamento e entrega assincrona. Separar a memoria de homologacao da memoria atual. A configuracao de homologacao deve respeitar a validacao do ID de workflow no Sentinel, sem remover essa protecao para executar uma copia.

Os dois exports atuais ja foram conferidos e o candidato da primeira etapa foi gerado localmente. O [guia de homologacao](SOFIA_AGENTE_LOCAL_HOMOLOGACAO.md) registra a estrutura preparada, as verificacoes pendentes e a ausencia de integracao RAG nesta etapa. O fluxo publicado ainda nao foi substituido.

Decisao posterior do usuario: atualizar o workflow existente em vez de exigir uma entrada separada de homologacao. A [atualizacao do agente local](SOFIA_AGENTE_LOCAL_ATUALIZACAO.md) preserva o ID, webhook e protecoes atuais, com backup e publicacao manual. Essa decisao altera a estrategia de aplicacao, nao a arquitetura, as permissoes ou o modo somente leitura. O candidato independente continua separado e nao precisa ser publicado.

Publicacao exige revisao do candidato, backup, validacao real no n8n e aprovacao. Nenhum workflow, credencial, modelo ou configuracao de rede foi alterado para registrar este alinhamento.

## Verificacoes de aceite

- Conversa natural sem reativar consultas anteriores ou inventar dados operacionais.
- Continuidade, correcao e troca de regional sem herdar filtros indevidos.
- Consultas atuais com evidencia de ferramenta e autorizacao a cada chamada.
- Memoria isolada e comportamento correto quando o escopo do usuario muda.
- RAG com fontes, controle de acesso, atualizacao do indice e resposta honesta quando nao houver evidencias suficientes.
- Tratamento seguro de instrucoes maliciosas em mensagens, documentos e resultados.
- Cancelamento, paginacao, erros e lacunas de coleta sem respostas enganosas.
- Medicao separada de qualidade, latencia e consumo de recursos, sem usar apenas testes simulados como prova de inteligencia.

## Referencias locais

- [Base de conhecimento](../sofia/knowledge/README.md)
- [Documentacao da SofIA](../sofia/README.md)
- [Fluxo controlado e historico dos experimentos](SOFIA_WORKFLOW_CONTROLADO.md)
