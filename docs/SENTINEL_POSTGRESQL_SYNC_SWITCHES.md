# Sincronizacao paralela de switches

## Estado inicial confirmado pelo operador

Em 16/11/2026, sentinel_api confirmou 166 switches (140 vinculados e 26 sem
correspondencia), alem de 51 regionais, 76 servidores, 49 firewalls e 49 licencas.
Migracao 004 e carga inicial aplicadas. Nao repetir nenhuma delas.

## Publicacao real, sem mudar o cache legado

GerenciadorSwitches._salvar_status_cache continua preservando local_only,
gravando o mesmo dicionario por host com flush/fsync/os.replace. So depois do
replace chama o novo publicador. Falha da gravacao original nao publica.
Falha de importacao/projecao/controle/SQL nao impede nem desfaz o cache original.
Nao altera autenticacao, chamadas Zabbix, frequencias, estados ou telas.

A API bem-sucedida de inventario chama esse salvamento com full_inventory=True.
Chamadas de verificacao individual/metadados mantem o padrao False. So uma
publicacao explicitamente completa marca ausentes; incremental apenas faz upsert
dos itens que contem. Cache vazio/invalido e recusado, nunca usado para zerar
todo o banco. Item sem hostid continua bloqueando a publicacao, salvo local_only
que tem identidade distinta conforme a carga inicial.

O cache antigo nao tem publicacao global confiavel. Nao usar seu mtime, maior
ultima_verificacao ou o horario de uma consulta CLI como publicacao ficticia.
O novo hook captura UTC junto ao replace original e cria arquivo SEPARADO:
output/switches_postgres_publication.json. E uma projecao operacional capturada,
nao um JSON bruto do Zabbix nem substituto de switches_status_cache.json.

Contem apenas campos permitidos do cache, codigos/nomes regionais para o vinculo,
horario da publicacao e indicador completo/incremental. Nao contem credenciais,
refs DPAPI, usuarios, token ou texto livre de problemas; alertas guardam apenas
quantidade. Tem nomes/IPs, portanto manter as permissoes operacionais do output,
nao commitar nem compartilhar o arquivo bruto. output permanece ignorado no Git.

O controle e escrito atomicamente, com lock entre processos de no maximo 0,25s
usando o helper OS-native existente (arquivo .lock exclusivo desse controle,
nao o lock do cofre). Controle antigo nao sobrescreve novo; mesmo horario com
conteudo divergente e erro. O lock nao serializa as gravacoes do cache original:
as corridas de escrita ja existentes nesse cache nao sao corrigidas aqui.
Timestamp ordena as publicacoes capturadas, nao promete ordem absoluta do disco
em processos concorrentes. CLI compara esta projecao com o SQL, nao bytes do
cache vivo que pode ter sido atualizado posteriormente por outro processo.

O controle e produzido em salvamentos normais mesmo com SQL desligado, para
permitir conferir/congelar uma publicacao real antes da primeira escrita. Um
controle corrompido causa erro e exige diagnostico; nao e ignorado como vazio.
Nao gerar publicacao artificial por comando de conferencia.

## Persistencia e permissao

services/operational_switch_postgres.py usa os mesmos tipos/identidades/vinculos
exatos do importador. Regional desconhecida/ambigua continua NULL. Nao inventa
vinculo por substring, nem muda o mapeamento usado nas telas atuais.
Nenhuma rota AD ou consulta da SofIA e alterada. Leituras futuras exigem escopo
autorizado no backend, e NULL nao se torna acesso global.

005_switch_shadow_sync.sql acrescenta atualizado_no_banco_em e marcador
operacional.sincronizacoes_switches. Acrescenta UPDATE ao coletor para upsert,
presenca e lock forte. Sem DELETE/TRUNCATE/MAINTAIN/CREATE; reader segue SELECT.
Guardas de banco/porta/data_directory, owner, transacao e timeouts como antes.
Locks sempre regionais -> switches -> marcador para coordenar outros escritores.

Uma transacao grava todos os registros e publica marcador por ultimo. Ignora
publicacao antiga e nao regrava mesmo digest. Observacao individual antiga/NULL
nao sobrescreve status/manutencao/alertas mais recentes; cadastro e vinculo seguem
a nova publicacao. Marcador confirma publicacao processada, nao igualdade de
todos os valores quando observacoes anteriores foram preservadas.
Data de publicacao, ultima verificacao e atualizado_no_banco_em sao distintas.
Nenhum switch ausente e apagado ou considerado offline por ausencia.

Hashes brutos da carga inicial ficam NULL quando o registro e atualizado por
este pipeline: nao recebem digest de projecao como se fossem hashes de arquivos
originais. A procedencia passa pelo marcador da publicacao capturada.

Worker com uma publicacao pendente + uma em execucao, preferindo data mais nova,
mesmo comportamento de fila dos outros escritores. Sem rede/SQL no thread que
salva o JSON, sem retry infinito. Falha aguarda outra publicacao normal. A fila
pode substituir uma publicacao completa por incremental mais recente; nesse
caso a reconciliacao de ausentes espera outra recarga completa processada.
Nao assumir que todo evento intermediario foi persistido como historico.

## Implantacao controlada no Rigel

1. Commit/push e pull mantendo o flag de switches ausente/desligado. Exemplo
   versionado: scripts/database/operational-postgres-switches-shadow.example.json.
2. Novo pg_dump custom e pg_restore --list. Sem teste de restauracao real ainda.
3. Aplicar SOMENTE 005 como sentinel_admin usando psql -X/ON_ERROR_STOP=1.
   Nao repetir migracoes 001-004 nem importar novamente os 166 switches.
4. Reiniciar Sentinel pelo restart_web_service.ps1 com SQL de switches desligado.
   Conferir healthz. Outros publicadores precisam recarregar seu codigo pelo
   procedimento habitual, sem iniciar outro gerenciador ou agendamento.
5. Executar uma recarga/verificacao normal de switches. O coletor atualizado
   produz a projecao separada. Conferir sem gravacao:

```powershell
& 'C:\Automacao\.venv31410\Scripts\python.exe' `
    C:\Automacao\scripts\database\sync_switch_cache.py
```

6. Se controle ausente, diagnosticar publicador/caminho/identidade Windows/logs;
   nao criar horario manual nem substituir o cache de producao.
7. Congelar COPIA PROTEGIDA da publicacao separada e conferir via --publication.
   Rever contagens, vinculos, data, indicador completo/incremental e digest.
8. Somente depois --apply --expected-digest com a mesma copia. Conferir novamente
   para confirmar marcador/digest e quantidade presente (incremental pode deixar
   presentes adicionais que nao constam da publicacao; isso e intencional).
9. Criar instance/operational-postgres-switches-shadow.json com enabled=true.
   Flags de firewalls e servidores permanecem inalterados. Nao precisa reiniciar
   para reler flag. Aguardar nova publicacao e comprovar marcador mais novo/true
   SEM --apply. Desligar nao cancela transacao em andamento.

Conexao DPAPI existente de sentinel_collector, no mesmo usuario Windows que ja
consegue le-la. Nao ampliar ACL do cofre para corrigir identidade errada.
Lock/SQL timeout gera aviso fixo e SQLSTATE, sem valores. Cache original preservado.

## Testes e limites

Testes locais usam cursores simulados, gravacao atomica em diretorio temporario,
fixture local_only, flags, ordenacao de publicacoes, integridade de contagens,
quarentena, sanitizacao e guards do CLI. Nao abrem o banco de producao.
Nao ha PostgreSQL local para homologar SQL/conflitos reais; validacao do operador
continua obrigatoria antes de habilitar. Esta fase nao cria historico de eventos,
telemetria detalhada nem troca as leituras atuais de nenhuma tela.
