# Guia rapido da Homologacao

Este guia e para uso diario do ambiente de homologacao, sem tocar na producao.

## O que e cada ambiente

- Producao: ambiente que a empresa usa hoje.
- Homologacao: ambiente de testes do time.

## Regra principal

Quem estiver testando deve usar apenas a homologacao.

## Enderecos

- Producao: `http://localhost:5000`
- Homologacao: `http://localhost:5001`

## Scripts prontos

### Ver os dois ambientes

```powershell
powershell -ExecutionPolicy Bypass -File .\status_ambientes.ps1
```

### Ver status da producao sem mexer nela

```powershell
powershell -ExecutionPolicy Bypass -File .\operar_producao.ps1 -Action status
```

### Ver status da homologacao

```powershell
powershell -ExecutionPolicy Bypass -File .\operar_homologacao.ps1 -Action status
```

### Reiniciar homologacao

```powershell
powershell -ExecutionPolicy Bypass -File .\operar_homologacao.ps1 -Action restart
```

### Abrir homologacao no navegador

```powershell
powershell -ExecutionPolicy Bypass -File .\operar_homologacao.ps1 -Action open
```

## Fluxo recomendado para o JR

1. Conferir os ambientes com [status_ambientes.ps1](status_ambientes.ps1).
2. Abrir apenas a homologacao.
3. Validar a alteracao na porta 5001.
4. Nao reiniciar a producao.
5. Se a homologacao travar, reiniciar apenas a homologacao.

## O que nao fazer

- Nao usar a porta 5000 para teste.
- Nao mexer na pasta de producao para validar alteracao nova.
- Nao misturar arquivos da homologacao com a base publica da producao.
- Nao reiniciar a producao para testar alteracao da homologacao.

## Pastas do ambiente

- Aplicacao da homologacao: `C:\Sentinel\hml`
- Base publica da homologacao: `C:\Users\Public\Automacao-HML`

## Objetivo do processo

Primeiro valida na homologacao. Depois a alteracao vai para a producao.