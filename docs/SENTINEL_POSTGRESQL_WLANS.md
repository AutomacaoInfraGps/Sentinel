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
