# Base de Conhecimento da SofIA

Esta pasta organiza o conhecimento interno que a SofIA podera usar para responder melhor no futuro.

Estes arquivos são documentação estruturada. O motor histórico `engine.py` pode carregar textos por tema. O chat atual usa o fluxo controlado de Ollama e n8n e ainda precisa de integração de recuperação documental com permissões para consultar esta pasta como RAG.

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
