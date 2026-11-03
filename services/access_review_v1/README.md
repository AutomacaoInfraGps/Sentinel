# Revisao de Acessos integrada ao Sentinel

A automacao faz parte deste repositorio. A pagina `/revisao-acessos` executa as areas Windows, Linux, ADManager e Firewalls, isoladas ou em lote, pela mesma fila. O resultado e gravado diretamente no SQLite local e aparece no sino existente para operadores.

## Preparacao

Na raiz do Sentinel, usando seu ambiente Python:

```powershell
.\venv\Scripts\python.exe -m services.access_review_v1.setup
```

Esse comando cria os arquivos abaixo somente quando ausentes. Nao sobrescreve configuracao existente.

| Arquivo local | Preencher |
| --- | --- |
| `instance/access_review/config/auditorias.json` | Areas habilitadas, tentativas, intervalo, timeout, retencao e limpeza de prints |
| `instance/access_review/config/linux.json` | URLs do Zabbix/Grafana e opcoes do navegador |
| `instance/access_review/config/admanager.json` | URL do ADManager e opcoes do navegador |
| `instance/access_review/config/firewalls.json` | URLs e ADOMs de FortiAnalyzer/FortiManager |
| `instance/access_review/config/notifications.json` | `sino_habilitado`: booleano |
| `instance/access_review/credentials/credentials.json` | Referencias `credential_ref` ao cofre do Sentinel; sem senhas neste arquivo |

### Cadastro manual no cofre

O Sentinel nao executa estes comandos automaticamente. Eles sao instrucoes para o responsavel pelo ambiente cadastrar os acessos, sem colocar senha em arquivo ou na linha de comando. Abra um PowerShell na raiz do Sentinel com **a mesma conta Windows que executa o processo web** e rode somente os sistemas que serao auditados:

Cadastre cada acesso usando a mesma conta Windows que executa o Sentinel:

```powershell
.\venv\Scripts\python.exe -m services.access_review_v1.configure_credentials zabbix
.\venv\Scripts\python.exe -m services.access_review_v1.configure_credentials grafana
.\venv\Scripts\python.exe -m services.access_review_v1.configure_credentials admanager
.\venv\Scripts\python.exe -m services.access_review_v1.configure_credentials fortianalyzer
.\venv\Scripts\python.exe -m services.access_review_v1.configure_credentials fortimanager
```

Usuario e senha sao solicitados com entrada oculta e armazenados pelo `core.secret_store.JsonSecretStore`, com DPAPI CurrentUser. O manifesto JSON contem apenas referencias. A versao anterior `credentials.env` deixou de ser lida; ela nao e migrada automaticamente. Se ainda existir preenchida, remova-a com o procedimento operacional da equipe apos cadastrar e testar os acessos no cofre. O cofre e resolvido apenas pelo coletor durante a execucao; os testes usam um cofre simulado.

| Comando | Referencias gravadas no cofre | Usado por |
| --- | --- | --- |
| `configure_credentials zabbix` | `access-review/zabbix/username` e `/password` | Linux / Zabbix |
| `configure_credentials grafana` | `access-review/grafana/username` e `/password` | Linux / Grafana |
| `configure_credentials admanager` | `access-review/admanager/username` e `/password` | ADManager Plus |
| `configure_credentials fortianalyzer` | `access-review/fortianalyzer/username` e `/password` | Firewalls / FortiAnalyzer |
| `configure_credentials fortimanager` | `access-review/fortimanager/username` e `/password` | Firewalls / FortiManager |

Em cada comando, informe primeiro o usuario e depois a senha quando solicitado. As duas entradas ficam ocultas. Nao informe credenciais como argumento, nao edite o arquivo do cofre manualmente e nao execute o cadastro com uma conta Windows diferente da conta do Sentinel. A mensagem `Acesso salvo no cofre para a conta Windows atual.` confirma apenas a gravacao; a homologacao final ocorre executando a auditoria isolada daquela area.

As URLs usam HTTPS com validacao de certificados por padrao. Instale a cadeia de confianca corporativa no Windows. O ADManager deste ambiente usa HTTP e seu exemplo define `allow_http: true`; essa excecao fica limitada ao arquivo `config/admanager.json`. O trafego de login do ADManager nao e criptografado, portanto o acesso deve permanecer em rede interna controlada e ser aceito pelo responsavel pelo ambiente. Linux e Firewalls continuam com `allow_http: false`. `verify_tls: false` permanece uma excecao separada para certificados HTTPS nao confiaveis e nao foi habilitada.

A conta operacional deve ter somente leitura nos sistemas auditados. Restrinja por ACL o acesso a `instance/access_review`, incluindo modelos, evidencias, diagnosticos e bancos. O `.gitignore` evita versionamento; ele nao substitui as permissoes NTFS. A sessao grafica deve ser dedicada a auditoria, pois as capturas incluem o monitor inteiro.

Fornecer em `instance/access_review/modelos/`:

- `Auditoria Galaxia Servidores Windows - Exemplo.docx`
- `Auditoria Galaxia Linux - Exemplo.docx`
- `Auditoria Galaxia ADManager - Exemplo.docx`
- `Auditoria Galaxia Firewalls - Exemplo.docx`

Os exemplos vazios versionados ficam em `services/access_review_v1/config/`. Os arquivos preenchidos, modelos, evidencias, bancos e resultados ficam em `instance/`, ignorada pelo Git. Nao e necessario alterar `environment.json`, configurar HMAC, URL de retorno ou caminho de outro repositorio.

## Execucao

A conta que inicia o Sentinel deve possuir acesso de leitura aos sistemas auditados. A captura exige Windows com sessao grafica aberta, monitor ativo e Microsoft Edge. A auditoria Windows exige RSAT/ActiveDirectory, ADUC, dsacls e Server Manager. As dependencias Python sao as do `requirements.txt` do Sentinel; o runner sempre usa o mesmo interpretador do processo web. A automacao nao instala dependencias durante uma execucao.

Preencha apenas as configuracoes das areas que pretende executar. A API valida a selecao, os modelos e as configuracoes antes de enfileirar. O conteudo das credenciais e validado pelo coletor na execucao e nao e devolvido ao navegador.

`POST /api/revisao-acessos/executions` exige sessao de operador e CSRF e recebe `{"mode":"completa","audits":["linux","firewalls"]}`. O painel principal oferece somente `Iniciar revisao`. O historico mostra os icones de cada area e um indicador sobreposto: X vermelho para falha de coleta, ! amarelo para falha de geracao/validacao e sinal verde de conclusao. Uma unica legenda explica esses estados. Falhas anteriores sem classificacao tambem exibem X vermelho; a explicacao ao passar o mouse informa que a etapa nao foi registrada, sem presumir uma causa.

`Gerar documentos novamente` aparece na execucao com falha de geracao e expande a selecao individual. A API recebe `{"mode":"somente_montagem","audits":["linux"],"source_execution_id":"<uuid-original>"}`. A nova execucao entra na mesma fila, registra a origem e possui seu proprio log. A recuperacao exige comprovacao de coleta concluida pelo processo e evidencias completas preservadas em `dados/recuperacao/<uuid>/<area>/home`; modelos, inventario e insumos necessarios tambem sao preservados, sem credenciais. Os arquivos sao conferidos por SHA-256 antes de enfileirar e novamente ao executar. A geracao usa uma copia de trabalho isolada em `runtime/regeneracao/<novo-uuid>/<area>/`, sem reutilizar a pasta de capturas da rodada atual. Coleta incompleta, arquivos ausentes ou alterados impedem a recuperacao. Retorna `202` com `job_id`; selecao invalida retorna `400`, evidencias indisponiveis `409`, fila cheia `429` e configuracao indisponivel `503`.

`GET /api/background-jobs/<job_id>` retorna estados `queued`, `running`, `completed` ou `failed` e eventos amigaveis por etapa. A fila e FIFO, persistida em `instance/access_review/queue.sqlite3`, com consumidor unico protegido entre processos. O limite e de 100 pedidos aguardando. Pedidos pendentes sao retomados ao abrir a pagina ou enfileirar. Uma execucao que estava em andamento quando o Sentinel parou fica marcada como interrompida, sem repeticao automatica da coleta. Confira e encerre janelas remanescentes da sessao antes de iniciar outro lote apos uma parada abrupta.

Cada area tem tentativas e timeout configuraveis. A falha de uma area nao impede o processamento das seguintes. O timeout encerra a arvore do processo de captura. A barra informa areas realmente processadas; o resultado final exige um DOCX novo ou atualizado que passe na validacao Open XML.

A barra de progresso usa marcos reais publicados pelos coletores: preparacao, acessos aos sistemas, capturas, montagem e validacao. Nao existe preenchimento artificial por tempo. O arquivo temporario de progresso aceita somente um identificador de etapa, percentual e contadores numericos, fica em `instance/access_review/runtime/` e e removido ao final da tentativa; saida bruta, URLs, credenciais e conteudo das evidencias nao sao enviados ao navegador. Tentativas que ainda terao repeticao aparecem em amarelo, conclusoes em verde e falhas definitivas em vermelho.

## Dados e resultados

O painel mostra somente o alvo em processamento; os eventos completos ficam no visualizador de log com rolagem interna. O bot AD encerra a area Windows depois de cinco regionais consecutivas com falha, reiniciando o contador quando uma regional termina com sucesso. Nessa condicao nao repete o lote Windows e segue para a proxima area selecionada. O botao de interrupcao solicita o encerramento de toda a execucao selecionada, inclusive suas areas restantes; outros pedidos da fila continuam independentes.

Neste ambiente, Linux e Firewalls usam `verify_tls: false` nas configuracoes locais para contornar `NET::ERR_CERT_AUTHORITY_INVALID`, confirmado nos prints de erro. A excecao aplica-se aos contextos de navegador desses coletores; os exemplos versionados mantem `verify_tls: true`. Para voltar a validar a identidade HTTPS dos servicos, instale a cadeia corporativa e reative essa opcao.

Documentos montados pelos bots: `instance/access_review/dados/execucoes/<area>/`.

Copias finais aprovadas para download: `instance/access_review/dados/documentos/<id-da-execucao>/<area>/`. Cada execucao tem seu manifesto de aprovacao e copias independentes; o arquivo Windows da pasta de trabalho pode ser sobrescrito pelo bot sem alterar o historico de downloads.

Evidencias: `instance/access_review/dados/evidencias/<area>/`.

Eventos sanitizados para o sino: `instance/access_review/executions.sqlite3`.

Os PNGs das areas selecionadas so sao removidos depois da conferencia de todos os documentos finais do lote, quando `remover_prints_apos_validacao` estiver ativo. Isso tambem vale para gerar novamente. Uma falha ou interrupcao preserva os prints. O historico do sino usa `retention_days` e `max_events`; documentos permanecem disponiveis para a operacao. A configuracao de notificacoes controla a exibicao no sino, sem impedir o registro dos resultados.

O card `Documentos das revisoes` permite selecionar a execucao e marcar uma ou mais areas para baixar suas copias finais aprovadas. `GET /api/revisao-acessos/documents` lista as execucoes e areas disponiveis; `GET /api/revisao-acessos/documents.zip?execution_id=<uuid>&area=linux&area=admanager` exporta somente as areas selecionadas, organizadas em pastas dentro do ZIP. Sem o filtro `area`, a API mantem a exportacao de todas as areas da execucao para compatibilidade. Ambos exigem operador autenticado. O registro interno confere nome, tamanho e data de modificacao; arquivos antigos sem aprovacao, intermediarios e resultados alterados nao entram no pacote. Durante uma execucao, o download retorna 409; sem documentos aprovados, retorna 404. O ZIP e temporario e nao inclui modelos, PNGs, configuracoes ou logs. Se uma execucao tiver falhas em outras areas, a lista identifica somente os documentos finais aprovados disponiveis, sem incluir os documentos das areas que falharam.

Os eventos de fila/execucao e mensagens amigaveis ficam no estado persistente do job. O logger do Sentinel registra identificador, area e estado. Saida bruta do PowerShell nao e exibida no navegador. Os auxiliares Windows mantem diagnosticos locais na pasta de execucao, com acesso restrito a conta operacional.

## Validacao

```powershell
.\venv\Scripts\python.exe -m unittest tests.unit.access_review_runner_test tests.unit.access_review_notifications_test
```

Os testes usam configuracoes e documentos sinteticos, sem acessar os sistemas auditados.
