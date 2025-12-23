# Como o Sistema Determina o Status dos Switches

Este documento explica como o sistema determina se um switch está online, offline ou em estado de alerta (warning).

## Processo de Verificação

Quando o sistema verifica o status de um switch, ele segue os seguintes passos:

1. **Busca o switch no Zabbix**:
   - Primeiro tenta encontrar pelo nome exato
   - Se não encontrar, tenta pelo IP
   - Se ainda não encontrar, tenta buscar por interfaces com o IP especificado

2. **Verifica o status do host no Zabbix**:
   - Se o host estiver inativo no Zabbix, o switch é considerado **offline**
   - Se o host estiver ativo, continua a verificação

3. **Busca problemas ativos**:
   - Consulta a API do Zabbix para verificar se existem problemas ativos para o switch
   - Se existirem problemas, o switch é considerado em estado de **warning**
   - Se não existirem problemas, o switch é considerado **online**

4. **Coleta informações adicionais**:
   - Busca itens de monitoramento como CPU, memória, uptime e tráfego de interfaces
   - Estas informações são exibidas na interface, mas não afetam o status

## Códigos de Status

O sistema utiliza três estados principais para os switches:

| Status | Descrição | Condição |
|--------|-----------|----------|
| **online** | Switch está funcionando normalmente | Host ativo no Zabbix e sem problemas |
| **offline** | Switch está desligado ou inacessível | Host inativo no Zabbix |
| **warning** | Switch está com algum problema | Host ativo no Zabbix, mas com problemas reportados |

## Trecho de Código Relevante

```python
# Determina status
status = "online"
if host_status == "inativo":
    status = "offline"
elif problemas:
    status = "warning"
```

## Fluxograma do Processo

```
┌─────────────────┐
│ Início          │
└────────┬────────┘
         ▼
┌─────────────────┐
│ Busca no Zabbix │
└────────┬────────┘
         ▼
┌─────────────────┐     Não     ┌─────────────────┐
│ Encontrou?      ├────────────►│ Status:         │
└────────┬────────┘             │ não encontrado  │
         │ Sim                  └─────────────────┘
         ▼
┌─────────────────┐     Não     ┌─────────────────┐
│ Host ativo?     ├────────────►│ Status:         │
└────────┬────────┘             │ offline         │
         │ Sim                  └─────────────────┘
         ▼
┌─────────────────┐     Sim     ┌─────────────────┐
│ Tem problemas?  ├────────────►│ Status:         │
└────────┬────────┘             │ warning         │
         │ Não                  └─────────────────┘
         ▼
┌─────────────────┐
│ Status:         │
│ online          │
└─────────────────┘
```

## Exemplos

1. **Switch Online**:
   - Host ativo no Zabbix
   - Sem problemas reportados
   - Indicado com um círculo verde na interface

2. **Switch Offline**:
   - Host inativo no Zabbix
   - Indicado com um círculo vermelho na interface

3. **Switch em Warning**:
   - Host ativo no Zabbix
   - Com problemas como:
     - Interface desconectada
     - Alto uso de CPU
     - Problemas de memória
   - Indicado com um círculo amarelo na interface

## Observações

- O status é atualizado sempre que o switch é verificado
- A verificação pode ser manual (clicando no botão "Verificar") ou automática (ao carregar a página)
- A data e hora da última verificação são exibidas no card do switch