# Atualizacao do workflow atual para AI Agent local

O usuario autorizou atualizar o workflow existente, mantendo a pagina `/sofia`, a autenticacao AD, o escopo imposto pelo Sentinel e ferramentas somente de leitura. A copia de homologacao `zxUluLOm3QCDKhVj` deixa de ser um requisito para essa troca. Nao foi implementada pagina ou rota alternativa no Sentinel.

## Arquivos preparados

- Atualizacao privada: `instance/sofia-workflows/sofia-main-agent-update.json`.
- Copia exata do export fornecido: `instance/sofia-workflows/sofia-main-before-agent-55bccf38dee3.json`.
- Gerador: `sofia/n8n/build_agent_workflow.py`, com `--update-existing --expected-id`.

A copia local representa o export recebido, nao um backup verificado do estado remoto no instante da troca. Fazer tambem um export fresco do n8n antes de importar. Nenhum desses arquivos executa publicacao automaticamente.

## O que muda

Substitui o planejador HTTP, a validacao de plano e o armazenamento manual da conversa por AI Agent, Ollama local, memoria Postgres e tres ferramentas de leitura: alertas, licencas e inventario. Preserva o ID `I4l72qvM1AoWvJhi`, nome, parametros completos do Webhook, webhookId, referencias de credenciais, registro de execucao, ramo de cancelamento, configuracoes do workflow e contrato final reply.

As ferramentas continuam chamando o subworkflow existente `tJ1f4rJJ4aH9ATT5`, sem altera-lo. O token de escopo vem do Sentinel, nunca da IA. A verificacao de permissoes no backend continua obrigatoria. Nao ha ferramentas de escrita, AD, shell, SQL livre ou rede arbitraria. A configuracao de rede Docker nao muda. Nao e preciso trocar variaveis de workflow/webhook do Sentinel nem implantar codigo Python para esta substituicao do JSON.

A nova memoria tem sufixo `:agent-v1`, distinto de `:v4` e `:agent-lab-v1`, sem excluir o historico antigo. RAG continua no escopo da arquitetura, mas ainda nao esta conectado nesta etapa. O modelo inicial e qwen3:4b-instruct; a retomada do agente nao comprova automaticamente melhora de interpretacao.

## Preparacao local

```powershell
.\venv313\Scripts\python.exe -m sofia.n8n.build_agent_workflow `
  --main "$env:USERPROFILE\Downloads\SofIA - Agente Sentinel v3 (1).json" `
  --inventory "$env:USERPROFILE\Downloads\SofIA Tool - Consultar Inventário Operacional (1).json" `
  --previous "$env:USERPROFILE\Downloads\SofIA - Agente Sentinel v3.json" `
  --update-existing --expected-id I4l72qvM1AoWvJhi
```

Usar o nome real do arquivo do inventario em Downloads, incluindo acentos quando presentes. O gerador recusa ID divergente, sobrescrita de export de origem e dados fixados nos exports. O backup local inclui um hash do conteudo e nao sobrescreve um arquivo divergente. O modo padrao sem `--update-existing` continua gerando apenas a copia independente de homologacao.

## Aplicacao manual

Reserve uma janela curta sem consultas em andamento. A importacao CLI pode desativar o workflow; ate publica-lo, o chat pode ficar indisponivel. Nao anunciar disponibilidade antes da verificacao real.

1. No editor, baixar um export fresco de `SofIA - Agente Sentinel v3` e guardar o arquivo para restauracao.
2. Copiar a atualizacao da maquina de desenvolvimento para o Celeno.

```powershell
scp .\instance\sofia-workflows\sofia-main-agent-update.json administrador@10.254.12.66:/tmp/
```

3. No Celeno, copiar o arquivo e importar especificamente esse workflow.

```bash
sudo docker cp /tmp/sofia-main-agent-update.json sofia-n8n-1:/tmp/sofia-main-agent-update.json
sudo docker exec -u root sofia-n8n-1 chown node:node /tmp/sofia-main-agent-update.json
sudo docker exec -u root sofia-n8n-1 chmod 600 /tmp/sofia-main-agent-update.json
sudo docker exec -u node sofia-n8n-1 n8n import:workflow --input=/tmp/sofia-main-agent-update.json
```

4. Recarregar o editor e abrir o workflow de ID `I4l72qvM1AoWvJhi`, nao a copia Candidate. Conferir o diagrama, as credenciais locais de modelo e memoria, os destinos das tres ferramentas, o metodo POST do registro, o caminho original do Webhook e o ramo de cancelamento.
5. Publicar esse workflow pela interface do n8n. O subworkflow existente nao precisa ser reimportado ou alterado. Nao publicar a copia Candidate para esta troca.
6. Abrir uma conversa nova na pagina `/sofia` existente e acompanhar os passos intermediarios do agente nas execucoes do n8n.

A documentacao oficial informa que a importacao atualiza workflows pelo ID e os desativa por padrao. A publicacao e uma etapa separada. Se o editor indicar incompatibilidade ou a nova versao nao atender o webhook, nao improvisar alteracoes no servidor ou nas permissoes: registrar o erro e restaurar o backup.

## Verificacao em execucao

O [aceite de perguntas naturais](SOFIA_AGENTE_ACEITE_NATURAL.md) registra a falha observada de resposta sem ferramenta e o proximo controle com o modelo 8B no agente nativo. A instrucao explicita do usuario para consultar uma ferramenta nao e criterio suficiente de sucesso.

- Saudacao e pedido social devem receber resposta natural, sem leitura de inventario.
- Contagem de servidores offline deve chamar a ferramenta e respeitar o estado.
- Dias restantes da licenca da Nutricar deve chamar a ferramenta de licencas, com regional correta e view=list/detail.
- Troca para TLSV POA deve substituir a localidade sem reter search=Nutricar.
- Resumo de alertas deve usar todas as severidades quando o usuario nao restringir.
- Um usuario de escopo restrito deve receber apenas dados autorizados pelo backend. Criador nao ganha permissao adicional.
- Interromper uma consulta deve cancelar a execucao desse mesmo ID e descartar respostas tardias.
- Confirmar continuidade da memoria em turnos sociais e operacionais, sem copiar fatos antigos como atuais.

Se falhar uma ferramenta ou o tool calling, usar os erros e parametros da execucao para diagnosticar. Testes simulados nao comprovam qualidade do modelo. Nao completar dados manualmente nem restaurar o planejador como mudanca de arquitetura sem combinar com o usuario.

## Restauracao

Usar o export fresco baixado antes da troca; conferir que seu ID e `I4l72qvM1AoWvJhi`. Copia-lo para o Celeno, para o container e importar com `n8n import:workflow --input=...`, seguindo os mesmos cuidados de permissao. Depois reabrir e publicar o workflow anterior no editor. Se o backup fresco nao estiver disponivel, a copia local preservada do export fornecido e um ponto anterior conhecido, mas pode nao conter mudancas remotas posteriores.

Nao apagar tabelas ou historico de memoria para restaurar. Nao alterar autenticacao, escopo, ID autorizado ou URL do Sentinel para contornar erros.

## Correcao de regional na entrada da ferramenta

A execucao real da continuacao sobre TLSV POA chamou Consultar_licencas com search="TLSV POA" e sem regional. A ferramenta retornou matched=0 com regional vazio; portanto, consultou texto no inventario autorizado em vez de restringir a unidade. Essa evidencia nao demonstra ausencia de licenca na regional. Nao foram constatados tokens invalidos ou ausencia de autorizacao nessa execucao.

Uma segunda execucao chamou a ferramenta com regional e search vazios. Retornou matched=49, displayed=20 e next_offset=20. Essa pagina parcial tambem nao permite afirmar que TLSV POA nao possui licenca: a consulta nem restringiu a regional solicitada.

O gerador incorpora `resolve_tool_regional.js` na entrada das ferramentas. Quando a mensagem atual menciona o nome normalizado de exatamente uma regional em allowed_regionals e regional esta vazio, preenche regional com esse codigo autorizado, inclusive se search tambem estiver vazio. Se search repetir exatamente essa mesma regional, remove apenas essa repeticao. Nomes sao comparados sem prefixo REG_, acentos, diferencas de caixa e separadores. Buscas parciais, nomes nao autorizados, referencias ambiguas e conflitos com uma regional explicita diferente nao sao reinterpretados. Buscas por produtos e categorias nao sao apagadas. O backend e a assinatura do token continuam sendo a autoridade final de acesso.

Essa correcao atua quando a ferramenta e chamada. Nao resolve, por si so, respostas operacionais sem chamada de ferramenta ou conclusoes indevidas a partir de paginas parciais em outras consultas. Esses comportamentos continuam sujeitos ao aceite em execucao real.

As expressoes atualizadas ficam em `instance/sofia-workflows/consultar-licencas-plan-expression.txt`, `consultar-alertas-plan-expression.txt` e `consultar-inventario-plan-expression.txt`. O gerador as escreve junto do workflow; tambem podem ser geradas pela funcao `export_tool_expressions`. Elas sao especificas de cada ferramenta e nao devem ser trocadas entre si.

Para corrigir a ocorrencia observada, baixar um backup atualizado e substituir somente o campo plan de Consultar licencas no workflow atual. No PowerShell de desenvolvimento:

```powershell
Set-Clipboard -Value ((Get-Content .\instance\sofia-workflows\consultar-licencas-plan-expression.txt -Raw -Encoding UTF8).Trim())
```

Colar no campo plan em modo Expression, salvar e publicar o workflow atual. Nao reimportar o JSON inteiro para esta correcao pontual e nao trocar credenciais. Depois repetir uma consulta direta sobre a licenca de TLSV POA e a continuacao apos Nutricar. Conferir a query efetivamente retornada pela ferramenta: regional=REG_TLSV_POA e search vazio, mantendo days_remaining. O resultado real e a resposta final ainda precisam ser conferidos; testes locais nao comprovam que a coleta possui os dados naquele instante.

## Referencia

[CLI oficial do n8n: importacao e publicacao](https://docs.n8n.io/hosting/cli-commands/)
