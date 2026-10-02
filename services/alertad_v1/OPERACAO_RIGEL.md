# Operação no Rigel

Este procedimento deve ser executado pelo usuário/equipe autorizada. Ele não
configura WEF, WinRM, DCs, firewall ou permissões corporativas.

## 1. Preparar diretórios locais

Separe diretórios locais para aplicação, SQLite, logs, configuração e cache. Não
use UNC nem unidade de rede. Conceda acesso apenas à conta de serviço e aos
administradores autorizados. Exemplo a adaptar:

```powershell
icacls C:\CAMINHO_LOCAL_PROTEGIDO /inheritance:r
icacls C:\CAMINHO_LOCAL_PROTEGIDO /grant:r "CONTA_DE_SERVICO:(OI)(CI)M"
```

Não envie ao agente o nome real da conta nem a saída contendo ACLs internas.

## 2. Instalar

```powershell
Set-Location C:\CAMINHO_DO_ALERTAD
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r .\requirements.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m compileall -q src tests alertad.py scripts
```

O ambiente Windows precisa do `pywin32` declarado nas dependências.

## 3. Configurar sem versionar segredos

Crie `settings.json` a partir do exemplo e configure:

- canal `ForwardedEvents`;
- lote de até 500 e sobreposição aprovada;
- intervalo de polling aprovado;
- backend `POWERSHELL_ADWS`, servidor opcional e timeout da consulta;
- canais habilitados;
- retenção apenas como parâmetros documentais; mantenha `purge_enabled=false`.

Crie um arquivo de ambiente protegido usando apenas os nomes de
`config/graph.env.example`. Não use valores de exemplo. O worker carrega esse
arquivo com `--env-file` sem sobrescrever variáveis já definidas no processo.

## 4. Diagnóstico local

```powershell
.\.venv\Scripts\python.exe .\alertad.py init-db C:\CAMINHO_LOCAL_PROTEGIDO\alertad.db
.\.venv\Scripts\python.exe .\alertad.py diagnose C:\CAMINHO_LOCAL_PROTEGIDO\alertad.db `
  --settings C:\CAMINHO_LOCAL_PROTEGIDO\settings.json
```

`diagnose` não abre Event Log, ADWS nem Graph. `status` e `diagnose` mostram a
geração abreviada e a sequência lógica por fonte, mas nunca o bookmark bruto. Use
o roteiro de homologação para as verificações reais.

## 5. Dry-run obrigatório antes de produção

Use outro arquivo SQLite:

```powershell
.\scripts\run_worker.ps1 `
  -Database C:\CAMINHO_LOCAL_PROTEGIDO\homologacao.db `
  -Settings C:\CAMINHO_LOCAL_PROTEGIDO\settings.json `
  -EnvironmentFile C:\CAMINHO_LOCAL_PROTEGIDO\alertad.env `
  -LogFile C:\CAMINHO_LOCAL_PROTEGIDO\logs\homologacao.jsonl `
  -DryRun -InitializeAtEnd -Once
```

Execute `-InitializeAtEnd` uma vez. Em seguida, gere um evento autorizado e rode
novamente somente com `-DryRun -Once`. Confirme mensagem, checkpoint,
deduplicação e ocorrências. Dry-run consulta ADWS apenas quando `MemberName`
está ausente, mas nunca constrói clientes Graph.

Para testar esse caminho sem alterar o AD, copie um XML real para arquivo local
protegido e use `alertad.py simulate-missing-member ... --settings ...`. O comando
abre `Get-Credential`, altera `MemberName` somente em memória e não grava no
SQLite nem no Event Log.

## 6. Renovar o Teams

A renovação é manual e pode exigir interação:

```powershell
.\.venv\Scripts\python.exe .\scripts\renew_teams_cache.py `
  --env-file C:\CAMINHO_LOCAL_PROTEGIDO\alertad.env
```

Proteja o arquivo indicado por `ALERTAD_TEAMS_CACHE_FILE` como uma credencial. O
worker detecta uma renovação externa pelo horário do arquivo e recarrega o cache.

## 7. Inicialização automática

Crie uma Tarefa Agendada com:

- identidade: conta de serviço somente leitura ou gMSA aprovada, sem depender de
  sessão aberta e capaz de executar `Get-ADUser`;
- programa: `powershell.exe`;
- argumentos: `-NoProfile -ExecutionPolicy Bypass -File
  "C:\CAMINHO_DO_ALERTAD\scripts\run_worker.ps1" ...`;
- “Iniciar em”: raiz local do projeto;
- gatilho: inicialização do servidor;
- reinício automático em caso de falha;
- somente uma instância da tarefa;
- sem `-InitializeAtEnd` e sem `-DryRun` em produção.

O próprio AlertAD mantém um segundo bloqueio por banco e recusará outra instância.
Não inclua segredos nos argumentos da tarefa; somente caminhos de arquivos.

## 8. Parada, estado e recuperação

Pare a tarefa de forma controlada. O sinal solicita shutdown, impede novas
operações e espera uma chamada Graph em curso terminar dentro do timeout.

```powershell
.\.venv\Scripts\python.exe .\alertad.py status C:\CAMINHO_LOCAL_PROTEGIDO\alertad.db
.\.venv\Scripts\python.exe .\alertad.py occurrences list C:\CAMINHO_LOCAL_PROTEGIDO\alertad.db
```

Após reinício, use o mesmo banco e não recapture o fim do log. Se o banco falhar
na validação/migração, preserve os arquivos e interrompa a operação; não apague,
recrie ou edite manualmente. Envie somente erro e logs sanitizados para análise.

## 9. Logs e manutenção

Logs são JSONL, giram por tamanho (5 MB, 10 arquivos por padrão) e omitem mensagens
de exceção potencialmente sensíveis. A retenção dos arquivos é responsabilidade
operacional até que o prazo seja aprovado.

Expurgo SQLite está bloqueado na v1. Tanto a configuração quanto uma chamada
direta ao store recusam a operação. Não altere essa proteção no ambiente; uma
futura ativação depende de desenho e prova da janela máxima de replay.
