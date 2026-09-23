# Servidores e VMs

## Objetivo

Permitir que a SofIA responda perguntas sobre a saúde dos servidores e VMs cadastrados no Sentinel.

## Status Considerados

- online;
- offline;
- warning;
- inativo;
- desconhecido.

## Perguntas Exemplo

```text
Como estão os servidores?
Servidores da regional ABC
Tem VM offline?
```

## Comportamento Atual

A SofIA resume contagens por status, podendo usar uma regional específica quando ela for identificada na pergunta.

## Fonte Técnica

```text
sofia/tools_sentinel.py
resumo_servidores()
identificar_regional()
nome_regional()
```

## Limites Atuais

A SofIA ainda não executa verificação em tempo real, reinicialização de serviço, acesso remoto ou comando em servidor.
