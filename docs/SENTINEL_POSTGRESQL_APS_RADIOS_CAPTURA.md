# Simulacao e captura nativa de RF UniFi

## Resultado real de partida

Conferencia enviada pelo operador no Rigel em 19/11/2026, SHA256 do JSON:
a7b7e5c4a131aac9cd0d4ce5686c13d9732c01cf4511c76c5c02e89f1149be84.
216 APs com projecao nativa e identidades concordantes; recebimento com fuso
em todos, sem data explicita de medicao. 453 configuracoes e 425 estatisticas,
com interface unica na respectiva tabela, sem registros descartados.
cu_total/cu_self_tx/cu_self_rx informados nas 425 estatisticas; tx_retry
informado em 409 e ausente em 16, sem preenchimento com zero.
Configuracoes e estatisticas continuam independentes; diferenca de contagens
nao comprova radios ausentes/falha. Valores podem variar em cada coleta.

## Entrega sem PostgreSQL

scripts/database/capture_ap_radio_catalog.py le data/unifi.json sem importar
coletores, config ou web_config. No padrao nao importa cofre/drivers SQL nem
faz consultas de rede: simulacao, nenhuma gravacao. Nao tem --apply.
--check-database e opcional, exige --source congelado e somente confere o destino.
Nao cria migracao/roles/escritor automatico e nao troca fonte da tela.

```powershell
& 'C:\Automacao\.venv31410\Scripts\python.exe' `
    'C:\Automacao\scripts\database\capture_ap_radio_catalog.py'
```

Revisar o resumo real antes de preparar a etapa SQL. Esperado a partir da
conferencia anterior: 216 APs, 453 configuracoes e 425 estatisticas, mas nao
fixar esses numeros como requisito universal de inventario.
vinculos_sql_conferidos permanece false: nenhuma existencia/site/endpoint
de destino foi consultada na simulacao. Identidade unica no JSON nao equivale a FK validada.

## Captura informada pelo operador

Backup informado no Rigel:
E:\Sentinel\PostgreSQL\backups\sentinel-antes-radios-unifi-20261119-152814-905.dump,
205895 bytes, em 19/11/2026 15:28:21. Captura criada em pasta restrita:
E:\Sentinel\PostgreSQL\backups\carga-radios-unifi-20261119-152903-923\radios-unifi.json.
Capturado_em 2026-11-19T18:29:04.620727+00:00;
digest dae75c115929e5e9bb6a20035b85f93cdffec2d9f0df742667aca2f828426e79;
sha256_projecao 9551dbbc3893e9d26073375ae6a57eb69ae3a199c1018a5a3ae860eaee43d4d1.
216 APs em 39 sites, 453 configuracoes, 425 estatisticas, 16 tx_retry ausentes.
Vinculos SQL ainda nao conferidos; estes dados sao resultados enviados, nao
acesso remoto desta revisao ao banco ou ao arquivo do Rigel.

Atualizacao posterior informada pelo operador: conferencia de destino concluida,
controladora/endpoint concordantes e zero sites/APs ausentes ou em site divergente;
destino_compativel=true. Tabelas RF nao foram conferidas por esse comando.
Migracao/carga inicial preparadas em
[SENTINEL_POSTGRESQL_APS_RADIOS_CARGA.md](SENTINEL_POSTGRESQL_APS_RADIOS_CARGA.md),
ainda sem confirmacao de aplicacao da 027 ou gravacao no Rigel.

## Conferencia somente leitura do destino

Depois de publicar e fazer pull, no Rigel sob a conta operacional:

```powershell
& 'C:\Automacao\.venv31410\Scripts\python.exe' `
    'C:\Automacao\scripts\database\capture_ap_radio_catalog.py' `
    --source 'E:\Sentinel\PostgreSQL\backups\carga-radios-unifi-20261119-152903-923\radios-unifi.json' `
    --check-database
```

Revalida captura/hash e verifica que o arquivo nao mudou durante a leitura.
Conecta com sentinel_collector/127.0.0.1:5433/sentinel via credencial SQL ja
configurada no cofre da conta operacional. Nao acessa credenciais da controladora.
Usa default_transaction_read_only e REPEATABLE READ, READ ONLY, timeout de 5s,
validacao de banco/usuario/porta e SELECTs parametrizados nas tabelas existentes:
controladoras_unifi, sites_unifi e aps_unifi.

Retorna apenas se a controladora existe/endpoint confere, quantos sites/MACs
da captura estao ausentes e quantos APs estao em site divergente. Nao confere
por nome nem altera vinculos. Sites extras no banco (inclusive sem APs) nao
invalidam a captura. Uma coleta SQL mais recente nao comprova medicao RF.
Esperado destino_compativel=true e zero ausencias/divergencias.
vinculos_sql_conferidos=true significa consulta concluida; a compatibilidade
e informada separadamente em banco.destino_compativel. Conferencia divergente
produz diagnostico, nunca ajusta o destino para fazer a carga passar.
tabelas_rf_conferidas permanece false: nenhuma tabela RF foi criada ou lida.
Nao emitir carga ate revisar esse resultado e preparar esquema/permissoes.

## Conteudo e validacoes

- Controladora no namespace existente sentinel_unifi_principal, endpoint/porta
  para futura comparacao com o cadastro SQL. Nao usa nomes de AP/site como chave.
- Somente projecao RF versionada, por MAC e site_id, com interface unica e
  explicita dentro de cada tabela. Nao associa tabelas por banda, ordem ou nome
  aproximado, e nao cria uma identidade universal de radio fisico.
- Mantem estados de campo ausente/nulo/invalido/informado e zeros numericos
  informados. Campos invalidos so permanecem quando NULL e assim identificados;
  valor e situacao contraditorios bloqueiam a captura.
- Bloqueia origem/versao divergentes, AP duplicado na controladora, MAC/site
  divergentes do inventario, sites repetidos/nao confirmados, interface ausente
  ou duplicada e tabelas/linhas de estrutura invalida.
- Recebido_em deve conferir com coletado_em do AP e da resposta do site e nao
  pode ser posterior a captura. Nao usa timestamp global ou mtime como medicao.
  Publicacao textual sem fuso e preservada sem conversao; medido_em segue NULL.
- AP offline pode ter estatisticas antigas. Resposta recebida nao garante
  medicao atual, confianca do dado, ausencia de interferencia ou RF saudavel.

O hash de origem corresponde aos mesmos bytes lidos. A fonte e relida antes
de concluir para detectar alteracao. JSON com chaves repetidas, NaN/infinito
ou tamanho acima de 32 MiB e recusado. Mensagens sao fixas, sem valores brutos.
O resumo contem apenas contagens, categorias, horarios e hashes, sem MACs,
nomes, IPs, endpoints ou credenciais.

## Captura congelada posterior

--capture CAMINHO cria exclusivamente um novo arquivo; nao sobrescreve.
Preparar pasta restrita no Rigel antes de usar essa opcao, conforme o processo
de cargas anteriores. A captura contem MACs, site_ids, interfaces e endpoint
interno, embora nao contenha credenciais, clientes, nomes de pessoas/APs/sites,
payload bruto ou dados do agregado legado. Nao versionar nem colar seu conteudo.
--source CAMINHO valida e simula essa captura congelada; nao aceita o JSON
bruto como se fosse uma captura e nao pode ser combinado com --capture.

sha256_projecao cobre controladora e registros RF canonicos. digest_carga
cobre tambem versao/fonte, captura, publicacao textual e hash da origem.
Revalidacao rejeita campos extras, ordem nao canonica ou hash divergente.
Hashes detectam alteracoes do artefato, nao sao assinatura/autorizacao.

Depois do resultado real da simulacao: planejar backup, pasta/captura restrita,
esquema e privilegios RF, conferencia readonly do destino, e so entao carga
inicial com digest revisado. Nao aplicar a captura nas tabelas de APs existentes
nem alterar seus vinculos para fazer uma conferencia passar.
