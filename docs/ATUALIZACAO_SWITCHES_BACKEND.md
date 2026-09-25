# Backend de atualização de switches

O backend Aruba Instant On 1830/1930 foi incorporado ao Sentinel em
`services/switch_update_v01`. O pacote mantém a validação de firmware, o
preflight, a atualização via WebUI, a persistência SQLite, a proteção DPAPI,
os logs por job e as rotas Flask.

## Estrutura

- `services/switch_update_v01/main.py`: executor Selenium e validações;
- `services/switch_update_v01/scheduler.py`: fila, SQLite, DPAPI e auditoria;
- `services/switch_update_v01/sentinel_backend.py`: API Flask autenticada;
- `services/switch_update_v01/worker.py`: passagem não interativa da fila;
- `services/switch_update_v01/windows_task.py`: heartbeat e disparo da tarefa;
- `executar_switch_update_worker.bat`: lançador com diretório absoluto;
- `agendar_atualizacao_switches.ps1`: instalação e operação da tarefa Windows.

O runtime fica em `data/switch_updates` e não é versionado. Firmwares de
laboratório, bancos e credenciais do projeto de origem não foram copiados.

## Agendador do Windows

A API grava cada job no SQLite e, para execução imediata, tenta disparar a
tarefa `SentinelSwitchUpdateWorker`. A repetição a cada minuto garante a
execução de jobs futuros e cobre uma falha pontual no disparo sob demanda.
Somente uma instância trabalha por vez; uma trava de arquivo do Windows evita
concorrência entre disparos.

Instalação requer PowerShell elevado:

```powershell
.\agendar_atualizacao_switches.ps1 -Action install
.\agendar_atualizacao_switches.ps1 -Action status
```

A tarefa usa `SYSTEM`, mas a identidade não precisa ser a mesma do processo web.
As novas credenciais são protegidas pelo DPAPI no escopo da máquina, portanto o
backend e o worker podem usar contas Windows diferentes desde que executem no
mesmo servidor. O arquivo do banco continua exigindo ACL restrita: qualquer
conta local que obtenha acesso ao blob protegido pode solicitar sua descriptografia
ao Windows nessa máquina.

## Configuração

As opções não sensíveis ficam na seção `switch_update` do
`environment.json`; veja `environment.example.json`. Produção mantém
`insecure_tls=false`. Quando o Selenium Manager não puder acessar a internet,
instale um ChromeDriver compatível e configure `driver_path`.

`webui_protocol_fallback` define somente o protocolo inicial quando o
inventário não informa um. Redirecionamentos da WebUI para HTTP ou HTTPS são
aceitos apenas no mesmo IP, e o protocolo final retornado passa a ser usado no
job. A transferência possui limite total de 1.200 segundos e limite de 300
segundos sem progresso, além da verificação de conectividade durante o envio.

O servidor precisa de Google Chrome e da dependência `selenium==4.49.0`.

## Segurança operacional

- Use somente firmware obtido de uma fonte oficial e confira o checksum antes
  de enviá-lo ao Sentinel. A extensão, o modelo e a versão não substituem uma
  assinatura criptográfica do fabricante.
- Mantenha `insecure_tls=false` em produção. A exceção deve ser temporária,
  documentada e restrita a um equipamento conhecido.
- Restrinja a escrita no repositório, nos scripts do worker e em
  `data/switch_updates` aos administradores, à conta do backend e a `SYSTEM`.
  Além do risco de elevação de privilégio pela alteração dos scripts, o DPAPI
  no escopo da máquina torna a confidencialidade das credenciais dependente
  dessas permissões de arquivo.
- Os diagnósticos podem conter capturas de tela, HTML e dados da interface do
  switch. Guarde-os somente pelo tempo necessário para análise e não os envie
  ao Git.
- `instance/`, `data/switch_updates/`, `diagnostics/` e arquivos `*.swi` são
  artefatos locais e permanecem fora do versionamento.

## Validação segura

```powershell
.\venv\Scripts\python.exe -c "from services.switch_update_v01.scheduler import SwitchUpdateScheduler; from services.switch_update_v01.sentinel_backend import install_switch_update_backend; print('backend OK')"
.\venv\Scripts\python.exe -m services.switch_update_v01.worker --help
.\venv\Scripts\python.exe -m unittest discover -s tests/unit -p "switch_update*_test.py" -v
```

Não execute transferência física de firmware durante a migração. A etapa de
interface e o teste ponta a ponta serão tratados separadamente.
