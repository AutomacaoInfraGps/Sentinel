# APs UniFi: auditoria anterior ao cadastro SQL

## Escopo

`scripts/database/audit_ap_sources.py` le somente `data/unifi.json` e
`estrutura_regionais.json`. Nao importa config, Flask, DPAPI ou coletores; nao
conecta a rede ou banco, nem altera arquivos. A saida tem apenas contagens e
categorias fixas, sem MACs, IPs, nomes, IDs ou credenciais.

## Fonte observada no codigo

`UniFi.py` consulta os dispositivos por site, seleciona `type == uap`, aplica
o filtro existente de APs de teste e salva a lista `aps` pelo `data_store`.
O registro contem MAC, IP, nome, modelo, firmware, status, clientes, uptime e
nome do site. A lista `sites` guarda o ID e o nome. O AP nao recebe atualmente
o ID do site nessa projecao. O timestamp global e adicionado ao salvar o JSON;
ele nao comprova uma observacao individual de cada AP ou sucesso em todos os sites.

## Conferencias

- Validade/formato dos MACs e duplicidades na controladora e por site.
- IDs de sites e nomes duplicados; nomes ambiguos nunca resolvidos pelo primeiro.
- Correspondencia do campo site do AP com um site de ID unico; conflitos com site_id.
- Correspondencia regional somente por codigo/nome/descricao exatos, ignorando
  maiusculas e espacos externos. Esta contagem NAO reproduz os aliases do mapa
  nem altera as permissoes ou vinculos existentes.
- O resumo `regional_por_regras_unifi_sem_aproximacao` aplica a normalizacao
  existente do mapa (inclusive prefixos Vnnn) e seus aliases explicitos,
  compartilhados em `unifi_site_matching.py`. O resumo adicional por site
  permite distinguir quantidade de APs e quantidade de sites. Correspondencia
  ambigua ou destino ausente nao gera vinculo. A auditoria nao aplica a busca
  parcial de fallback usada em algumas telas; casos restantes exigem revisao.

### Identidade regional para a migracao

O resolvedor do cadastro considera codigo e nome, nunca descricao geografica:
por exemplo, RHMED e MACAE podem compartilhar a descricao Rio de Janeiro sem
ser a identidade REG_RIO_DE_JANEIRO. Empates reais de codigo/nome continuam
sem vinculo. Aliases explicitos com destino existente tem precedencia.
Se um alias apontar para codigo ausente, somente uma identidade unica exata
normalizada de codigo/nome pode resolver o site, com motivo especifico
`identidade_unica_com_alias_desatualizado`. Isso nao altera os aliases do mapa,
as telas, o catalogo regional ou as permissoes AD. Nunca criar uma regional ou
escolher outra apenas pela cidade, por prefixo parcial ou pelo IP do AP.

### Vinculos confirmados no mapa de producao

Em 2026-11-17, a conferencia somente de leitura do mapa do Rigel identificou
6 APs de `V041_CAXIAS_DO_SUL` em `REG_CAXIAS` e 4 APs de
`V006_SULZER_TRIUNFO` em `REG_SULZER`. Os aliases explicitos
`CAXIAS_DO_SUL` e `SULZER_TRIUNFO` preservam esses relacionamentos ja usados
no Sentinel, sem inferir vinculos pela descricao comum Rio Grande do Sul.
- Cobertura de IP, modelos, firmware, status e coleta explicita por AP.
- Chaves JSON repetidas e estruturas invalidas rejeitadas.

O inventario ja e filtrado pelo coletor; nao representa todos os dispositivos
da controladora. Falha ou ausencia de site nao significa inventario vazio,
AP offline ou exclusao. MAC identifica o equipamento; site representa vinculo
atual e pode mudar. A identidade da controladora tambem precisa ser definida
antes de qualquer importacao. Nao usar nome ou IP como identidade do AP.

## Execucao no Rigel

```powershell
& 'C:\Automacao\.venv31410\Scripts\python.exe' `
    'C:\Automacao\scripts\database\audit_ap_sources.py'
```

Revisar o resumo real antes de preparar migracao SQL. Nesta etapa nao existe
nova tabela de APs, carga inicial ou sincronizacao automatica. Os leitores,
agendamentos e controles de acesso do Sentinel permanecem inalterados.

## Carga inicial preparada (migracao 010)

`scripts/database/import_ap_catalog.py` usa a lista nativa de APs e sites,
nao o mapa derivado. A simulacao e o padrao e nao conecta ao banco, controladora
ou cofre. O comando abaixo exige tzdata no mesmo ambiente Python:

```powershell
& 'C:\Automacao\.venv31410\Scripts\python.exe' `
    'C:\Automacao\scripts\database\import_ap_catalog.py' `
    --source-timezone America/Sao_Paulo
```

### Modelo

- `operacional.controladoras_unifi`: namespace estavel
  `sentinel_unifi_principal`, endpoint como atributo, publicacao global e
  hashes dos dois arquivos de origem. Nao guarda credenciais.
- `operacional.sites_unifi`: chave controladora + ID nativo, nome do site,
  codigo regional opcional e motivo explicito do vinculo. Preserva sites
  sem APs, inclusive os sem correspondencia regional.
- `operacional.aps_unifi`: chave controladora + MAC normalizado, referencia
  composta ao site, nome, IP, modelo, firmware, status, clientes, uptime e
  coleta individual quando realmente informada. Uma mudanca futura de site
  nao deve criar outro AP. Nome e IP nunca sao usados como identidade.

O namespace identifica a instancia configurada no Sentinel, nao o IP, que pode
mudar. Uma segunda controladora exige configuracao e revisao proprias antes
de qualquer importacao; nao juntar inventarios por MAC global.

O timestamp global do JSON e convertido com o fuso explicitamente escolhido,
mas fica apenas em `publicacao_fonte_em`. Nao preenche `coletado_em` dos APs,
nao prova coleta bem-sucedida em todos os sites e nao permite inferir ausencia.
Na origem atual, os 216 APs permanecem com `coletado_em` nulo. Campos brutos
como redes Wi-Fi, VAPs, senhas, tokens e interferencias nao entram na carga.

### Garantias e sequencia de homologacao

1. Revisar a simulacao de producao, sem banco.
2. Fazer backup custom-format do banco e conferir o catalogo com pg_restore.
3. Congelar, em pasta com ACL restrita, os dois arquivos: `data/unifi.json`
   e `estrutura_regionais.json`. Simular novamente com `--source` e
   `--regionals` apontando para as copias; guardar o digest dessa simulacao.
4. Aplicar somente `scripts/database/sql/010_ap_catalog.sql` como
   sentinel_admin, confirmando COMMIT. Ela valida sentinel, porta 5433 e
   diretorio E:/Sentinel/PostgreSQL/data; cria tabelas com sentinel_owner.
5. Rodar `--check-database` nas mesmas copias. Exige as tres tabelas vazias
   e nenhum codigo regional do catalogo ausente no PostgreSQL para a carga.
6. Somente apos revisar, executar `--apply --expected-digest` com o digest
   exato da copia congelada. Os arquivos, o fuso e as linhas normalizadas
   (inclusive os vinculos resolvidos) participam do digest.
7. Conferir contagens de controladoras/sites/APs, status e vinculos pelo
   sentinel_api. A carga e inicial, nao pode ser repetida em tabelas ocupadas.

O escritor valida identidade SQL, bloqueia as tabelas na ordem regionais,
controladoras, sites, APs e usa valores parametrizados, na mesma transacao.
Qualquer divergencia de contagem ou erro cancela toda a carga pelo contexto
transacional. Recusa JSON duplicado, MAC invalido/duplicado na controladora,
site desconhecido/ambiguo e valores invalidos; nao descarta APs silenciosamente.
Regional nao identificada fica nula, sem emprestar a permissao de outra regional.

A migracao concede SELECT ao sentinel_reader e SELECT/INSERT ao coletor,
sem UPDATE, DELETE ou CREATE adicionais. Nao habilita tarefa, flag, sincronizacao
ou nova leitura das telas. A futura consulta pela SofIA precisa filtrar os
sites/APs pelo escopo regional autenticado no backend; sentinel_api e uma conta
tecnica de leitura, nao implementa por si so as permissoes AD de cada pessoa.

Teste local usa mocks de conexao SQL; aplicar e homologar em PostgreSQL real
somente seguindo a sequencia acima. Redes Wi-Fi continuam fora desta carga.
