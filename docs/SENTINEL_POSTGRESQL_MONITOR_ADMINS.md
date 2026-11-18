# Monitor de Admins: carga inicial (016)

## Limites

Espelho inicial do cache e da baseline existentes, em transacao unica.
Nao muda as consultas Forti, os botoes de aprovacao, o JSON da baseline,
as notificacoes ou o SLA. A tela continua lendo o fluxo atual.
Nao habilita sincronizacao automatica nem troca o leitor da tela para SQL.
A sincronizacao continua e o historico de aprovacoes precisam de uma etapa
posterior, depois de homologar esta carga. Nao usar o bootstrap como sincronizador.

## Identidade e evidencias

- fontes_monitor_admins: origem logica, quatro hashes, fuso explicito da fonte,
  horario declarado de publicacao, digest e horario real de importacao.
- dispositivos_monitor_admins: uniao das chaves do cache e da baseline,
  presenca independente em cada origem, indicadores trivalentes e ultima
  coleta valida quando explicitamente informada. Ausencia de evidencia e NULL.
- contas_admins_observadas: contas retornadas ou preservadas no cache. Evidencia
  distingue consulta_valida_declarada de cache_sem_confirmacao_atual.
- baseline_admins_aprovada: somente contas presentes no JSON da baseline.
  Estar no equipamento nunca aprova automaticamente uma conta.
- divergencias_monitor_admins: novos, removidos e remocoes pendentes declarados
  pelo Sentinel. Nao recalcula diferencas ou transforma uma falha em remocao.

Chaves incluem origem, chave original do equipamento e usuario exato, com
maiusculas preservadas. Nao funde contas homonimas de equipamentos diferentes,
nao assume identidade pessoal e nao inventa serial/VDOM ausentes.
Listas invalidas/duplicadas, indicadores nao booleanos, consulta contraditoria,
datas invalidas/ambiguas e identidades centrais incoerentes bloqueiam toda a carga.
Datas legadas completas sem fuso exigem --source-timezone; hora solta nao e aceita.
O horario de publicacao nao substitui ultima_coleta_valida ausente.

Vinculo regional por nome exato do firewall (casefold), somente se unico no
catalogo. Ambiguidades e nao encontrados ficam sem FK regional, preservados
com motivo; nao usa busca aproximada. FMG e FAZ centrais ficam sem regional.
Chaves exclusivas da baseline sao mantidas mesmo sem consulta no cache.
Na auditoria do Rigel: FGT_CTRLCABEDELO sem correspondencia e FGT_CONTROL_MCO /
FGT_LC fora do cache precisam continuar preservados, nao eliminados ou renomeados.
Os totais devem vir da simulacao do servidor, nao do cache local de homologacao.

## Privilegios

016 cria sentinel_admins_reader NOLOGIN, sem concede-lo automaticamente a
nenhum login. Tabelas pertencem a sentinel_owner. PUBLIC, sentinel_reader e
sentinel_api nao recebem leitura de contas. Coletor tem somente SELECT/INSERT.
Nao concede UPDATE, DELETE ou aprovacao de contas. Dados adicionais dos JSONs
(credenciais, mensagens cruas de erros, configuracao, etc.) nao sao armazenados.
Resumo imprime apenas contagens, categorias e hashes, nunca usuarios.

Antes de permitir DBeaver/SofIA/API para essas tabelas, revisar quem pode ler
contas administrativas. Papel SQL tecnico nao implementa o escopo regional AD.
Superusuarios/dono e outros papeis administrativos continuam com seus privilegios.

## Sequencia no Rigel

1. Publicar os arquivos novos; executar somente a simulacao:

```powershell
& 'C:\Automacao\.venv31410\Scripts\python.exe' `
    'C:\Automacao\scripts\database\import_admin_catalog.py' `
    --source-timezone America/Sao_Paulo
```

2. Revisar totais, vinculos pendentes e contas anteriores. Fazer backup custom
   de sentinel e validar com pg_restore --list antes de mudar o esquema.
3. Congelar dashboard_admins_cache.json, baseline configurada, cache de firewalls
   e estrutura_regionais.json em pasta de backup com ACL restrita; pausar edicoes
   de baseline durante a copia. A baseline pode ter caminho personalizado em
   fortianalyzer.admin_baseline_file; nao assumir o arquivo padrao sem conferir.
4. Simular as mesmas copias com --cache, --baseline, --firewalls e --regionals.
   Digest inclui os quatro arquivos e a projecao tipada. Nao enviar/copiar contas
   para o chat, repositorio ou logs.
5. Aplicar 016_admin_monitor_catalog.sql como sentinel_admin usando psql -X,
   ON_ERROR_STOP=1, banco sentinel, 127.0.0.1:5433. A migracao valida tambem
   E:/Sentinel/PostgreSQL/data. Nao reaplicar em tabelas/papel existentes.
6. Rodar --check-database com as quatro copias explicitas; todas as tabelas
   novas devem estar vazias e todas as regionais presentes.
7. Somente depois da revisao, usar --apply --expected-digest da copia aprovada.
   SQL usa sentinel_collector via DPAPI, somente no RIGEL. Advisory lock serializa
   importadores cooperantes; locks de tabela sao compativeis com os grants.
   PKs/FKs protegem contra duplicacao. Sucesso e impresso apos commit.
8. Conferir contagens como admin ou leitor autorizado:

```sql
SELECT (SELECT count(*) FROM operacional.dispositivos_monitor_admins) AS dispositivos,
       (SELECT count(*) FROM operacional.contas_admins_observadas) AS observadas,
       (SELECT count(*) FROM operacional.baseline_admins_aprovada) AS aprovadas;
SELECT vinculo_regional, count(*) FROM operacional.dispositivos_monitor_admins
GROUP BY vinculo_regional ORDER BY vinculo_regional;
SELECT evidencia, count(*) FROM operacional.contas_admins_observadas
GROUP BY evidencia ORDER BY evidencia;
```

Nao repetir carga inicial em tabelas ocupadas. Contagens diferentes entre
baseline e observadas nao provam exclusao de contas: sao fontes diferentes.
Esta etapa nao reconstitui quem aprovou uma conta ou quando ocorreu a aprovacao.
Os testes locais usam mocks SQL; nao substituem a homologacao em PostgreSQL real.

## Tema das telas

Correcoes no theme.css limitadas ao tema escuro: cabecalhos/filtros do monitor,
editor e campos pendentes do cadastro de e-mails, selecao da tabela, paineis de
metricas e horario de verificacao dos firewalls. Cores de estado continuam
distintas. Nenhuma chamada adicional ao banco foi adicionada nessas telas.
Previa sintetica: python -m tests.manual.administrative_theme_browser_test.
