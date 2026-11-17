# APs UniFi: auditoria anterior ao cadastro SQL

## Escopo

`scripts/database/audit_ap_sources.py` le somente `data/unifi.json` e
`estrutura_regionais.json`. Nao importa config, Flask, DPAPI ou coletores; nao
conecta a rede ou banco, nem altera arquivos. A saida tem apenas contagens e
categorias fixas, sem MACs, IPs, nomes, IDs ou credenciais.

## Fonte observada no codigo

`UniFi.py` consulta os dispositivos por site, seleciona `type == uap`, aplica
o filtro existente de APs de teste e salva a lista `aps` pelo `data_store`.
O registro contem MAC, IP, nome, modelo, firmware, status, clientes, uptime e
nome do site. A lista `sites` guarda o ID e o nome. O AP nao recebe atualmente
o ID do site nessa projecao. O timestamp global e adicionado ao salvar o JSON;
ele nao comprova uma observacao individual de cada AP ou sucesso em todos os sites.

## Conferencias

- Validade/formato dos MACs e duplicidades na controladora e por site.
- IDs de sites e nomes duplicados; nomes ambiguos nunca resolvidos pelo primeiro.
- Correspondencia do campo site do AP com um site de ID unico; conflitos com site_id.
- Correspondencia regional somente por codigo/nome/descricao exatos, ignorando
  maiusculas e espacos externos. Esta contagem NAO reproduz os aliases do mapa
  nem altera as permissoes ou vinculos existentes.
- Cobertura de IP, modelos, firmware, status e coleta explicita por AP.
- Chaves JSON repetidas e estruturas invalidas rejeitadas.

O inventario ja e filtrado pelo coletor; nao representa todos os dispositivos
da controladora. Falha ou ausencia de site nao significa inventario vazio,
AP offline ou exclusao. MAC identifica o equipamento; site representa vinculo
atual e pode mudar. A identidade da controladora tambem precisa ser definida
antes de qualquer importacao. Nao usar nome ou IP como identidade do AP.

## Execucao no Rigel

```powershell
& 'C:\Automacao\.venv31410\Scripts\python.exe' `
    'C:\Automacao\scripts\database\audit_ap_sources.py'
```

Revisar o resumo real antes de preparar migracao SQL. Nesta etapa nao existe
nova tabela de APs, carga inicial ou sincronizacao automatica. Os leitores,
agendamentos e controles de acesso do Sentinel permanecem inalterados.
