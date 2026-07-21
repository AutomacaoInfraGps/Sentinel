# Switches

## Objetivo

Permitir que a SofIA responda perguntas sobre switches e alertas do Zabbix ja carregados pelo Sentinel.

## Status Considerados

- online;
- offline;
- warning;
- inativo;
- desconhecido.

## Perguntas Exemplo

```text
Como estao os switches?
Switches da regional ABC
Tem alerta no Zabbix?
Tem problema de switch?
```

## Comportamento Atual

A SofIA resume switches por status e pode listar alertas ativos de switches em cache.

## Fonte Tecnica

```text
sofia/tools_sentinel.py
resumo_switches()
alertas_switches_ativos()
identificar_regional()
nome_regional()
```

## Limites Atuais

A SofIA nao consulta o Zabbix em tempo real neste fluxo e nao executa acoes em switches.
