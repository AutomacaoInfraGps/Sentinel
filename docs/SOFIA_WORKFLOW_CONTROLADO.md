# SofIA com consulta controlada e entrega assíncrona

## Direcao aprovada

Em 12/11/2026, o usuario alinhou a retomada de um **AI Agent local com memoria, ferramentas autorizadas e RAG**, sem acesso externo durante a operacao. Consulte [Arquitetura alvo](SOFIA_ARQUITETURA_ALVO.md). Este guia documenta o fluxo controlado existente e os experimentos anteriores. Seus comandos de geracao e importacao nao implementam a retomada do agente e nao devem ser aplicados como se o fizessem.

## Fluxo preparado

O modelo interpreta o pedido em um plano JSON pequeno. O Sentinel valida o plano, aplica o escopo assinado e monta a resposta operacional usando o inventário. Cada plano de consulta passa obrigatoriamente pelo endpoint `/api/internal/sofia/v1/assistant/query`.

Os recursos disponíveis são alertas atuais, firewalls, licenças, links, VPNs, servidores, APs, switches, Wi-Fi e regionais autorizadas. O modelo escolhe recurso, filtros, campos e paginação. Contagens e listas são formatadas pelo servidor. Conversas sociais recebem uma resposta curta do modelo.

O contexto enviado ao modelo contém identidade autenticada, até quatro mensagens curtas de usuário e assistente, incluindo respostas operacionais, e o último plano de consulta. As mensagens históricas são enviadas como turnos `user` e `assistant` em ordem. A identidade autenticada e o último plano ficam no contexto do sistema. A mensagem atual ocupa o último turno `user`. Papéis fora de `human` e `ai` são descartados durante a leitura do histórico. A memória usa a tabela isolada existente com o sufixo de sessão `:v4`. Isso inicia um contexto novo para este fluxo. O histórico visual já salvo no navegador continua disponível.

O gerador exporta `ler-contexto-curto-query.sql` para o campo Query de `Ler contexto curto`. A expressão de `Validar plano` reconhece uma regional mencionada de forma inequívoca usando `allowed_regionals` do Webhook e remove uma busca correspondente à regional anterior quando o escopo muda. Buscas por equipamentos ou produtos são preservadas. A autorização final continua sendo aplicada pelo Sentinel por meio do escopo assinado.

O chat recebe HTTP 202 e acompanha o resultado com requisições curtas. A mesma aba do navegador retoma o acompanhamento após recarregamento ou navegação pelo Sentinel. O botão de parada usa o controle de execução existente.

## Arquivos locais

Os candidatos gerados ficam em `instance/sofia-workflows/sofia-main-controlled.json` e `instance/sofia-workflows/sofia-inventory-controlled.json`. A pasta é ignorada pelo Git. Os candidatos mantêm os IDs dos workflows, o caminho do webhook e as referências às credenciais dos exports fornecidos.

Para gerar novamente na máquina de desenvolvimento, a partir da raiz do repositório, execute no PowerShell.

```powershell
.\venv313\Scripts\python.exe -m sofia.n8n.build_readonly_workflows `
  --main "$env:USERPROFILE\Downloads\SofIA - Agente Sentinel v3.json" `
  --inventory "$env:USERPROFILE\Downloads\SofIA Tool - Consultar Inventário Operacional.json"
```

## Experimento de planejamento em etapas

**Resultado recebido: reprovado para integracao.** A primeira execucao com qwen3:4b-instruct teve zero acertos nos vinte casos, com media de aproximadamente 11,19 segundos por pergunta. Todos os roteamentos usaram context_mode=new, inclusive as continuacoes. Treze casos foram rejeitados por campos invalidos, principalmente duplicados. Houve tambem busca repetindo a regional, contradicao no roteamento social, contagem com atributos especificos e quatro planos montados com filtros incorretos. A existencia de rejeicoes nao representa interpretacao correta. Esta variante nao deve substituir o workflow publicado nem ser integrada com base somente nos testes simulados. A revisao local da montagem das chamadas nao identificou substituicao da mensagem atual; isso nao verifica o processamento remoto pelo Ollama. Antes de outra suite completa, e necessario isolar a interacao entre instrucoes, contrato de saida e modelo com diagnosticos pequenos. Os comandos abaixo ficam registrados para reproducao, nao como recomendacao de publicacao.

Esta variante ainda nao deve ser publicada no n8n. O modo `--staged-contract` do avaliador importa `tests/manual/sofia_staged_planner.mjs` e faz duas chamadas locais por pergunta. A primeira classifica modo, recurso, apresentacao e continuidade. A segunda extrai somente os parametros permitidos para aquele recurso, ou produz uma resposta social. O codigo monta o plano e valida as combinacoes, sem executar consultas ao Sentinel.

Cada recurso possui um conjunto menor de campos e estados. Alertas nao aceitam firmware ou vencimento. Uma contagem nao aceita atributos especificos de itens. Nomes regionais precisam pertencer ao catalogo sintetico autorizado. O campo `inherit` enumera os filtros e atributos que devem ser copiados da consulta anterior. Valor explicito e heranca da mesma chave sao conflitantes. Perguntas novas nao herdam parametros. Busca e campos nao podem ser herdados entre recursos distintos; estado e regional precisam continuar compativeis. O codigo rejeita contradicoes em vez de repetir a chamada para tentar corrigir o plano. Essas validacoes nao comprovam que um filtro semanticamente valido foi realmente solicitado: a suite continua conferindo os pedidos completos.

O modo registra a saida bruta de cada etapa, o plano final ou a causa da rejeicao e o tempo total. As expectativas ficam somente no avaliador. Sao os dezesseis casos anteriores e quatro adicionais sobre firmware de switch, multiplos filtros, ampliacao regional e contagem de alertas por categoria e severidade. Compare os primeiros dezesseis separadamente com as rodadas anteriores. Esta variante usa paginacao fixa de 20 e 0; continuacao de paginas e integracao com autorizacao real precisam de trabalho posterior antes de publicacao.

Na maquina de desenvolvimento, copie os dois arquivos juntos, a partir da raiz do repositorio.

```powershell
scp .\tests\manual\sofia_planner_ollama_test.mjs .\tests\manual\sofia_staged_planner.mjs administrador@10.254.12.66:/tmp/
```

No Celeno, copie ambos para o container e use o modelo instalado que teve o melhor resultado anterior. A variante nao baixa modelos, nao modifica a rede e nao publica workflows.

```bash
sudo docker cp /tmp/sofia_planner_ollama_test.mjs sofia-n8n-1:/tmp/sofia_planner_ollama_test.mjs
sudo docker cp /tmp/sofia_staged_planner.mjs sofia-n8n-1:/tmp/sofia_staged_planner.mjs
sudo docker exec sofia-n8n-1 node /tmp/sofia_planner_ollama_test.mjs /tmp/sofia-main-controlled.json --staged-contract --model qwen3:4b-instruct
```

O comando retorna codigo 1 quando algum caso falha. Isso faz parte da avaliacao e nao implica falha de Docker. Os testes locais `node --test tests/unit/sofia_staged_planner_test.mjs` usam respostas simuladas e verificam montagem, validacao e avaliador completo. A execucao no modelo real ainda e necessaria. Aumentar o numero de chamadas pode elevar a latencia.

Somente apos conferir essa rodada deve ser preparada a integracao dos nos de intencao, parametros, contexto e conversa no n8n, com backup do workflow, preservacao do webhook e das credenciais, testes de escopo e cancelamento, paginacao, conversa nova e conversa existente. O retorno desta avaliacao isolada nao autoriza publicacao automatica.

### Diagnostico controlado do formato de saida

Apos a reprovacao do planejamento em etapas, `--format-diagnose` isola o parametro `format` da API. Usa o contrato anterior de extracao e somente duas perguntas: dias restantes de uma licenca em conversa nova e resumo de alertas com contexto anterior. Cada pergunta e executada com schema, `format="json"` e sem `format`, totalizando seis chamadas. Mensagens, modelo, contexto e opcoes de inferencia permanecem iguais dentro de cada comparacao. A instrucao de produzir um plano JSON continua presente nas tres condicoes. O diagnostico nao compara diretamente com o antigo agente do n8n e nao comprova uma causa com apenas duas perguntas.

O retorno inclui `formato` e `saida_bruta`, inclusive quando o JSON e invalido. Nao ha extracao permissiva de blocos Markdown, reparo de respostas ou remocao de filtros. Sem restricao de formato, texto fora do JSON falha no mesmo avaliador e permanece registrado. As chamadas sao sequenciais e a primeira pode incluir carregamento do modelo; os tempos nao constituem um benchmark controlado de desempenho. Os testes simulados verificam que somente `format` muda nas requisicoes comparadas e que a evidencia bruta e preservada.

Depois de copiar o avaliador atualizado para o Celeno e para o container, execute somente este modo, sem combinar outras modalidades.

```bash
sudo docker exec sofia-n8n-1 node /tmp/sofia_planner_ollama_test.mjs /tmp/sofia-main-controlled.json --format-diagnose --model qwen3:4b-instruct
```

Este diagnostico requer apenas o arquivo principal do avaliador. Nao altera workflows, dados, redes ou modelos instalados. Os criterios de avaliacao nunca sao enviados ao modelo.

O retorno real do diagnostico teve quatro falhas em seis chamadas. A pergunta sobre a licenca falhou nas tres condicoes: view=count nao entregava days_remaining, e search repetia a localidade; com schema, tambem faltou regional. O resumo de alertas falhou com schema ao acrescentar critical, mas passou em JSON livre e sem restricao de formato, com respostas brutas identicas entre essas duas condicoes. Esse resultado indica sensibilidade ao formato nesse caso, sem comprovar que o schema explica os demais erros. A primeira chamada levou 28,19 segundos e nao deve ser comparada diretamente com as chamadas aquecidas.

O modo `--json-contract` amplia esse controle para os mesmos dezesseis cenarios originais. Mantem o prompt de extracao, contexto, modelo e opcoes; somente substitui o schema por `format="json"`. Os filtros extras e atributos continuam sujeitos aos mesmos criterios estritos. Nao ha reparo de respostas. A saida inclui o JSON bruto. Esta comparacao ainda requer execucao real antes de qualquer integracao.

O retorno recebido da suite JSON livre teve sete acertos e nove falhas em dezesseis casos. Passaram troca simples de regional, resumo geral, firmware, velocidade, contagem de servidores offline, campos de APs offline e provedor de links offline. As falhas incluem contagem indevida para days_remaining, buscas redundantes por regional, campos inexistentes de alertas, filtros herdados indevidos e severidades concatenadas. Uma resposta repetiu a chave status: o JSON bruto continha high e depois active; JSON.parse conservou o ultimo valor, que foi reprovado pelo avaliador. O pedido social foi reconhecido como chat com resposta preenchida, mas falhou no contrato por omitir fields. Essa falha estrutural deve ser distinguida das falhas semanticas, sem alterar retrospectivamente a pontuacao. A variante nao esta aprovada para integracao. Remover o schema tambem remove da requisicao o catalogo completo de campos que existia nele; o prompt congelado nao repete esse catalogo completo. Isso limita a interpretacao do controle e impede atribuir todos os erros ao modelo ou somente ao formato.

A conferencia do export local `SofIA - Agente Sentinel v3.json`, datado de 9 de novembro de 2026, encontrou um AI Agent com memoria Postgres e ferramentas conectadas, com qwen3:4b-instruct operacional, temperatura 0.2 e numPredict 1024. O agente recebia identidade autenticada e mensagem atual e usava descricoes das ferramentas. Os candidatos de planejamento HTTP e os experimentos nao reproduzem essa arquitetura. O export local nao comprova qual workflow esta publicado atualmente. A proxima comparacao deve partir de um export atual do workflow em uso, preservando escopo assinado, consulta autorizada, cancelamento e entrega assincrona. Nao restaurar o export antigo automaticamente.

```bash
sudo docker exec sofia-n8n-1 node /tmp/sofia_planner_ollama_test.mjs /tmp/sofia-main-controlled.json --json-contract --model qwen3:4b-instruct
```

## Primeiro aplicar a revisão no Rigel

Para uma revisão apenas das instruções de identidade e conversa, o gerador também escreve `instance/sofia-workflows/interpretar-pedido-expression.txt`. Copie seu conteúdo com `.Trim()` para o campo Body em modo Expression do nó `Interpretar pedido`, mantendo o formato Raw e o Content Type `application/json`. Salve e publique o workflow principal. O arquivo incorpora `plan_prompt.txt` e o contrato JSON do modelo. A troca desse campo aplica o prompt revisado ao workflow existente.

A homologação de identidade deve incluir uma conversa nova com um criador configurado, um usuário comum e uma mensagem que declare uma identidade diferente. Confira o `user_context` autenticado no corpo enviado ao modelo e a resposta produzida em cada caso. Os testes automatizados verificam a transmissão desse contexto e a validade das expressões. O comportamento conversacional precisa de verificação com o Ollama em execução.

O prompt orienta uma nova consulta para todo pedido operacional, mesmo quando a memória contém uma resposta para a mesma pergunta. `previous_query` representa a última consulta executada e pode estar atrás do assunto das mensagens recentes. Ambos os formatos começam por `mode` no schema. A validação estrutural aceita texto livre em respostas sociais e depende da interpretação do modelo para escolher esse modo. A homologação com o Ollama deve incluir perguntas operacionais depois de respostas antigas incorretas e agradecimentos acompanhados de uma nova consulta. Confira `mode=query` e a execução autorizada em cada pedido de dados.

### Avaliação de interpretação no Celeno

O script `tests/manual/sofia_planner_ollama_test.mjs` lê a expressão do workflow gerado e executa seis cenários sintéticos contra `http://ollama:11434/api/chat` dentro do container n8n. Verifica intenção, recurso, regional, filtros e campos esperados. Não consulta nem altera o inventário ou a memória do Sentinel. O teste usa o Ollama local e pode consumir alguns minutos de CPU. Os resultados dessa avaliação devem ser conferidos antes de publicar uma revisão do prompt. Os testes unitários de estrutura e expressão não comprovam a interpretação do modelo.

Após copiar o script e o candidato para `/tmp` no Celeno, execute.

```bash
sudo docker cp /tmp/sofia_planner_ollama_test.mjs sofia-n8n-1:/tmp/sofia_planner_ollama_test.mjs
sudo docker cp /tmp/sofia-main-controlled.json sofia-n8n-1:/tmp/sofia-main-controlled.json
sudo docker exec sofia-n8n-1 node /tmp/sofia_planner_ollama_test.mjs /tmp/sofia-main-controlled.json
```

Cada linha informa o caso, o plano produzido e os critérios que falharam. O resultado final informa `casos` e `falhas`. Código de saída diferente de zero indica falha na avaliação.

Se as consultas operacionais falharem de forma sistemática, o argumento `--diagnose` compara a mesma pergunta em quatro condições. Usa o contrato atual, o contrato também descrito no prompt, o schema restrito à extração de consulta e o modo JSON guiado pelo contrato. A variante restrita à consulta é um controle de diagnóstico e força `mode=query`. Ela verifica os parâmetros extraídos, enquanto as demais também verificam a escolha do modo. O diagnóstico faz somente chamadas locais ao Ollama e não altera workflows publicados.

```bash
sudo docker exec sofia-n8n-1 node /tmp/sofia_planner_ollama_test.mjs /tmp/sofia-main-controlled.json --diagnose
```

O argumento `--flat-contract` avalia os seis cenários com um único objeto JSON contendo modo, resposta e parâmetros. A adaptação do schema e da instrução de saída ocorre somente na chamada de teste, mantendo as demais instruções e o modelo. Esse modo é uma hipótese de contrato alternativo e não modifica o candidato ou o workflow publicado. Use essa avaliação para comparar a seleção de intenção e a extração com o resultado do contrato `anyOf`.

```bash
sudo docker exec sofia-n8n-1 node /tmp/sofia_planner_ollama_test.mjs /tmp/sofia-main-controlled.json --flat-contract
```

O argumento `--intent-contract` avalia um objeto com `intent`, `parameters` e `reply`. `intent` reúne modo, recurso, apresentação e uso de contexto antes de gerar os campos e filtros de `parameters`. Esse contrato experimental existe apenas no teste e requer adaptação do validador antes de qualquer uso em produção. A avaliação mantém as perguntas, os critérios esperados e o modelo das demais modalidades.

```bash
sudo docker exec sofia-n8n-1 node /tmp/sofia_planner_ollama_test.mjs /tmp/sofia-main-controlled.json --intent-contract
```

O argumento `--model` permite repetir a avaliação com outro modelo já instalado, preservando o prompt, as opções de inferência e a modalidade selecionada. A saída identifica o modelo solicitado e o modelo informado na resposta. O script não faz download de modelos nem altera a configuração de produção.

```bash
sudo docker exec sofia-n8n-1 node /tmp/sofia_planner_ollama_test.mjs /tmp/sofia-main-controlled.json --flat-contract --model qwen3:4b
```

O argumento `--domain-context`, junto de `--flat-contract`, compara o contrato único com referências de operações e correspondências de nomes regionais. Os exemplos usam localidades fictícias diferentes dos cenários avaliados. A correspondência de nomes usa uma lista de regionais autorizadas sintética das fixtures. Seis casos adicionais verificam firmware, velocidade de link, contagem de servidores, identificação de APs, alertas de firewalls e links filtrados por estado com provedor. Os resultados desse modo não comprovam a integração do contexto autorizado em produção, que precisa ser implementada e verificada separadamente caso a avaliação seja aprovada.

```bash
sudo docker exec sofia-n8n-1 node /tmp/sofia_planner_ollama_test.mjs /tmp/sofia-main-controlled.json --flat-contract --domain-context
```

### Resultados recebidos da avaliação local no Celeno

O operador executou as comparações abaixo com as mesmas seis perguntas originais. Os testes de contexto de domínio também incluíram quatro perguntas adicionais na primeira revisão.

| Contrato | Modelo | Acertos |
| --- | --- | --- |
| Duas estruturas em `anyOf` | qwen3:4b-instruct | 1 de 6 |
| Objeto único | qwen3:4b-instruct | 2 de 6 |
| Intenção antes dos parâmetros | qwen3:4b-instruct | 1 de 6 |
| Objeto único | qwen3:4b | 2 de 6 |
| Objeto único com contexto de domínio, primeira revisão | qwen3:4b-instruct | 7 de 10 |
| Objeto único com contexto de domínio, segunda revisão | qwen3:4b-instruct | 10 de 12 |
| Objeto único com contexto de domínio, terceira revisão | qwen3:4b-instruct | 10 de 12 reportados pelo avaliador anterior |

Na segunda revisão, passaram as consultas de licenças, troca de regional, firmware, velocidade, contagem de servidores, APs offline, alertas de firewalls, links offline e conversa social. Persistiram dois erros. O pedido de alertas de switches selecionou inventário de switches. O resumo de alertas selecionou corretamente contagem, mas acrescentou o estado de equipamento `inactive` como filtro de severidade.

A terceira revisão do avaliador explicitou o contrato de categoria e severidade para todas as consultas de alertas. O adaptador operacional rejeita filtros de alertas incompatíveis com as severidades do mapa para evitar uma contagem zero causada por filtro inválido. Essa proteção exige atualização do código no Rigel. As variantes de contexto de domínio continuam restritas ao avaliador manual e ainda precisam de integração e validação do workflow antes da publicação.

Na terceira revisão executada no Celeno, os mesmos dois casos falharam. O resumo recebeu `critical` sem solicitação de severidade. A inspeção encontrou ainda um falso positivo no caso de links, que acrescentou `search=offline` ao estado `offline`. O avaliador atualizado exige filtros regional, status e search vazios quando a fixture não pede uma restrição. O resultado recebido corresponde, portanto, a nove planos que atenderam aos critérios de filtros conferidos manualmente e três com erros. A proteção contra severidades incompatíveis não detecta uma severidade válida inventada pelo modelo.

O modo `--context-ablation`, combinado com `--flat-contract --domain-context`, executa os três cenários problemáticos com e sem o histórico de licença, mantendo o mesmo prompt, modelo, schema e exemplos. No retorno recebido, somente o pedido de alertas de switches sem histórico passou. O resumo recebeu `critical` nas duas condições. Os links receberam `search=offline` nas duas condições e perderam o estado `offline` com histórico. Foram um acerto e cinco falhas. Esse resultado sustenta influência do histórico em parte dos erros e mantém erros de filtro mesmo sem histórico.

O modo experimental `--sparse-contract`, junto de `--flat-contract --domain-context`, exige somente mode, resource e view no schema. Filtros não solicitados podem ser omitidos; os exemplos demonstrativos usam essa representação. O avaliador aplica padrões apenas às chaves omitidas para comparar os planos com as mesmas expectativas. Filtros extras continuam sendo considerados erros. O modo pode ser combinado com `--context-ablation` para repetir os seis cenários de comparação. A alteração do contrato ainda precisa de execução no Ollama. Ela afeta exclusivamente o script manual e não foi integrada ao gerador, à validação do workflow ou à API.

A primeira execução do contrato opcional na comparação de histórico teve quatro acertos em seis. Os dois resumos e as duas consultas de links passaram. Os pedidos de alertas de switches selecionaram corretamente alerts e search=switch, mas acrescentaram critical nas duas condições. A revisão seguinte descreve os filtros no schema e inclui um par de exemplos demonstrativos de outra categoria, com severidade explícita e com severidade ausente. A suíte completa agora possui dezesseis casos, incluindo severidade crítica, severidade alta, todas as severidades e remoção da severidade numa continuação. Os exemplos novos não usam as perguntas de teste. O resultado dessa execução está registrado a seguir.

O retorno da suíte completa dessa revisão teve dez acertos e seis falhas, com sete acertos nos doze casos originais e três nos quatro casos novos. Falharam a licença da Nutricar, o firmware de Araras, a velocidade dos links de Campinas, os campos explícitos de APs, o provedor dos links offline e a continuação que deveria remover a severidade preservando a categoria VPN. A licença recebeu critical e uma busca redundante por Nutricar. O firewall recebeu online e search=firewall sem solicitação. A velocidade foi convertida em search=velocidade. Os pedidos de APs e links omitiram fields. A continuação perdeu search=vpn. A suíte ampliada expôs regressões de atributos e continuidade apesar da melhora nos três cenários de comparação. Essa variante permanece experimental, sem comprovação de adequação para publicação.

### Extração com campos obrigatórios e contexto em dados

O modo experimental `--extraction-contract` usa os mesmos dezesseis casos. Exige mode, resource, view e fields, preservando filtros opcionais. Um prompt consolidado distingue o objetivo da consulta, os atributos solicitados e as restrições. O avaliador envia uma mensagem de sistema e um objeto de dados com mensagem atual, identidade sintética, correspondências regionais, último plano executado e até duas mensagens anteriores do usuário. As respostas anteriores do assistente são excluídas nessa variante. O modo não modifica o workflow exportado nem publica configurações.

A ausência de fields é contabilizada como falha inclusive em conversa social, cujo valor esperado é um array vazio. Os padrões de filtros vazios existem somente para comparar chaves omitidas. Os filtros e atributos explícitos continuam sujeitos às expectativas dos testes. A compatibilidade de planos compactos com a API e a validação do workflow exige implementação e teste antes de eventual integração.

No Celeno, após copiar o script atualizado para o container, execute a avaliação.

```bash
sudo docker exec sofia-n8n-1 node /tmp/sofia_planner_ollama_test.mjs /tmp/sofia-main-controlled.json --extraction-contract
```

A execução confirmada com o script de 25.287 bytes teve onze acertos reportados e cinco falhas. Nutricar recebeu search em vez de regional e view=count para um atributo numérico. O resumo geral recebeu critical. Alertas de firewalls perderam a categoria e selecionaram contagem. VPNs de todas as severidades receberam critical, e a continuação perdeu também a categoria VPN. Na maior parte das chamadas, a duração foi de aproximadamente cinco a dez segundos; a primeira levou 27,56 segundos.

A inspeção identificou ainda um falso positivo nos alertas críticos de APs. O plano acrescentou expires_at, firmware, speed e provider em fields sem solicitação. O avaliador passou a rejeitar campos adicionais além dos atributos esperados pela fixture e dos identificadores básicos name, regional e status. Sob esse critério, a rodada tem dez planos aprovados e seis com erros. Esse critério avalia a correspondência ao pedido, sem alterar nem completar o plano do modelo. Os testes locais usam respostas simuladas para conferir a montagem das chamadas, a separação do histórico e a rejeição de campos obrigatórios ausentes ou adicionais indevidos. A variante continua experimental.

### Conferência experimental antes da consulta

O modo `--review-contract` usa a extração anterior e acrescenta uma chamada de revisão por caso ao mesmo Ollama local. O revisor recebe somente o contrato, a mensagem atual, a identidade sintética, o contexto pertinente e candidate_plan. As expectativas das fixtures e os erros calculados pelo avaliador permanecem fora das duas chamadas. A revisão pode confirmar ou corrigir o plano; ela também pode introduzir erros, que são medidos pela mesma suíte.

O retorno inclui plano_inicial, erros_iniciais, o plano final, os erros finais e os tempos separados de interpretação e revisão. O total inclui as duas chamadas. O resumo informa falhas_iniciais e falhas após revisão. A suíte possui dezesseis casos e executa até trinta e duas chamadas. Toda chamada é somente de inferência no endereço privado do Ollama, sem consulta ao Sentinel ou alteração do banco.

```bash
sudo docker exec sofia-n8n-1 node /tmp/sofia_planner_ollama_test.mjs /tmp/sofia-main-controlled.json --review-contract
```

A execução recebida com qwen3:4b-instruct reportou seis falhas iniciais e seis finais em dezesseis casos. Cada revisão acrescentou aproximadamente quinze a dezenove segundos. O revisor recuperou a busca por firewalls, mas manteve view=count numa pergunta que pedia uma lista. Também alterou a regional correta REG_TLSV_POA para REG_TLSV_PO. O avaliador passou a exigir view=list nos pedidos de identificação de alertas de switches e firewalls. Aplicando esse critério ao retorno recebido, são dez acertos iniciais e nove finais. A revisão não foi integrada ao gerador de workflows.

O próximo controle usa o modelo qwen3:4b já instalado com o mesmo contrato de extração, sem a chamada adicional de revisão. Essa comparação mantém prompt, contexto e schema e muda somente o modelo solicitado. Não há download nem publicação de workflows.

```bash
sudo docker exec sofia-n8n-1 node /tmp/sofia_planner_ollama_test.mjs /tmp/sofia-main-controlled.json --extraction-contract --model qwen3:4b
```

Os testes locais conferem com respostas simuladas a montagem das duas chamadas, a ausência de gabaritos no pedido enviado ao revisor, a seleção do modelo e a rejeição de contagens em pedidos de listas. A opção experimental de revisão deve mostrar revisao=true no início de cada caso. Opções desconhecidas passam a gerar erro para evitar executar silenciosamente outra modalidade.

O contrato JSON enviado ao Ollama possui dois formatos em `anyOf`. Consultas contêm `context_mode`, `mode=query` e o objeto `query` com os parâmetros. `context_mode=new` identifica um pedido independente e permite remover a regional anterior quando ela estiver ausente da mensagem atual. `context_mode=continue` permite preservar o escopo da consulta anterior. Pedidos de alertas usam o recurso `alerts`, com a categoria em `search`. Conversa, esclarecimento e domínio indisponível contêm somente `mode` e `reply` preenchido. O nó `Validar plano` converte os dois formatos para o plano interno usado pelas etapas seguintes e mantém compatibilidade com os formatos anteriores. Atualize juntos o Body de `Interpretar pedido` e a expressão `plan` de `Validar plano` antes de publicar. Teste uma consulta seguida de um pedido social, uma continuação operacional e uma pergunta independente sobre outro recurso. Um plano social com resposta vazia deve ser rejeitado pela validação.

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
