# Aceite de consultas naturais no AI Agent

## Evidencias recebidas

No agente nativo com qwen3:4b-instruct, uma continuacao sobre TLSV POA gerou afirmacao de ausencia de licenca com intermediateSteps vazio. A captura do n8n confirmou que nenhuma ferramenta foi usada naquela execucao. Uma conversa nova, iniciada com instrucao explicita para consultar a ferramenta, retornou uma licenca, matched=1, regional=REG_TLSV_POA, search vazio e 39 dias restantes no snapshot daquela consulta. Esse numero e evidencia historica, nao um valor esperado fixo para testes futuros.

O teste mudou a conversa e a instrucao inicial ao mesmo tempo. Nao comprova isoladamente que a memoria causou o erro nem que o agente passou a decidir consultar corretamente. As continuacoes corretas apos essa instrucao explicita nao sao suficientes como aceite de uso espontaneo de ferramentas.

## Proxima comparacao

Testar qwen3:8b no mesmo AI Agent nativo. As rodadas anteriores com 8B avaliaram o planejador JSON, nao esse fluxo de agente com ferramentas. O modelo ja esta instalado no Celeno; nao fazer download, conectar a internet ou alterar a arquitetura para esta comparacao.

Antes de alterar, guardar export fresco do workflow atual. No no Ollama Local, mudar apenas Model de qwen3:4b-instruct para qwen3:8b. Preservar temperatura 0.2, thinking desativado, contexto 8192, saida 2048, threads 8, credencial interna, prompt, ferramentas e memoria. Salvar e publicar o workflow atual, nao o Candidate. Fazer a troca sem consultas em andamento. Evitar manter os modelos 4B carregados durante a rodada; isso nao exige apaga-los do disco.

Nao mudar o modelo padrao do gerador enquanto essa comparacao nao estiver avaliada. A configuracao publicada depois da troca precisa ser reconciliada com um export atual se for aprovada.

## Roteiro sem instrucao indutora

Iniciar conversa nova pela interface que gera outra conversation_id; nao basta recarregar a pagina, pois o historico pode ser retomado. Nao incluir pedidos de uso de ferramenta, nomes tecnicos ou codigos REG_.

Conversa A:

1. Bom dia, tudo bem?
2. Quantos dias faltam para a licenca da Nutricar vencer?
3. E da TLSV POA?
4. Qual o resumo dos alertas ativos?

Conversa B, tambem nova:

1. Quando vence a licenca da TLSV POA?
2. E da Nutricar?

Variacoes adicionais devem incluir outras unidades autorizadas e perguntas nao presentes nessas conversas. Nao ajustar o prompt a partir de cada frase individual. Usar o mesmo roteiro com os dois modelos antes de concluir uma comparacao de qualidade.

## Criterios

- Cada resposta com fatos operacionais atuais precisa de chamada de ferramenta nesta interacao. Conferir intermediateSteps e a observacao; texto correto vindo apenas da memoria nao passa.
- Filtros, regional e atributos retornados precisam corresponder ao pedido. Trocar unidade nao pode reter a busca antiga.
- Conferir fatos contra o retorno atual do Sentinel. Ausencia de resultado, falha de consulta e lacuna de coleta sao situacoes distintas.
- Saudacao nao exige chamada de inventario. Identidade e permissoes continuam vindas do Sentinel.
- Registrar erros e latencia, inclusive carregamento inicial. Se houver falha de memoria, protocolo ou tool calling, guardar a evidencia em vez de mudar varias configuracoes simultaneamente.
- Para permissoes, repetir com usuario autorizado de escopo restrito e confirmar que a ferramenta nao entrega outra regional. Nunca alterar permissoes para conseguir um acerto.

Sucesso parcial nao autoriza anunciar o problema como resolvido. Um modelo maior pode continuar falhando. Falhas nesta comparacao nao justificam remover o agente, a memoria, o RAG planejado ou as protecoes de leitura.

## Retorno da configuracao

Se o 8B falhar ao carregar, exceder a capacidade disponivel ou piorar o funcionamento, restaurar somente Model=qwen3:4b-instruct e publicar. Preservar a correcao de regional e as ferramentas ja em uso. Nao reiniciar o Sentinel, reimportar JSON antigo ou mudar a rede para esse retorno.
