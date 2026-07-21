# Servidores e VMs

## Objetivo

Permitir que a SofIA responda perguntas sobre a saude dos servidores e VMs cadastrados no Sentinel.

## Status Considerados

- online;
- offline;
- warning;
- inativo;
- desconhecido.

## Perguntas Exemplo

```text
Como estao os servidores?
Servidores da regional ABC
Tem VM offline?
```

## Comportamento Atual

A SofIA resume contagens por status, podendo usar uma regional especifica quando ela for identificada na pergunta.

## Fonte Tecnica

```text
sofia/tools_sentinel.py
resumo_servidores()
identificar_regional()
nome_regional()
```

## Limites Atuais

A SofIA ainda nao executa verificacao em tempo real, restart de servico, acesso remoto ou comando em servidor.
