# Auditoria da projecao de radios UniFi

## Situacao

Inventario informado pelo operador no Rigel em 19/11/2026: 216 APs, 43 sites,
203 online e 13 offline, todos com MAC/site identificados e coleta com fuso.
Sem duplicidade de identidade. Isso nao confere o PostgreSQL nem a telemetria RF.

UniFi.py salva o inventario em aps e um agregado separado em
interferencia_5ghz_por_site. Este ultimo alimenta a analise da tela de antenas,
mas nao entra em NATIVE_FIELDS do escritor operacional_ap_postgres.py.
O agregado guarda nome do AP e rotulo do site, sem MAC/site_id/ID de radio
ou data individual por linha. Canal automatico/ausente e radio nao encontrado
sao excluidos; ausencia da linha nao significa AP sem radio ou offline.

cu_total, cu_self_tx, cu_self_rx e tx_retry podem receber zero quando a resposta
nao contem estatistica. Por isso o JSON existente nao permite distinguir zero
medido de valor padrao. A data de coleta do inventario nao comprova essa medicao.
Nao promover esses valores a telemetria confirmada nem ligar por nome sozinho.

## Resultado informado no Rigel em 19/11/2026

Arquivo auditado: SHA256
cacb9598ae895704b24c60b79a3dad01ede3badaa5b6abf0c76096f59dfb37a6.
Publicacao declarada sem fuso, sem conversao automatica.

- 31 sites na projecao RF, 102 grupos de canais e 125 linhas de radio.
- 125 candidatos unicos por site/nome, sem aprovacao de vinculos.
- Nenhuma linha com MAC, site_id, ID textual de radio ou coleta explicita.
- 91 identidades do inventario sem linha RF; nao representam 91 radios ausentes.
- Percentuais no intervalo esperado nas 125 linhas, sem soma TX/RX maior que total.
- Zeros sem comprovacao: cu_total 20, cu_self_tx 26, cu_self_rx 76, tx_retry 30.
  Contagens por campo, nao quantidade de radios distintos sem medicao.
- Riscos declarados: OK 93, ATENCAO 26, CRITICO 6. Nao reavaliados como medicao.

Nao houve acesso PostgreSQL nem carga. O resultado nao aprova nomes como chave
de equipamento e nao permite distinguir zeros medidos de defaults. Recomenda-se
uma projecao nativa separada, preservando o agregado atual para compatibilidade
da tela, antes de criar o espelho RF. Identidade e valores devem vir da resposta
da controladora, sem preencher ausencias com zero. Horario de recebimento da
resposta deve ser distinguido de data de medicao, quando esta for fornecida.
O ajuste descrito abaixo foi implementado depois da auditoria, mas ainda depende
de publicacao e de nova coleta/conferencia no Rigel.

## Projecao nativa adicional, sem carga SQL

services/unifi_radio_collection.py adiciona radios_nativos a cada AP nas duas
versoes do coletor (Unifi.Py e scripts/Unifi.py). Usa exclusivamente a resposta
stat/device ja consultada, sem nova requisicao. O agregado legado e todos os
campos existentes permanecem inalterados. Nenhum leitor da tela foi trocado.

A projecao versionada contem MAC normalizado, site_id, recebido_em com fuso,
estado online declarado e duas tabelas independentes: configuracoes (radio_table)
e estatisticas (radio_table_stats). Whitelist de nome de interface, banda
declarada e canal; estatisticas incluem cu_total, cu_self_tx, cu_self_rx e
tx_retry a partir de tx_retries_pct, sem arredondamento adicional.
Canal auto e zero explicito sao preservados, sem inferir canal operacional.
Nao ha inferencia de banda a partir do numero do canal.

Campos ausentes, nulos ou invalidos ficam NULL com situacao discriminada;
zero numerico explicitamente informado permanece zero. Booleanos, textos
numericos, NaN/infinito e percentuais fora de 0-100 nao sao aceitos como metricas.
Lista ausente, nula, invalida e presente vazia sao situacoes distintas.
Linhas de estrutura invalida sao contadas sem copiar seu conteudo.
Nomes de interface ausentes/duplicados nao se tornam IDs pela banda ou posicao;
configuracao e estatisticas nao sao associadas automaticamente.

recebido_em e o horario da resposta validada de dispositivos do site. Nao e
data de medicao do radio: medido_em permanece NULL e data_medicao_confirmada
false. Estatisticas de um AP offline podem estar antigas; presencia/valor zero
na resposta nao comprovam estado atual ou ausencia de interferencia.
Segredos, clientes, payloads brutos, IPs e nomes de pessoas nao entram na whitelist.

O espelho SQL atual continua excluindo radios_nativos: teste confirma digest
e artefato de APs inalterados. Escritas de inventario ja habilitadas continuam
no fluxo existente; nao foi criado escritor, tabela, carga ou flag RF.

Depois do push/pull, aguardar uma coleta UniFi normal (ou atualizar somente
as antenas pela tela existente). Nao executar checklist completo apenas para
isso nem reiniciar PostgreSQL. Repetir audit_ap_radio_sources.py: a nova fonte
radios_nativos informa contagens, identidades concordantes, recebimento com
fuso, interfaces e metricas ausentes/nulas/invalidas/explicitamente informadas,
sem exportar identificadores ou valores individuais. Antes de nova coleta,
aps_sem_projecao_nativa e esperado. As duas fontes sao auditadas separadamente:
a versao scripts/Unifi.py nao cria o agregado legado de interferencia.

Validacao local sintetica: 83 testes passaram, incluindo comparacao do JSON
legado e numero de requisicoes das duas versoes antes/depois da extensao.
Nao foi executada coleta real. Um teste adicional de escopo regional que importa
web_config nao concluiu por indisponibilidade de credenciais DPAPI locais;
nao houve alteracao de permissoes/escopo nesta etapa.

## Execucao no Rigel

Publicar codigo e fazer pull antes de executar:

```powershell
& 'C:\Automacao\.venv31410\Scripts\python.exe' `
    'C:\Automacao\scripts\database\audit_ap_radio_sources.py'
```

Somente leitura de data/unifi.json, sem import de UniFi.py, config, Flask,
cofre ou coletores. Nao conecta SQL/controladora e nao altera arquivos.
Exporta apenas hash, contagens e categorias fixas, nunca nomes/sites, MACs,
IPs, IDs, valores individuais ou credenciais. Hash corresponde aos mesmos
bytes analisados. JSON com chaves repetidas ou estrutura raiz invalida e recusado.

Mede cobertura/formato dos percentuais, zeros sem comprovacao, datas por linha,
contagens declaradas divergentes e candidatos por site/nome exatos, sem aliases,
aproximacao, aprovacao de vinculos ou alteracao de permissoes. Canais inteiros
positivos sao apenas formato, nao validacao regulatoria ou prova de banda.
Nomes repetidos permanecem ambiguos. Risco e contado como declarado, sem recalculo.

Proxima decisao de carga depende do resultado real da nova coleta. Uma preservacao do legado deve ser
identificada como projecao nao confirmada; telemetria nativa exigira evidencia
explicita de origem/identidade/ausencia, em etapa separada. Nenhuma migracao,
carga, sincronizacao RF ou troca do leitor foi preparada nesta etapa.
