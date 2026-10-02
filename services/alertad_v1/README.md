# AlertAD

AlertAD monitora alterações de membros de grupos de risco do Active Directory. A
aplicação roda no Rigel, lê exclusivamente o canal local `ForwardedEvents`,
usa `MemberName` quando disponível e resolve ausências por `Get-ADUser`/ADWS,
persiste o resultado em SQLite e envia alertas
independentes por Teams e e-mail via Microsoft Graph.

WEF/WinRM, subscriptions, Domain Controllers, contas e permissões são
infraestrutura externa. O AlertAD não configura nem acessa remotamente os DCs
para coletar eventos; a consulta de diretório usa o ADWS existente.

## Fluxo da v1

```text
ForwardedEvents local
  -> EventSource (bookmark + geração + sequência lógica)
  -> parser e filtro de grupos
  -> MemberName ou Get-ADUser/ADWS somente quando o nome estiver ausente
  -> SQLite (evento + snapshot + entregas + checkpoint)
  -> worker de entregas
  -> Teams e e-mail
```

Eventos aceitos: `4728`, `4729`, `4732`, `4733`, `4756` e `4757`.

Grupos aceitos: Domain Admins, Administrators, Backup Operators, Enterprise
Admins, Schema Admins e nomes iniciados por `GGS_Suporte`, sem distinção entre
maiúsculas e minúsculas.

## Garantias e limites

- leitura local, incremental, ordenada e limitada a 500 eventos por lote;
- checkpoint durável `(generation, logical_sequence, opaque_bookmark)`; o
  `EventRecordID` não é usado como cursor global;
- pequena sobreposição e deduplicação persistente;
- evento/snapshot/entregas/checkpoint confirmados na mesma transação;
- eventos inválidos geram ocorrência sanitizada e não interrompem o lote;
- falha do ADWS usa o SID como fallback e não elimina o alerta;
- Teams e e-mail têm estados e retentativas independentes;
- um envio inicial e até cinco novas tentativas: 30 s, 30 s, 30 s, 5 min e
  15 min, respeitando um `Retry-After` maior;
- um lock de sistema operacional impede dois workers para o mesmo banco; caminhos
  equivalentes convergem e bancos com hard links são recusados;
- coleta e entrega rodam em ciclos separados, de modo que o timeout do Graph não
  bloqueie a próxima leitura do Event Log;
- após aceitação externa e crash antes do commit local, a entrega fica
  `uncertain` e pode ser reenviada. Portanto, a integração é **at-least-once**,
  não exactly-once;
- autenticação Graph/MSAL e chamadas HTTP usam timeout finito;
- SQLite, logs e cache de autenticação devem ficar em disco local protegido;
- expurgo está desabilitado por contrato até existir uma janela de replay
  comprovadamente segura.

## Instalação local

Requer Python 3.11 ou posterior. No Windows:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r .\requirements.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -t . -v
```

Copie `config/settings.example.json` para um arquivo não versionado, defina
`poll_interval_seconds` e habilite `directory` com backend `POWERSHELL_ADWS`.
`directory.server` pode permanecer `null` para descoberta normal do domínio. Mantenha
`retention.purge_enabled` como `false`. Copie apenas os nomes de
`config/graph.env.example` para um arquivo local
protegido e preencha os valores no Rigel. Segredos nunca devem ser colocados no
JSON, no repositório ou na linha de comando.

## Primeiro teste seguro

Use um banco exclusivo de dry-run. Esse modo não constrói notificadores Graph nem
cria entregas reais, e o banco fica marcado permanentemente como `dry_run`.

```powershell
.\.venv\Scripts\python.exe .\alertad.py init-db .\data\homologacao.db --dry-run

.\.venv\Scripts\python.exe .\alertad.py worker .\data\homologacao.db `
  --settings .\config\settings.homologacao.json `
  --log-file .\logs\homologacao.jsonl `
  --dry-run --initialize-at-end --once
```

`--initialize-at-end` cria o corte inicial uma única vez. Não o use em
reinicializações: o worker deve retomar o checkpoint do SQLite. Depois do corte,
gere um evento aprovado e execute sem essa opção. A mensagem será mostrada
localmente, sem chamada ao Graph.

Nunca reutilize esse banco em produção; a aplicação recusa a troca entre os modos
`dry_run` e `production`.

## Execução contínua

```powershell
.\scripts\run_worker.ps1 `
  -Database C:\CAMINHO_LOCAL_PROTEGIDO\alertad.db `
  -Settings C:\CAMINHO_LOCAL_PROTEGIDO\settings.json `
  -EnvironmentFile C:\CAMINHO_LOCAL_PROTEGIDO\alertad.env `
  -SentinelEnvironmentFile C:\CAMINHO_DO_SENTINEL\environment.json `
  -LogFile C:\CAMINHO_LOCAL_PROTEGIDO\logs\alertad.jsonl
```

O `environment.json` fornece tenant, cliente, segredo e remetente apenas em
memória. O `alertad.env` complementar deve conter somente os destinos e a
configuração delegada do Teams, sem duplicar o `client_secret` do Sentinel.

O script é apropriado como ação de uma Tarefa Agendada sob a conta de serviço.
A criação da tarefa, ACLs e identidade ficam a cargo da equipe do ambiente. Use o
diretório do projeto como “Iniciar em” e configure reinício em caso de falha.

## Comandos operacionais

```powershell
# Valida configuração e banco sem acessar rede
.\.venv\Scripts\python.exe .\alertad.py diagnose .\data\alertad.db `
  --settings .\config\settings.json

# Estado resumido, incluindo geração abreviada e sequência lógica, sem bookmark
.\.venv\Scripts\python.exe .\alertad.py status .\data\alertad.db

# Ocorrências abertas
.\.venv\Scripts\python.exe .\alertad.py occurrences list .\data\alertad.db

# Marcar uma ocorrência analisada
.\.venv\Scripts\python.exe .\alertad.py occurrences resolve .\data\alertad.db 123

# Relatório dos pontos de atenção
.\.venv\Scripts\python.exe .\alertad.py report .\data\alertad.db .\data\atencao.csv
```

O destino do relatório não pode ser o SQLite, seus arquivos auxiliares/lock nem
um alias para qualquer um deles.

Acrescente `--dry-run` aos comandos de leitura quando o banco for de homologação.

## Microsoft Graph e diretório

E-mail usa autenticação de aplicação e `Mail.Send`. Teams usa autenticação
delegada e `ChatMessage.Send` para um chat existente; o AlertAD não cria chats nem
altera participantes. A renovação do cache delegado é manual:

```powershell
.\.venv\Scripts\python.exe .\scripts\renew_teams_cache.py `
  --env-file C:\CAMINHO_LOCAL_PROTEGIDO\alertad.env `
  --sentinel-environment C:\CAMINHO_DO_SENTINEL\environment.json
```

O diretório usa `Get-ADUser` local por PowerShell/ADWS, com timeout e cache
temporário limitado. Em operação contínua, a consulta herda a identidade Windows
da conta de serviço ou gMSA que executa o worker; o AlertAD não armazena sua senha.
O módulo ActiveDirectory deve estar instalado no Rigel.

Para homologar um evento sem `MemberName` sem alterar o AD, salve localmente uma
cópia protegida do XML de um evento real e execute:

```powershell
.\.venv\Scripts\python.exe .\alertad.py simulate-missing-member `
  C:\CAMINHO_PROTEGIDO\evento-teste.xml `
  --settings C:\CAMINHO_PROTEGIDO\settings.json
```

O comando troca `MemberName` por ausente apenas em memória e abre o
`Get-Credential` nativo. A credencial temporária permanece no processo PowerShell,
não é devolvida ao Python, persistida ou registrada. O administrador deve revisar
e executar o comando pessoalmente. Esse modo nunca é usado pelo worker normal.

## Documentos

- [ESCOPO_V1.md](ESCOPO_V1.md): fonte de verdade;
- [OPERACAO_RIGEL.md](OPERACAO_RIGEL.md): instalação e operação;
- [HOMOLOGACAO_V1.md](HOMOLOGACAO_V1.md): roteiro de aceite externo;
- [INTEGRACAO_SENTINEL.md](INTEGRACAO_SENTINEL.md): arquitetura e gates da próxima fase.

As fixtures são totalmente sintéticas. Nenhum teste automatizado acessa o
Event Log, AD, Graph, Teams ou e-mail corporativos.
