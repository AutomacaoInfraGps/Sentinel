# Persistencia paralela de VPNs

## Estado confirmado pelo operador

Carga inicial 006 aplicada e conferida como sentinel_api: 166 VPNs (153 online,
13 offline), todas vinculadas. Totais: 51 regionais, 76 servidores, 49 firewalls,
49 licencas, 166 switches. Nao repetir a carga inicial nem a migracao 006.

## Mesmo fluxo, segunda persistencia

operational_state.py continua gravando o mesmo estado via escrita atomica.
Somente depois do sucesso da gravacao e da liberacao do lock local chama o hook
de VPNs, tanto em publish_group_records('vpns', ...) como publish_map_snapshot.
Outros grupos publicados individualmente nao disparam esse hook.

Nao altera chamadas aos equipamentos, SSH, fallback FortiManager, frequencias,
vinculos regionais, permissoes AD, rotas, SofIA, tela ou leitura atual dos JSONs.
Nao cria outro coletor nem agendamento. Um erro SQL ou de preparacao da segunda
persistencia nao desfaz a gravacao original nem transforma a coleta em erro.
Conexao SQL fica no worker, fora do thread que publica o cache.

## Fonte, identidade e limites

Apenas o caminho global output/sentinel_operational_state.json pode publicar.
Nenhum arquivo filtrado por usuario e aceito como inventario global. O hook
recebe os registros da publicacao atual, nao relendo estado possivelmente
sobrescrito por outro processo. Leitura SQL futura continua exigindo escopo AD
no backend; o papel SQL de leitura nao representa um usuario do Sentinel.

Reutiliza o parser tipado do bootstrap: todos os registros precisam ser SSH com
serial, VDOM, origem do VDOM, vinculo explicito e coletado_em com fuso.
Fallback FM sem serial ou metadados antigos sao recusados como conjunto, sem
silenciosamente descartar itens e sem mudar o fallback que atende as telas.
Nesse caso o banco mantem a coleta anterior, sem avancar marcador de frescor.

Esta fase aceita somente um hub/VDOM homologado e um instante de coleta por
publicacao, como o coletor atual. Mudanca de serial (inclusive HA), VDOM, ou
mistura de contextos exige homologacao, nao associacao automatica por nome.
O checkpoint e o SQL recusam contexto diferente do previamente homologado.
A fila limitada nao oferece suporte a multiplos hubs nem historico de eventos.

O resumo de tuneis nao e inventario completo verificado. Assim, faz upsert dos
itens observados mas NAO apaga, marca ausentes ou declara offline os que faltam.
O total SQL pode superar o tamanho da ultima resposta. Reconciliacao de tuneis
removidos requer uma fonte completa e validada, fora desta etapa.

## Relogios e checkpoint

Usa o coletado_em real dos registros, em UTC. Nao usa a hora sem data da tela,
mtime, relogio do CLI ou updated_at de uma republicacao do mapa para fingir
coleta nova. Uma republicacao identica gera o mesmo digest. Mesmo instante com
conteudo diferente e conflito; nao aplicar uma das versoes arbitrariamente.

output/vpns_postgres_publication.json e uma projecao SEPARADA, com somente
colunas operacionais permitidas e codigos regionais. Sem comentarios, outros
grupos, credenciais, referencias DPAPI ou nomes regionais de configuracao.
Contem nomes/serial/endpoint do hub e tuneis: manter ACL operacional de output,
nao publicar o arquivo real nem commitar. O output e ignorado no Git.

O checkpoint e produzido depois de publicacoes normais mesmo com SQL desligado,
para homologacao manual. Escrita atomica, flush/fsync/replace e lock exclusivo
entre processos de ate 0,25s nesse checkpoint. Nao altera o lock do cofre DPAPI
nem resolve corridas preexistentes entre gravacoes do estado operacional.
Checkpoint mais antigo nao substitui mais novo; checkpoint corrompido ou troca
de contexto exige diagnostico, nao reinicializacao silenciosa.

## SQL, permissoes e falhas

007_vpn_shadow_sync.sql acrescenta atualizado_no_banco_em e marcador por
(firewall_serial, vdom). Libera NULL nos hashes brutos para nao rotular digest
normalizado como hash de arquivo original. Registros atualizados usam marcador
da projecao para procedencia; importado_em conserva a primeira insercao.

Coletor recebe UPDATE de vpns e SELECT/INSERT/UPDATE do marcador. Reader recebe
apenas SELECT do marcador; sem DELETE/TRUNCATE/CREATE/MAINTAIN ou privilegios AD.
Guarda banco sentinel, porta 5433 e data_directory E:/Sentinel/PostgreSQL/data.
Nao toca Aegis ou servico PostgreSQL existente na porta 5432.

Transacao READ COMMITTED, lock_timeout 1s, statement_timeout 10s, locks sempre
regionais -> vpns -> marcador. Valida codigos regionais existentes, mesmo
contexto da carga inicial, upserts com parametros e contagem dos itens enviados.
Observacao mais antiga que a linha SQL nao sobrescreve dados mais novos.
Marcador e gravado por ultimo, junto ao commit de todas as atualizacoes.
Digest igual nao regrava; coleta antiga e ignorada. Marcador confirma publicacao
processada, nao igualdade byte a byte quando dados SQL mais novos sao retidos.

Worker usa a conexao DPAPI ja existente de sentinel_collector, mesma conta
Windows operacional. Uma publicacao pendente mais uma em execucao, preferindo
coleta mais recente; sem historico, retry infinito ou fila duravel. Falha aguarda
proxima publicacao normal; nao bloqueia o cache. Avisos fixos e SQLSTATE apenas,
sem mensagem bruta do driver. Desligar o flag impede novos trabalhos/pendentes,
mas nao cancela transacao ja em andamento.

## Implantacao incremental no Rigel

1. Commit/push e pull mantendo ausente/desligado
   instance/operational-postgres-vpns-shadow.json. Exemplo versionado false em
   scripts/database/operational-postgres-vpns-shadow.example.json.
2. Novo backup pg_dump custom e pg_restore --list antes de 007. Leitura do
   catalogo nao e um teste real de restauracao.
3. Aplicar SOMENTE 007 como sentinel_admin usando psql -X/ON_ERROR_STOP=1.
4. Reiniciar via restart_web_service.ps1 e confirmar healthz HTTP 200.
   Outros publicadores do mapa precisam carregar o codigo atualizado pelo
   procedimento habitual, sem iniciar outro agendamento.
5. Executar Atualizar VPN e aguardar sucesso. A publicacao separada sera criada.
   Se ausente, diagnosticar codigo/processo/metadados/logs; nao fabricar horario.
6. Conferir SEM gravacao:

```powershell
& 'C:\Automacao\.venv31410\Scripts\python.exe' `
    C:\Automacao\scripts\database\sync_vpn_catalog.py
```

7. Congelar copia PROTEGIDA de output/vpns_postgres_publication.json no E:, fora
   do Git; conferir novamente com --publication no caminho dessa copia.
8. Rever contexto, contagens, coleta e digest normalizado. So depois usar
   --apply --expected-digest com a mesma copia, e conferir novamente sem apply.
9. Criar instance/operational-postgres-vpns-shadow.json com enabled=true.
   Nao altera os flags de firewalls/servidores/switches. Flag e relido por coleta,
   nao exige reinicio para habilitar/desabilitar.
10. Executar uma NOVA coleta pela tela e conferir novamente SEM --apply.
    Exigir nova coleta_sincronizada e conteudo_ja_sincronizado=true antes de
    afirmar que a sincronizacao automatica foi validada.

Os testes locais usam cursores simulados e cache em pastas temporarias. Cobrem
whitelist, horarios, origem incompleta/fallback, contexto, checkpoints atomicos,
ordenacao, upsert sem ausencia, marcador final, hook nativo e guards CLI.
Nao ha PostgreSQL local para homologar a migracao ou conflitos reais; a
validacao do operador permanece obrigatoria antes de habilitar o flag.
