# Estrutura do projeto Sentinel

## Fonte operacional atual

Os seguintes arquivos permanecem na raiz porque sao entradas da aplicacao ou
sao referenciados por caminho em outras rotinas:

- `run_web_service.py`: servico Flask/Waitress.
- `web_config.py`: rotas, cache e regras de negocio.
- `gerenciador_atualizacoes.py`: atualizacoes em background.
- `executar_tudo.py`: checklist e dashboard offline.
- `config.py`: configuracao compartilhada.
- `Unifi.Py`: integracao UniFi carregada pelo nome do arquivo.
- `utilizarSession.py`: captura do GPS com Playwright.
- `verificar_servidores_v2.py`: verificacao de servidores.
- `Replicacao_*.ps1`: rotinas de replicacao do AD.

Mover qualquer um deles exige atualizar chamadas por subprocesso, imports,
arquivos `.spec`, scripts PowerShell e tarefas configuradas no Windows.

## Pastas

- `services/`, `clients/`, `auth/`, `sofia/`: codigo modular ativo.
- `templates/` e `static/`: interface web.
- `templates/mapa_checklist_base.html`: fonte visual versionada do mapa do
  checklist; os arquivos equivalentes em `output/` sao apenas resultados.
- `tests/unit/`: testes automatizados.
- `tests/manual/`: verificacoes executadas sob demanda.
- `tools/manual/`: ferramentas de diagnostico e operacao manual.
- `tools/maintenance/`: manutencao e migracoes do repositorio.
- `docs/`: documentacao tecnica e historica.
- `archive/`: implementacoes antigas preservadas para consulta.
- `scripts/`, `core/` e `web/`: copias ou estruturas legadas ainda em auditoria.
- `snmp_worker/`: servico SNMP separado; sua `.venv` e local e nao versionada.
- `tools/net-snmp/`: dependencia externa vendorizada; revisar separadamente.

## Estruturas legadas auditadas

A raiz continua sendo a fonte oficial para `config.py`, `data_store.py`,
`auth_ad.py`, `user_model.py`, `iniciar_web.py` e
`web_config_hierarquico.py`.

As copias correspondentes em `core/`, `web/` e `scripts/` nao sao identicas e
devem permanecer isoladas ate que chamadas externas e tarefas agendadas sejam
verificadas. A unica copia identica encontrada, `web/user_model.py`, foi
removida. Os scripts `scripts/ambientes/operar_producao.ps1` e
`scripts/ambientes/operar_homologacao.ps1` continuam ativos.

## Arquivos locais e gerados

Credenciais, caches, resultados de diagnostico, HTML gerado e ambientes
virtuais devem permanecer fora do Git. Os principais casos estao cobertos pelo
`.gitignore`, incluindo `environment.json`, caches JSON, `diagnostico.json`,
`resultados_verificacao.json`, `status_servidores.html` e qualquer `.venv/`.

## Regra para novos arquivos

1. Codigo reutilizavel deve entrar no modulo funcional correspondente.
2. Testes automatizados ficam em `tests/unit/`; testes exploratorios em
   `tests/manual/`.
3. Ferramentas avulsas ficam em `tools/manual/` ou `tools/maintenance/`.
4. Documentacao nova fica em `docs/`, mantendo apenas `README.md` e
   `CHANGELOG.md` na raiz.
5. Saidas de execucao, caches e credenciais nunca devem ser adicionados ao Git.

## Proximas etapas seguras

1. Comparar cada copia de `scripts/`, `core/` e `web/` com a versao ativa.
2. Adicionar testes para os pontos que usam caminhos de arquivo.
3. Migrar um grupo por vez, mantendo wrappers temporarios na raiz.
4. Revisar se `tools/net-snmp/` deve virar dependencia instalada ou artefato de
   distribuicao, em vez de permanecer versionado.
