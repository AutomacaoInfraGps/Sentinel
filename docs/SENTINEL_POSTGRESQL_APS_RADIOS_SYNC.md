# Sincronizacao manual RF UniFi (028)

Implementacao preparada; homologacao no Rigel ainda pendente. Nao ativa worker,
nao muda coletores, leitores das telas, configuracao de startup ou PostgreSQL.
Pre-requisito: 027 e carga inicial conferidas integralmente.

## Sequencia de homologacao

1. Publicar os arquivos e fazer pull no Rigel. Criar novo pg_dump custom e
   conferir codigo de saida, tamanho e pg_restore --list. O backup anterior
   a 027 nao contem os dados RF carregados depois dele.
2. Executar scripts/database/sql/028_unifi_radio_shadow_sync.sql com psql -X,
   ON_ERROR_STOP=1 e sentinel_admin, banco sentinel, loopback porta 5433.
   Exige data_directory E:/Sentinel/PostgreSQL/data. Nao reiniciar servicos.
3. Inicializar o marcador com a MESMA captura congelada da carga inicial.
   Isso confere as linhas atuais contra a evidencia inicial, sem tentar
   reconstruir hashes JSON a partir de tipos numericos do PostgreSQL.

```powershell
& 'C:\Automacao\.venv31410\Scripts\python.exe' `
    'C:\Automacao\scripts\database\sync_ap_radio_catalog.py' `
    --source 'E:\Sentinel\PostgreSQL\backups\carga-radios-unifi-20261119-152903-923\radios-unifi.json'
```

Esperado: conferencia_sem_gravacao; destino_compativel, fonte_inicial_compativel
e conteudo_atual_confere true; conteudo_ja_sincronizado false;
ultima_captura_sincronizada null. Contagens presentes/preservadas: 216
recebimentos, 453 configuracoes e 425 estatisticas. Todos os bloqueios de
antiguidade, conflito e base divergente devem estar false/zero.

Somente apos revisar a conferencia, acrescentar --apply e --expected-digest
dae75c115929e5e9bb6a20035b85f93cdffec2d9f0df742667aca2f828426e79
ao mesmo comando. Repetir sem --apply para confirmar conteudo_ja_sincronizado
true e ultima_captura_sincronizada correspondente a captura inicial. A primeira
sincronizacao so grava o marcador se as linhas RF ja conferem.

4. Depois de homologar a inicializacao, gerar OUTRA captura com
   capture_ap_radio_catalog.py --capture em pasta nova restrita, sem sobrescrever
   a inicial. Conferir com sync_ap_radio_catalog.py --source desse novo arquivo;
   revisar digest/contagens/bloqueios, aplicar explicitamente com seu digest e
   repetir a conferencia. Nao repetir import_ap_radio_catalog.py --apply.

## Garantias e limites

- Fonte inicial imutavel; marcador separado guarda ultima captura sincronizada.
- Captura igual e idempotente. Captura nova com linhas iguais atualiza somente
  o marcador, sem reescrever o conjunto RF.
- Registros ausentes recebem presente_na_captura=false, nao DELETE. O ultimo
  valor fica preservado; isso nao e historico completo nem prova radio inexistente.
- Recebimentos antigos por AP ou mudancas no mesmo recebimento sao recusados.
  Reaparecimento de AP ausente exige recebimento mais recente.
- Publicacao sem fuso e comparada apenas como declarada, sem converter para UTC.
  Troca entre publicacao com/sem fuso exige revisao. Publicacao/captura regressiva
  ou mesmo horario com conteudo diferente tambem bloqueia gravacao.
- Configuracoes e estatisticas continuam separadas; nenhum vinculo pela banda,
  posicao ou nome de AP. Metricas ausentes continuam NULL, zero informado e zero.
  Recebimento nao vira data de medicao, que permanece desconhecida.
- Destino/controladora/site/MAC existentes devem conferir; nenhum vinculo e
  corrigido automaticamente. Pais sao protegidos por locks SHARE curtos.
- Mesmo advisory lock da carga inicial; uma transacao, timeouts, parametros SQL
  e leitura integral de retorno. Sucesso somente apos commit do contexto.
- Permissoes adicionais UPDATE limitadas as tres tabelas RF e ao marcador;
  sem DELETE, sem permissao nova de escrita no inventario ou na fonte inicial.
- Testes locais sinteticos, incluindo falha de commit e mensagens sanitizadas.
  DDL ainda nao executado em PostgreSQL local; validacao real sera no Rigel.

Nao habilitar sincronizacao automatica nesta etapa.
