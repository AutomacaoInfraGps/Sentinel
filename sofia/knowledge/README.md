# Base de Conhecimento da SofIA

Esta pasta organiza o conhecimento interno que a SofIA podera usar para responder melhor no futuro.

No momento, estes arquivos sao documentacao estruturada. Eles ainda nao sao carregados automaticamente pelo `engine.py`.

## Objetivo

Separar conhecimento em arquivos pequenos por tema, evitando deixar tudo misturado no codigo.

```text
knowledge/
|-- README.md
|-- dashboard.md
|-- regionais.md
|-- servidores.md
|-- links_internet.md
|-- switches.md
|-- vpns.md
|-- seguranca.md
```

## Uso Futuro

Esta base podera alimentar:

- respostas explicativas;
- perguntas frequentes;
- RAG;
- procedimentos internos;
- fluxos de atendimento;
- scripts aprovados;
- validacoes antes de acoes reais.

## Regra

Conhecimento pode orientar a SofIA, mas nao autoriza acao.

Permissao e decisao de execucao devem continuar no backend, em regras explicitas.
