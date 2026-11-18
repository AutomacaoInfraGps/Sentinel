# Espelhamento opt-in de contatos SLA (015)

## Contrato

Direcao unica: XLSX configurado -> PostgreSQL. Nenhuma rotina nova salva
planilha, troca o leitor das telas ou altera o projeto SLA. A periodicidade
e 300 segundos, em thread propria do run_web_service.main, fora das rotas
de consulta/edicao. Edicoes do Sentinel e edicoes externas convergem pelo
mesmo leitor. Nao depende de usuario abrir a pagina nem de novo servico ou
tarefa agendada. Quem executa web_config.py diretamente nao inicia esse
worker; producao deve usar o runner ja usado por restart_web_service.ps1.

Sem instance/operational-postgres-contatos-sla-shadow.json com enabled=true,
nao ha leitura periodica do XLSX nem conexao SQL por esse worker. A thread
verifica a flag a cada ciclo. So executa no RIGEL e sob a conta que ja consegue
ler a planilha e o segredo DPAPI do coletor. Reiniciar somente o aplicativo
depois de publicar e ao habilitar/desabilitar na homologacao.

## Captura sem dados pessoais em arquivo publico

sync_sla_contacts.py --capture le a configuracao existente e os dois arquivos
locais, valida com build_contact_catalog da carga inicial e grava somente
um recibo em output/contatos_sla_postgres_publication.json. Nao conecta ao banco.
Recibo contem versao, data da leitura e hashes de configuracao, conteudo,
planilha e catalogo. NAO contem nomes, e-mails, rotulos regionais, caminhos,
aba, linhas de planilha ou payload XLSX. Nao e fila duravel nem backup.

O caminho absoluto configurado e aba exata entram no hash da origem. Uma vez
registrado o primeiro marcador SQL, mudanca nessa identidade exige revisao
manual: nao resetar marcador automaticamente para aceitar outro arquivo.
Aba configurada precisa existir; nao usar outra silenciosamente. Cabecalhos,
formulas, tipos e duplicidades seguem as guardas do bootstrap.

O leitor confere se os arquivos continuaram iguais durante a leitura. Antes
de gravar e antes de terminar a transacao, confere novamente a fonte atual.
Falha ou alteracao aborta SQL e preserva a fonte original. Sao leituras
otimistas: editores externos nao participam do bloqueio; uma alteracao apos
a ultima verificacao pode aparecer so no ciclo seguinte. Nao ha transacao
distribuida entre XLSX e PostgreSQL nem promessa de consistencia instantanea.

Sem --capture ou --apply, o CLI apenas confere banco e recibo. Pode receber
--publication apontando para uma copia congelada DO RECIBO. Para aplica-la,
os arquivos de origem atuais ainda precisam corresponder aos hashes. Se
mudarem, capturar e revisar novamente: recibo nao contem dados suficientes
para restaurar versoes anteriores da planilha. Copias XLSX de backup continuam
protegidas separadamente e nao sao enviadas para chat ou Git.

## Atualizacao SQL

015 adiciona presente_na_fonte as referencias regionais e aos contatos, com
valor inicial true. Novo marcador por fonte registra lido_em (horario da
leitura, nao da ultima edicao por uma pessoa), hash tipado e identidade da
origem. Hora de salvamento/importacao nao e apresentada como coleta remota.

O escritor usa a MESMA chave advisory transacional do bootstrap 014 para
serializar cargas cooperantes e ROW EXCLUSIVE nas tabelas alteradas. Nao
repete o problema do SHARE ROW EXCLUSIVE que exigia privilegios adicionais.
FKs, PKs e UNIQUE continuam protegendo integridade; advisory nao bloqueia
comandos externos que nao seguem o protocolo. Regioes novas precisam existir
no cadastro SQL. A fonte inicial precisa existir e ter a mesma aba.

Uma revisao diferente atualiza rotulos e papeis por origem+regional+papel.
Ausencias confirmadas numa leitura integral valida marcam presente_na_fonte
false, preservando ultimo nome/e-mail. Isso NAO e cadastro mestre de pessoas
nem historico de todas as versoes. Quando o papel reaparece, volta a true.
Consumidores SQL futuros devem filtrar as duas tabelas por presente_na_fonte.
Nenhum leitor web/SofIA atual e trocado aqui.

Uma planilha global vazia, sem contatos preenchidos, invalida ou com vinculo
nao resolvido e recusada integralmente, sem desativar todos os registros.
Remocao em massa de todas as pessoas exige revisao manual; nao interpretar
erro, falta de arquivo ou falha parcial como exclusao. Permutacao de rotulos
entre regionais pode conflitar com UNIQUE existente: revisar, nao tentar
apagar referencias antigas para forcar a carga.

Conteudo tipado identico evita reescrever contatos, mas atualiza comprovante
de leitura e hashes da fonte. Digest tipado nao inclui relogio de captura ou
campos irrelevantes de regionais; inclui caminho/aba via hash, vinculos,
linha de origem e contatos. Recibo exige hashes brutos iguais, mesmo se o
conteudo tipado nao mudou. Captura antiga nao sobrescreve marcador mais novo;
mesmo horario com conteudo conflitante bloqueia. Conferencia verifica linhas
de contato antes de gravar marcador. Commit inclui dados e marcador.

O worker nao guarda credenciais SQL novas, usa o coletor via DPAPI e emite
somente codigo de falha e SQLSTATE nos logs. Falha no espelhamento nao altera
resultado das edicoes XLSX porque elas nao chamam SQL. Recibo salvo antes
de uma falha SQL permite conferir pendencia, mas nao garante fila de mudancas.

## Privilegios e homologacao

015 concede UPDATE somente nas tres tabelas de contatos e SELECT/INSERT/UPDATE
no marcador ao coletor. Nenhum DELETE/CREATE global. Leitura do marcador fica
no papel restrito sentinel_contatos_reader; PUBLIC/sentinel_reader/sentinel_api
nao recebem esses dados. Nao conceder papel de contatos automaticamente a
logins de consulta. Manter as regras de autorizacao futuras separadas do login
tecnico e do escopo de inventario.

Sequencia no Rigel, sem pular etapas:

1. Publicar todos os arquivos novos e run_web_service.py, sem habilitar flag.
2. Fazer backup custom-format e conferir catalogo, antes da 015.
3. Aplicar 015_sla_contacts_shadow_sync.sql como sentinel_admin e confirmar COMMIT.
4. Executar sync_sla_contacts.py --capture; conferir recibo e contagens.
5. Conferir sem argumentos, congelar recibo e revisar --publication.
6. Aplicar recibo com --apply --expected-digest exato; conferir sem --apply.
7. Reiniciar aplicativo com flag true e aguardar ciclo de ate cinco minutos.
8. Executar conferencia sem gravar. Ver lido_em mais novo sincronizado; nao
   exigir digest diferente quando a planilha nao mudou.
9. Homologar uma edicao autorizada pelo usuario na planilha/tela, confirmar
   comportamento do SLA preservado e o novo estado no SQL apos o ciclo.
   Nao usar dados pessoais ficticios ou remover contato real para testar.

Flag false/ausente desliga novas gravacoes no proximo ciclo; reinicio garante
que nao haja ciclo antigo em andamento. Nao reverte SQL ja gravado. Testes
locais usam XLSX sinteticos e mocks, nao validam DPAPI/producao nem substituem
backup e homologacao transacional real do Rigel.
