# Auditoria das fontes de Replicacao AD

Etapa somente leitura anterior a qualquer migracao SQL. Nao executa repadmin,
consultas AD, rede, DPAPI ou importacao da aplicacao web. Nao altera arquivos.
Nao exporta nomes de controladores, caminhos, detalhes ou erros brutos.

## Execucao no Rigel

```powershell
& 'C:\Automacao\.venv31410\Scripts\python.exe' `
    'C:\Automacao\scripts\database\audit_replication_sources.py'
```

Enviar somente o JSON resumido. Nao enviar os arquivos de origem.

## Fontes e selecao

A rota /replicacao le data/replicacao.json pelo data_store.py da raiz e uma
fonte publica. Ambas aceitam UTF-8, UTF-8 com BOM e Latin-1. A auditoria
recusa chaves JSON duplicadas e sinaliza mudanca dos bytes durante a leitura.

A fonte publica segue config._resolve_public_base, sem importar config:
AUTOMACAO_PUBLIC_BASE/data/replicacao.json, se configurado; caso contrario,
PUBLIC/Automacao/data/replicacao.json, com o padrao Windows de config.
O ambiente do terminal pode diferir do processo web. Nesse caso usar
--public-source com o arquivo exato utilizado pelo servico.

A tela prefere a fonte com maior total declarado (total_servidores ou
controladores); no empate prefere a local. Nao compara datas. A auditoria
informa uma previsao dessa regra, com ressalva para fontes invalidas/ilegiveis
ou totais que exigiriam conversoes inseguras. Nao prova qual arquivo o
processo web efetivamente abriu.

O endpoint /api/public/status/replicacao usa outro caminho legado baseado em
USERPROFILE/Public/replicacao.json. O script Replicacao_Final.ps1 escreve no
Desktop do usuario. Esta auditoria cobre as duas fontes da pagina, nao
reconcilia automaticamente todos esses caminhos.

## Identidade e evidencia

Reconhece servidores e detalhes.controladores. Preserva ausencia de lista,
lista invalida e lista vazia como situacoes distintas. Contabiliza nomes
completos e a identidade nome + secao explicita (Origem, Destino, Problema).
O mesmo controlador pode aparecer em Origem e Destino legitimamente.
Nao funde nomes curtos, nao inventa secao e nao atribui regionais.

O normalizador legado da tela pode inventar Destino, status e horario para
campos ausentes. A auditoria nao o executa. ultima_replicacao e preenchida
com a hora da coleta nos coletores atuais: nao comprova o horario da ultima
replicacao bem-sucedida. Datas sem fuso permanecem declaradas sem fuso.

O parser Python de replsummary usa a ultima coluna numerica como erros;
essa coluna pode representar percentual, nao quantidade de falhas. A
semantica deve ser validada antes de modelar contadores SQL. O coletor
PowerShell tambem pode criar linhas Problema derivadas de erros operacionais,
que nao sao observacoes de uma conexao de replicacao. Existe ainda fallback
de erro de processamento no fluxo web que cria um registro de exemplo;
nao tratar qualquer linha salva como controlador comprovado.

Totais de linhas podem diferir de controladores unicos por causa das secoes.
As contagens de divergencia sao diagnosticos, nao correcoes automaticas.

## Proxima etapa

Conferir o resumo no Rigel, identificar a fonte e evidencia real, decidir
identidades e semantica dos campos antes de preparar esquema e permissoes.
Depois: backup, copias restritas, simulacao com digest, migracao, carga e
conferencia. Nenhum leitor da tela ou escritor paralelo foi alterado aqui.
