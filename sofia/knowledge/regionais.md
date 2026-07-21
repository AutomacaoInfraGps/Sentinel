# Regionais

## Objetivo

Regionais representam unidades ou ambientes monitorados pelo Sentinel.

## Dados Usados Hoje

A SofIA usa os dados carregados pelo gerenciador de regionais.

Ela pode consultar:

- total de regionais;
- nome/codigo de uma regional;
- resumo de servidores;
- resumo de links;
- resumo de switches.

## Perguntas Exemplo

```text
Quantas regionais temos?
Resumo da regional ABC
Como esta a regional Macae?
```

## Comportamento Esperado

Quando identificar uma regional, a SofIA deve responder com um resumo consolidado:

```text
Resumo da REG_ABC: servidores: X no total; links de internet: Y no total; switches: Z no total.
```

## Fonte Tecnica

```text
sofia/tools_sentinel.py
identificar_regional()
total_regionais()
nome_regional()
resumo_servidores()
resumo_links()
resumo_switches()
```
