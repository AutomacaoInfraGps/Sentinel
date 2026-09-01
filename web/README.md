# Web legado

Esta pasta contem uma estrutura web anterior. O servico atual e iniciado por
`run_web_service.py` e utiliza `web_config.py`, ambos na raiz do projeto.

Os arquivos desta pasta nao devem substituir as entradas da raiz sem uma
migracao controlada e testes de inicializacao, rotas e tarefas em background.

`user_model.py` nao permanece nesta pasta porque era identico ao arquivo ativo
da raiz. Consulte `docs/ESTRUTURA_PROJETO.md` para a classificacao das demais
copias.
