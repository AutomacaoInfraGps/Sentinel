# Guia de Ambientes Producao e Homologacao

Este guia foi criado para permitir dois ambientes no mesmo servidor sem derrubar a instancia atual da porta 5000 antes da homologacao estar validada.

## O que ja ficou pronto no projeto

- A porta web agora pode ser definida por variavel de ambiente `AUTOMACAO_WEB_PORT`.
- A base publica compartilhada agora pode ser definida por variavel de ambiente `AUTOMACAO_PUBLIC_BASE`.
- Os scripts [restart_web_service.ps1](restart_web_service.ps1), [monitor_web_background.ps1](monitor_web_background.ps1) e [servico_web.ps1](servico_web.ps1) aceitam `-Port` e `-PublicBase`.
- O comportamento padrao continua igual ao atual: porta `5000` e base publica `C:/Users/Public/Automacao`.

## Estrategia recomendada

1. Manter a producao atual como esta.
2. Criar uma copia separada do projeto para homologacao.
3. Subir a homologacao em outra porta e com outra base publica.
4. Validar login, dashboards, links, regionais e jobs da homologacao.
5. So depois planejar a migracao da producao para um endpoint estavel.

## Estrutura recomendada

- Producao: `C:\Sentinel\prod`
- Homologacao: `C:\Sentinel\hml`
- Base publica producao: `C:\Users\Public\Automacao`
- Base publica homologacao: `C:\Users\Public\Automacao-HML`

## Passo 1. Criar a copia de homologacao

Copie a pasta atual para outro diretorio no mesmo servidor.

Exemplo:

```powershell
Copy-Item "C:\Automacao" "C:\Sentinel\hml" -Recurse
```

Se preferir, faca a copia manualmente pelo Explorer para reduzir risco operacional.

## Passo 2. Revisar arquivos sensiveis da homologacao

Na copia de homologacao, confirme estes itens:

- [environment.json](environment.json)
- [auth_state.json](auth_state.json)
- diretorio `.venv`
- certificados, caches ou tokens usados pela aplicacao

Se a homologacao nao puder usar as mesmas credenciais de producao, troque primeiro o [environment.json](environment.json) da copia.

## Passo 3. Subir homologacao sem tocar na producao

Entre na pasta da homologacao e execute:

```powershell
powershell -ExecutionPolicy Bypass -File .\restart_web_service.ps1 -Port 5001 -PublicBase "C:\Users\Public\Automacao-HML"
```

Depois valide:

```powershell
Invoke-WebRequest http://127.0.0.1:5001/api/test -UseBasicParsing
```

URL esperada da homologacao:

```text
http://SERVIDOR:5001
```

## Passo 4. Instalar homologacao como tarefa separada

Se quiser manter a homologacao sempre ativa:

```powershell
powershell -ExecutionPolicy Bypass -File .\servico_web.ps1 -Action install -TaskName "SentinelHmlStartup" -ServiceName "SentinelHml" -DisplayName "Sentinel Homologacao" -Port 5001 -PublicBase "C:\Users\Public\Automacao-HML"
```

Isso evita conflito com a instancia atual da producao.

## Passo 5. Checklist minimo antes de mexer na producao

- Login AD funcionando
- Dashboard principal carregando
- Regionais abrindo normalmente
- Atualizacao de links funcionando
- Jobs em background sem erro
- Logs separados da producao
- Arquivos em `C:\Users\Public\Automacao-HML` sendo gerados corretamente

## Passo 6. Migracao futura da producao

Depois da homologacao aprovada, a producao pode ser movida para um modelo mais estavel:

1. Colocar a instancia de producao em uma pasta dedicada.
2. Subir como tarefa/servico fixo.
3. Publicar via IIS com reverse proxy e HTTPS.
4. Deixar o Waitress escutando apenas internamente.
5. Usar Git para promover alteracoes de homologacao para producao.

## Fluxo Git recomendado

- `main`: producao
- `develop` ou `hml`: homologacao

Fluxo:

1. Desenvolver e testar em `hml`.
2. Validar com o time.
3. Fazer merge para `main`.
4. Publicar na pasta de producao.

## Observacoes importantes

- Nao reutilize a mesma base publica para producao e homologacao.
- Nao use a mesma porta para as duas instancias.
- Nao reinicie a pasta de producao a partir da copia de homologacao.
- Antes de qualquer mudanca em producao, faça backup de [environment.json](environment.json) e das pastas `logs` e `output`.