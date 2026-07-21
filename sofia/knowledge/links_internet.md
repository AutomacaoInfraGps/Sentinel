# Links de Internet

## Objetivo

Permitir que a SofIA responda perguntas sobre links de internet cadastrados nas regionais.

## Status Considerados

- online;
- offline;
- inativo;
- desconhecido.

## Perguntas Exemplo

```text
Como estao os links?
Links de internet da regional ABC
Tem link offline?
```

## Comportamento Atual

A SofIA resume a quantidade de links por status, considerando todos os links ou apenas uma regional identificada.

## Fonte Tecnica

```text
sofia/tools_sentinel.py
resumo_links()
identificar_regional()
nome_regional()
```

## Limites Atuais

A SofIA nao altera SD-WAN, nao reinicia link e nao executa comandos no firewall.
