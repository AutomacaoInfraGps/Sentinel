# Auditoria do inventario de firmware SQLite

## Estado anterior confirmado no Rigel

PostgreSQL: 166 switches presentes, 26 sem regional, todos com verificacao
e declarados online. Publicacao de inventario completo em
2026-11-18 16:19:41.981785-03; sincronizacao em 16:19:42.403644-03.
Ambos os caches JSON tinham as mesmas 166 identidades, sem duplicidades de
ID; um IP compartilhado por identidades distintas. Isso nao e identidade
suficiente para anexar firmware automaticamente.

## Execucao

```powershell
& 'C:\Automacao\.venv31410\Scripts\python.exe' `
    'C:\Automacao\scripts\database\audit_switch_firmware_sources.py'
```

Usa o caminho configurado pelo codigo da tela:
data/switch_updates/scheduled_updates.sqlite3. --database permite apontar um
snapshot consistente ja preparado. Nao copiar somente o arquivo principal
de um SQLite em uso ignorando WAL. Nao parar jobs ou executar consultas aos
equipamentos para este levantamento.

## Garantias e limites

Abre URI SQLite mode=ro&cache=private, nao cria banco se estiver ausente e
ativa PRAGMA query_only. Nao importa/inicializa SwitchUpdateScheduler,
config, web_config ou o cofre. Nao executa CREATE/ALTER/INSERT/UPDATE/DELETE,
mudanca de journal_mode, checkpoint, migracao ou agendamento. O authorizer
permite somente leituras das oito colunas da tabela switch_firmware_inventory
e a verificacao de tipo/nome desse objeto em sqlite_master. Bloqueia consultas
as tabelas de jobs, funcoes, comandos de escrita e demais tabelas.

A leitura ocorre em transacao SQLite coerente; WAL ativo e respeitado, sem
immutable=1 que poderia ignorar transacoes confirmadas no WAL. O mecanismo
SQLite pode usar/criar arquivos auxiliares de coordenacao WAL/SHM conforme
o ambiente; nao prometer ausencia absoluta de efeitos de bookkeeping no
filesystem. Nenhum dado logico do aplicativo e gravado. A conexao e fechada
explicitamente em todos os caminhos. O arquivo de cache e lido e relido,
mas SQLite e JSON nao formam uma transacao atomica conjunta.

Tabela ausente, objeto que seja view, schema diferente, lock/erro de leitura
ou inventario acima de 10000 linhas retornam diagnostico fixo sem mensagens
brutas do SQLite. Fonte indisponivel nao vira inventario vazio. Apenas uma
tabela existente pode retornar registros=0 legitimamente. O codigo nao
consulta registros de jobs mesmo quando estao no mesmo arquivo fisico.

Resumo inclui cobertura de campos textuais, formatos temporais, duplicidade
de host/nome/IP e origens conhecidas (inclusive bulk_webui, gravado pela
consulta em lote da tela). Origens inesperadas ficam em categoria fixa,
nunca sao exibidas como chaves arbitrarias. No modo padrao, nomes, IPs,
regionais, modelos, versoes, erros brutos ou credenciais nao saem no JSON. Nao calcula confianca
de firmware, idade/suporte de versao, sucesso de atualizacao ou novas coletas.

## Identidade e proxima etapa

Resultado confirmado no Rigel: 140 registros de firmware, todos com horario
com fuso e origem bulk_webui. Comparacao com o cache: 137 candidatos com IP
e nome concordantes; 1 ambiguo, 1 com IP e nome apontando identidades
diferentes e 1 sem correspondencia. Nenhum vinculo foi aprovado.

Para conferir somente as pendencias, executar:

```powershell
& 'C:\Automacao\.venv31410\Scripts\python.exe' `
    'C:\Automacao\scripts\database\audit_switch_firmware_sources.py' `
    --unresolved
```

Essa opcao explicita inclui nomes, hosts, IPs normalizados, regionais e
identidades candidatas (tipo/id de origem), limitando rotulos a 255 caracteres.
Somente linhas pendentes aparecem em pendencias_identidade, separando
candidatos por IP e por nome, sem escolher automaticamente um deles.
O resumo padrao continua sem identificadores. Modelos, versoes, erros,
credenciais e conteudo de jobs continuam excluidos nos dois modos.
O resultado pode mudar se o inventario ou cache forem atualizados entre execucoes.

O inventario SQLite e identificado por host e nao guarda hostid Zabbix.
A tela usa cruzamento por IP ou nome; a auditoria somente sugere candidatos
com o cache de status. Enderecos internos divergentes, IP/nome que apontam
identidades diferentes, IPs compartilhados e candidatos sem identidade
valida nao sao aprovados. Mesmo IP+nome concordantes continua candidato;
regional ou versao sozinhas nao vinculam um equipamento.

Modelo/versao e checked_at_utc pertencem ao inventario de consulta de
firmware, nao ao status de rede de ultima_verificacao. O scheduler pode
preservar modelo anterior mais longo ao atualizar uma identidade: o horario
da linha nao prova que todos os atributos foram detectados naquele instante.
Nao migrar jobs junto com esse inventario nem mudar o mecanismo de atualizacao.

Revisar resumo do Rigel, resolver candidatos pendentes e definir identidade
com fonte/evidencia antes de preparar esquema, backup e carga PostgreSQL.
Nenhuma migracao ou espelho de firmware foi preparado nesta etapa; a tela e
os jobs existentes permanecem inalterados.
