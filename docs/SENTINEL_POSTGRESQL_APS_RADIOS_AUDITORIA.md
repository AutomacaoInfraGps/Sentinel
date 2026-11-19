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

Proxima decisao depende do resultado real. Uma preservacao do legado deve ser
identificada como projecao nao confirmada; telemetria nativa exigira evidencia
explicita de origem/identidade/ausencia, em etapa separada. Nenhuma migracao,
carga, sincronizacao ou troca do leitor foi preparada nesta auditoria.
