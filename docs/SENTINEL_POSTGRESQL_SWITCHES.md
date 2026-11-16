# Carga inicial de switches

## Fonte e identidade

Usa output/switches_status_cache.json, publicado atomicamente por
GerenciadorSwitches._salvar_status_cache. A fonte primaria e o Zabbix; a mesma
rotina preserva local_only de laboratorio. O mapa tem agrupamentos/filtros e
nao e autoridade para inventariar switches nativos. Nao altera o coletor atual.

A chave e fonte/tipo_origem/id_origem. fonte=sentinel_zabbix_principal representa
a unica origem Zabbix atual do projeto, nao um identificador descoberto por URL.
Nao mistura instancias; migrar/trocar o Zabbix exige revisar essa identidade.
Zabbix usa hostid decimal positivo (nao IP/nome). Dois hosts com mesmo hostid
bloqueiam a carga. Switch sem hostid bloqueia, nunca e descartado silenciosamente.
local_only=true usa identidade separada pelo nome local normalizado; rename
futuro desses itens exige reconciliacao, nao identidade de Zabbix sintetizada.

Preserva status, ultima verificacao, modelo/origem, local, CORE/origem,
manutencao e quantidade de alertas. Nao recalcula alertas/estado. Ainda nao
inclui telemetria de portas, CPU, memoria ou historico, ausentes desse cache.
Nao armazena texto livre de problemas/diagnosticos, credenciais ou JSON bruto.
IP e endereco DNS sao separados, sem resolucao de nomes; DNS nao vira IP ficticio.
Horarios ingenuos usam fuso explicito, nao mtime nem hora da importacao.

## Vinculo regional e autorizacao

O cadastro estrutura_regionais.json fornece codigo/nome para vinculo EXATO e
unico apos normalizar acentos, separadores e tokens REG/REGIONAL/REGIAO.
Nao usa substring, fuzzy matching, descricao, IP ou nome do switch para adivinhar
regional. Se dois codigos/nome colidirem, fica ambiguo, sem escolher o primeiro.

Sem correspondencia, ambiguo ou ausente: codigo_regional=NULL e motivo separado;
preserva regional_origem para reconciliacao tecnica. Mais switches podem ficar
sem vinculo que no mapa atual, que usa outras regras. Nao e perda de registros.
Nao corrigir vinculos automaticamente para obter a mesma contagem do mapa.

Todas as consultas futuras de usuario exigirao codigo_regional no escopo AD
validado pelo backend. NULL nao e uma regional global nem permite acesso a
usuarios limitados. Nenhuma nova rota de usuario/SofIA ou leitura e adicionada
aqui. sentinel_api e conta tecnica SELECT, nao implementa AD/RLS por si so.
Quarentena e vinculados compartilham tabela com constraint de coerencia; a conta
tecnica pode conferir tudo, mas nunca deve repassar isso sem filtro autorizado.

## Guardas da carga

- SQL 004 cria somente operacional.switches, owner sentinel_owner, destino
  sentinel/5433/E:/Sentinel/PostgreSQL/data, transacao e timeouts.
- Reader SELECT; collector SELECT/INSERT, sem UPDATE/DELETE/TRUNCATE/CREATE.
- Importador simula sem banco por padrao. --check-database e somente leitura.
- --apply exige Rigel, identidade SQL fixa e --expected-digest exato revisado.
- Digest inclui os hashes DOS DOIS arquivos, fuso e projecao. Congelar ambos.
  Alteracoes inclusive em campos nao importados invalidam o digest de carga.
- Fonte nao tem publicacao global confiavel. Nao inventa uma usando mtime ou
  maior ultima_verificacao: os horarios individuais sao apenas observacoes.
- Trava regionais SHARE ROW EXCLUSIVE (coletor ja tem UPDATE) para serializar
  importadores, e switches ROW EXCLUSIVE permitido por INSERT.
- Exige switches vazia, todas as regionais da origem ja no banco, confere total
  final e grupos de vinculo. Commit/rollback pertencem ao contexto da conexao.
- Nao insere/atualiza regionais, servidores, firewalls ou licencas.
- Erros mostram etapa/tipo/SQLSTATE, nunca parametros ou texto bruto do driver.

## Implantacao controlada no Rigel

1. Commit/push e pull. Nao repetir migracoes 001/002/003.
2. Simular, sem conexao:

```powershell
& 'C:\Automacao\.venv31410\Scripts\python.exe' `
    C:\Automacao\scripts\database\import_switch_catalog.py `
    --source-timezone America/Sao_Paulo
```

3. Rever total, duplicidades/identidade, vinculados/quarentena e horarios.
4. pg_dump custom de sentinel e pg_restore --list. Restauracao real ainda precisa
   ser testada separadamente. Congelar cache e cadastro em pasta restrita a
   operador/SYSTEM/admins, como nas cargas anteriores. Cadastro contem refs DPAPI;
   nao compartilhar/commitar arquivos, nem abrir ACL.
5. Simular com --cache e --regionals nas duas copias protegidas e revisar digest.
6. Aplicar somente 004 como sentinel_admin, psql -X e ON_ERROR_STOP=1. Nao repetir
   depois de COMMIT. Conferir --check-database com as copias, tabela switches vazia.
7. Somente depois --apply --expected-digest usando as MESMAS copias.
8. Conferir total e vinculos com sentinel_api. Nao repetir carga inicial.

Esta implementacao nao executou a migracao no Rigel e nao tem PostgreSQL local
para homologacao real. Testes de unidade usam cursores simulados, dados sinteticos
e verificacoes de guardas. A simulacao local nao valida os registros de producao.

## Proxima fase, ainda nao implementada

Sincronizacao automatica dos switches exigira metadado de publicacao global
no caminho original de _salvar_status_cache sem mudar o formato legado do cache
nem fingir observacao nova de todos os itens a cada verificacao individual.
Tratar merges local_only, falha parcial, concorrencia entre processos e itens
removidos antes de adicionar hook/flag e permitir escrita incremental.
Nao habilitar uma configuracao de switches ainda: nao ha worker nesta etapa.
