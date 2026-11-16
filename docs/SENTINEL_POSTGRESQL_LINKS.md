# Links de internet: auditoria antes da carga

VPNs tiveram carga e sincronizacao automatica homologadas pelo operador:
166 VPNs, 154 online/12 offline na coleta 2026-11-16 16:51:02 -03, digest e
marcador confirmados sem --apply. Links sao a proxima categoria, ainda sem SQL.

## Caminhos atuais verificados no codigo

- web_config._executar_sincronizacao_links_todas_regionais chama a coleta por
  regional. _load_regional_interfaces resolve equipamento/ADOM do FortiManager,
  busca configuracao de interfaces e combina monitoramento via proxy.
- Fontes retornadas incluem fortimanager, fortimanager_proxy_monitor e
  fortimanager_config+proxy_monitor. Nao presumir uma unica fonte pelo nome da
  tela. Ha tambem caminhos legados fortigate e fallback_local.
- _coletar_links_regional combina interface e membros SD-WAN/SLA. O status pode
  vir de SLA, interface ou equipamento desconectado; nao equivale apenas a ping.
- estrutura_regionais.json guarda links e links_internet_auto. A tela prefere
  a lista automatica quando ela existe, mesmo vazia; o caminho legado aplica
  selecao/filtros. Somar ambas as listas duplica links.
- _build_auto_link_id gera identificador regional/interface e acrescenta sufixo
  quando ha colisao. O ID nao e por si so uma identidade global do equipamento.
- Persistencias individuais/em lote podem substituir ultima_verificacao por
  horario local de gravacao, inclusive ao persistir fallback. Nao o tratar como
  uma coleta nova confirmada de status. Os formatos e cobertura precisam ser
  medidos antes da migracao.

Nada disso foi alterado nesta etapa. Nao modificar agora filtros, frequencias,
origem de status, cadastro, vinculacao, AD, SofIA ou gerenciador de atualizacoes.

## Auditoria segura no Rigel

Depois de commit/push e pull, sem reiniciar:

```powershell
& 'C:\Automacao\.venv31410\Scripts\python.exe' `
    C:\Automacao\scripts\database\audit_link_sources.py
```

Le somente estrutura_regionais.json, output/sentinel_operational_state.json e
output/mapa_monitoramento_cache.json com biblioteca padrao. Sem rede, SQL,
Flask ou DPAPI. Nao grava, nao consulta equipamentos e nao exporta registros,
IDs, nomes, IPs, comentarios, provedores, credenciais ou texto de erros.
Chaves JSON duplicadas sao recusadas. Origens/status/modos desconhecidos viram
categorias fixas, nunca nomes de campos/valores arbitrarios na saida.

O relatorio separa as duas listas do catalogo e as projecoes. Conta IDs repetidos
dentro/entre regionais, cobertura de regional+ID e regional+endpoint+interface,
presenca de serial/VDOM e tipos de horarios/IP. Nao usa nome como interface nem
infere serial a partir do endpoint. Sem catalogo valido, nenhum vinculo pode
ser confirmado. Valores zero numericos contam como presentes; booleanos nao
viram IDs. Duplicidades sao diagnostico, nao criterio automatico de fusao.

## Proximos passos

1. Rever auditoria real e decidir a fonte para cadastro e para observacoes.
2. Definir identidade/vinculo sem fundir links por provedor/IP, com tratamento
   explicito de listas automaticas vazias, fallback e dados de verificacao.
3. Preparar tabela/importador e testes; simular antes de qualquer escrita.
4. Backup, copias congeladas protegidas, migracao, carga e leitura com api.
5. So depois, persistencia paralela controlada e homologacao de coleta nova.

Nao existe migracao SQL, importador ou flag de links criado nesta etapa.
Preservar as sincronizacoes ja habilitadas das outras categorias.
