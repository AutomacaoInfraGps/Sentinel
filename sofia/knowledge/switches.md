# Switches

## Objetivo

Permitir que a SofIA responda perguntas sobre switches e alertas do Zabbix já carregados pelo Sentinel.

## Status Considerados

- online;
- offline;
- warning;
- inativo;
- desconhecido.

## Perguntas Exemplo

```text
Como estão os switches?
Switches da regional ABC
Tem alerta no Zabbix?
Tem problema de switch?
```

## Comportamento Atual

A SofIA resume switches por status e pode listar alertas ativos de switches em cache.

## Fonte Técnica

```text
sofia/tools_sentinel.py
resumo_switches()
alertas_switches_ativos()
identificar_regional()
nome_regional()
```

## Limites Atuais

A SofIA não consulta o Zabbix em tempo real neste fluxo e não executa ações em switches.
