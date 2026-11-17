# Sincronizacao paralela dos APs UniFi

## Escopo e evidencia

A carga inicial 010 foi conferida no Rigel: 1 controladora, 43 sites,
216 APs (205 online e 11 offline) e 216 vinculados a regionais na copia
congelada. Essas contagens descrevem a carga, nao uma coleta permanente.

Os dois coletores usados pelo Sentinel (`Unifi.Py` e `scripts/Unifi.py`)
continuam consultando os mesmos endpoints, mantendo filtros, regra de status,
HTML e agendamentos existentes. A resposta de stat/device agora precisa ter
sucesso HTTP, estrutura valida e nenhum erro explicito em meta.rc. Somente
apos essa validacao recebe horario UTC de observacao. A coleta das WLANs nao
comprova coleta dos APs e nao fornece seu horario.

Cada site publicado recebe `coleta_aps_confirmada` e `coletado_em`. Cada AP
recebe o ID real do site, o mesmo horario e `coleta_status_confirmada` apenas
quando state e um inteiro nao negativo. O mapeamento online/offline e o do
coletor existente; nao foi substituido por ping ou por ausencia em lista.

O timestamp global adicionado por data_store.save_data permanece como antes
para os leitores atuais. Nao e usado como data de observacao do AP. JSONs
antigos ou sem esses sinais nao geram observacoes novas automaticamente.

## Publicacao e gravacao

Depois do os.replace bem-sucedido de `data/unifi.json`, data_store chama
`services.operational_ap_postgres.publish_ap_catalog`. Outros componentes,
arquivos temporarios ou arquivos de outros diretorios nao publicam APs.
Falha no JSON nao chama o hook; falha no PostgreSQL nao desfaz o cache salvo.

O hook projeta campos tipados, sem senhas, VAPs, tokens, WLANs ou respostas
brutas, e salva atomicamente `output/aps_postgres_publication.json`. Usa lock
de arquivo e preserva a publicacao anterior se detectar observacao antiga,
endpoint diferente ou conflito com o mesmo horario. O arquivo contem nomes,
IDs, MACs e IPs operacionais: nao publicar no Git nem compartilhar a integra.

Mesmo com a flag desligada, uma coleta real produz o checkpoint para
homologacao. Sem APs confirmados ele preserva a publicacao anterior. O arquivo
representa o subconjunto confirmado da coleta mais recente aceita, nao uma
fila duravel, historico ou garantia de cobertura total. Se um site falhou, seus
APs anteriores podem nao estar nessa publicacao; permanecem no banco e a
proxima coleta bem-sucedida podera atualiza-los. Nao afirmar que todos os APs
estao recentes somente porque a publicacao consultada foi processada.

A flag local `instance/operational-postgres-aps-shadow.json` controla a
gravacao automatica. O exemplo versionado fica desligado. O arquivo real nao
deve ser versionado. Cada publicacao relê a flag; nao exige reinicio do
PostgreSQL. Desativar a flag impede novas operacoes, nao cancela uma transacao
ja iniciada.

Os coletores sao subprocessos curtos. Por isso a gravacao habilitada ocorre
sincronamente depois do JSON salvo, com timeouts de conexao/lock/statement,
em vez de uma thread daemon que poderia morrer antes do commit. Pode
acrescentar tempo a conclusao do subprocesso; nao adiciona novas consultas a
controladora. A conexao usa o coletor via DPAPI CurrentUser da identidade de
execucao; nao alterar a conta Windows nem copiar o segredo para JSON.

## Modelo e seguranca SQL

`011_ap_shadow_sync.sql` valida a instancia Sentinel (banco, porta 5433 e
diretorio de dados), preserva sentinel_owner e acrescenta horarios de
atualizacao/observacao e `operacional.sincronizacoes_aps`. A tabela de controle
tem chave controladora + MAC e FK para o AP. Concede UPDATE nas tres tabelas
UniFi existentes ao coletor e SELECT/INSERT/UPDATE no controle. Nao concede
DELETE, TRUNCATE, CREATE ou permissoes novas ao PUBLIC.

O escritor valida destino/endpoint e existencia dos codigos regionais, usa
valores parametrizados e bloqueia na ordem regionais, controladoras, sites,
APs, marcadores. Toda a gravacao pertence a uma transacao. Marcador de AP so
e gravado depois de conferir o AP e seu horario no banco. Datas anteriores
nao substituem observacoes mais novas; mesmo horario com conteudo diferente
e um conflito, nao uma atualizacao silenciosa.

Somente sites/APs observados sao atualizados. Nenhum AP ausente e apagado,
marcado offline ou movido para outra regional por omissao. Mudanca real de
site conserva a identidade controladora + MAC. Sem vinculo regional o site
continua com codigo nulo, nao ganha a permissao de outra regional.

Uma nova controladora ou troca de endpoint exige revisao: nao mistura
inventarios de equipamentos diferentes no mesmo namespace. Hashes brutos da
carga inicial ficam nulos na controladora apos sincronizacao; os marcadores
guardam hashes do conteudo tipado observado, nao do JSON com outros campos.

Leitores da interface continuam os atuais. Nao ha migracao de consultas da
SofIA ou implementacao nova de RLS. As permissoes AD existentes permanecem
na aplicacao; uma futura leitura SQL precisa aplicar o escopo autenticado
por regional via site. A conta tecnica SQL nao equivale ao usuario humano.

## Homologacao no Rigel

1. Commit/push dos arquivos e pull no Rigel. Nao habilitar a flag ainda.
2. Backup custom-format de sentinel e conferencia do catalogo com pg_restore.
3. Aplicar somente 011 com sentinel_admin e ON_ERROR_STOP, confirmar COMMIT.
4. Reiniciar apenas o aplicativo Sentinel, se necessario para carregar o
   data_store novo, e conferir healthz 200. Nao reiniciar PostgreSQL/Aegis.
5. Executar nova coleta UniFi pelo fluxo normal e aguardar a conclusao.
6. Rodar a conferencia abaixo, que e somente leitura via DPAPI:

```powershell
& 'C:\Automacao\.venv31410\Scripts\python.exe' `
    'C:\Automacao\scripts\database\sync_ap_catalog.py'
```

7. Congelar o checkpoint numa pasta de backup com ACL restrita e conferir
   a mesma copia com `--publication`. Revisar cobertura e min/max de datas.
8. Aplicar manualmente SOMENTE essa copia com `--apply --expected-digest`
   usando o digest exato revisado; conferir novamente sem --apply.
9. Criar a flag local com enabled true. Executar outra coleta real, aguardar
   terminar e conferir sem --apply. Datas de observacao precisam avancar e
   os marcadores dessa publicacao precisam estar processados.

Nao repetir a carga inicial 010. A flag de APs e independente das flags de
firewalls, servidores, switches, VPNs e links. Nao habilitar WLANs nesta etapa.

## Validacao

Testes de resposta HTTP/API, estado ausente, horarios reais com fuso,
projecao segura e isolada, checkpoint atomico, conflitos/antiguidade,
hook apos JSON, falha isolada de SQL, upserts/marcadores, consulta somente
leitura, guardas CLI e grants. SQL foi testado com mocks; a migracao e o
fluxo completo ainda precisam da homologacao real no Rigel.
