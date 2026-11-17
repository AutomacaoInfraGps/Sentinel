# Redes Wi-Fi: auditoria antes da migracao

## Escopo desta etapa

`scripts/database/audit_wlan_sources.py` le somente `data/unifi.json` e
`estrutura_regionais.json`. Nao consulta a controladora, cofre DPAPI ou banco,
nao altera arquivos e nao exporta SSIDs, IDs, IPs, MACs, nomes de APs ou senhas.
A saida tem contagens e categorias fixas. Nenhuma tabela, carga ou flag de
sincronizacao WLAN e criada nesta etapa. A sincronizacao de APs continua
independente e com o comportamento existente.

## Limitacoes observadas no codigo

O coletor principal consulta configuracao WLAN e observa VAPs dos APs. Os
helpers de `services/unifi_networks.py` projetam nome, rede textual, bandas,
transmissao e ativo, removendo credenciais. A projecao de configuracao nao
preserva atualmente o ID nativo da WLAN nem o ID da networkconf. Ela tambem
deduplica por nome sem distinguir maiusculas. A fusao com runtime usa nome
sem distinguir maiusculas e nao preserva a origem de cada item.

Essas listas servem a apresentacao atual, mas nao comprovam inventario de
configuracao com identidades completas. SSID nao e chave de WLAN; uma mesma
rede pode ser observada em muitos APs e o mesmo nome pode existir em varios
sites ou em configuracoes diferentes. Nunca inventar ID pelo nome ou contar
cada VAP como uma WLAN configurada. Nao extrair VLAN/identidade de rede do
rotulo textual de exibicao. Transmissao textual pode representar nomes de APs
ou de grupos, nao comprova FK para equipamentos.

O script legado `scripts/Unifi.py` nao coleta WLANs. Ausencia dessa lista nao
deve apagar WLANs do SQL nem significar que o site nao possui redes.

## O que conferir

- IDs de site e de WLAN disponiveis, conflitos de IDs e duplicidades por site.
- Nomes repetidos no mesmo site (exatos e ignorando maiusculas) e nomes
  compartilhados entre sites, sem fundir os registros da origem.
- Lista ausente, vazia ou invalida, contadas separadamente.
- Vinculo regional usando o resolvedor aprovado para os sites UniFi, sem
  correspondencia parcial ou vinculo por descricao geografica.
- Estado ativo somente quando booleano: ativo nao equivale a AP online,
  alcance de radio, clientes conectados ou disponibilidade fim a fim.
- Origem declarada e datas especificas de WLAN, nunca a data global do JSON
  ou a coleta de APs como substituto de coleta de configuracao WLAN.

Os campos de evidencia especificos de WLAN ainda podem estar ausentes.
A auditoria nao cria esses campos e nao infere sucesso de uma consulta de
configuracao a partir da existencia de SSIDs observados no runtime.

## Execucao no Rigel

```powershell
& 'C:\Automacao\.venv31410\Scripts\python.exe' `
    'C:\Automacao\scripts\database\audit_wlan_sources.py'
```

Revisar a saida real antes de definir a carga. Se os IDs e a proveniencia
nao estiverem disponiveis, o proximo passo e preservar uma projecao segura
de configuracao separada da lista de apresentacao e do runtime. Isso deve
manter as telas atuais, proteger passphrases/tokens e evitar alterar a
sincronizacao de APs ja homologada. Credenciais continuam no DPAPI.

Qualquer futura consulta SQL da SofIA deve filtrar sites/WLANs pelo escopo
regional autenticado no Sentinel; nao usar o nome do SSID como permissao.

## Projecao separada de configuracao preparada

O coletor principal (`Unifi.Py`) agora pode salvar em cada site:

- `wlans_configuradas`: lista segura com wlan_id nativo, nome, networkconf_id
  quando informado, ativo booleano ou nulo, bandas, origem configuracao_unifi
  e coletado_em com fuso UTC. Nao guarda passphrases, security, RADIUS,
  tokens, respostas brutas ou credenciais.
- `coleta_wlans_confirmada`, `wlans_coletadas_em`, `wlans_situacao`: evidencia
  especifica da consulta WLAN. Nao reutiliza a coleta AP nem o timestamp
  global adicionado na gravacao do arquivo.

A lista `redes_wifi` e seu merge de exibicao permanecem com o comportamento
existente; o Fluxo Neural e o overlay continuam lendo essa lista. A nova
projecao preserva IDs diferentes mesmo com SSID igual, inclusive diferencas
de maiusculas, e nao trunca IDs ou inventa identidades pelo nome.

O helper `services/unifi_wlan_collection.py` aceita apenas resposta HTTP
bem-sucedida com envelope reconhecido, sem erro explicito de API. As chamadas
existentes sao reaproveitadas, sem consultas adicionais. Uma resposta vazia
confirmada e registrada como lista vazia; falhas/erro de API nao comprovam
ausencia. Identidade ausente, duplicada ou conflitante invalida a projecao do
site inteiro, sem descartar registros silenciosamente ou exportar o erro bruto.
O estado enabled ausente ou nao booleano fica nulo; nao e inventado como ativo.

Os sites ainda seguem o criterio original de inclusao na publicacao (APs ou
redes para exibir). Sites omitidos nao significam exclusao/ausencia confirmada.
O script legado `scripts/Unifi.py` permanece sem coletar configuracao WLAN:
uma publicacao por esse caminho pode nao conter a nova lista. Nao interpretar
isso como zero WLANs. A sincronizacao SQL de APs continua projetando apenas
seus campos aprovados e ignora os novos campos WLAN.

Os campos novos ficam dentro de cada site, sem criar lista global de nomes
de redes fora do filtro regional. O filtro existente de sites UniFi remove
tambem a configuracao de sites nao autorizados. Nenhuma nova rota publica ou
alteracao de permissao AD foi criada.

### Homologacao da coleta, ainda sem SQL

1. Publicar o coletor, helper, auditoria e testes juntos; nao publicar o
   coletor sem o novo modulo importado.
2. Executar a coleta principal pelo mesmo fluxo que atualiza o inventario
   Wi-Fi no Fluxo Neural. Nao executar manualmente uma copia de outro script.
3. Aguardar terminar e rodar `audit_wlan_sources.py`. O resumo antigo fica
   em `unifi_nativo`; o novo e `unifi_configuracao_separada`.
4. Conferir sites com coleta confirmada, IDs nativos, origem, horarios e
   vinculos regionais. A quantidade configurada pode diferir da lista de
   exibicao: esta pode conter SSIDs apenas observados ou agrupar nomes iguais.
5. Somente depois da conferencia real preparar a migracao e o importador.
   Ainda nao existe tabela SQL ou flag de sincronizacao WLAN nesta etapa.

Os sites sem regional continuam sem vinculo automatico. Reaproveitar somente
o relacionamento site/regional aprovado; nao relacionar pelo nome do planeta.
