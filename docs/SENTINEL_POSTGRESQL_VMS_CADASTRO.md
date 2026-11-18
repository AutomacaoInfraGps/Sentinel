# Carga inicial do cadastro de VMs (018)

## Escopo confirmado pelo operador

A aba de VMs ainda esta em desenvolvimento. Auditoria do Rigel encontrou
somente 1 VM, com ID/IP validos, regional textual Rio de Janeiro, status Unknown
e sem horario de verificacao. O operador confirmou o vinculo com
REG_RIO_DE_JANEIRO e que so ha a VM do RJ cadastrada atualmente.

O IP tambem corresponde a um servidor cadastrado, mas isso nao comprova que os
dois registros devem ser fundidos. Nao ha FK nem insercao/alteracao em servidores.

018 e SOMENTE cadastro inicial, nao conclui a migracao da tela de VMs inteira.
Nao habilita sincronizacao automatica, nao altera web_config/coletores/JSON,
nao configura WinRM/TrustedHosts e nao consulta equipamentos.

## Projecao SQL

- fontes_cadastro_vms: origem fixa sentinel_vm_cadastro, hashes de ambos os
  arquivos, fuso legado se explicitamente informado, digest e importado_em.
- maquinas_virtuais: origem + ID original, nome, IP principal, FK regional,
  rotulo regional original, regra de vinculo, descricao opcional, status_declarado
  e ultima_verificacao quando a fonte trouxer data completa valida.

Unknown permanece Unknown. Data ausente permanece NULL. importado_em e somente
a data de entrada SQL, nunca substitui coleta ausente. Running e preservado
como declaracao do cadastro, nao como evidencia real de estado no hipervisor.

O importador permite apenas o codigo RJ exato ou o rotulo Rio de Janeiro
(casefold e espacos externos removidos). Nao estende a aprovacao a RG_*, outros
nomes normalizados ou outras regionais. Novos vinculos precisam revisao futura.

ID vazio, nao textual, repetido ou com espacos externos bloqueia a carga.
IP invalido ou repetido entre VMs bloqueia. Uma lista ipAddresses que contenha
enderecos adicionais/divergentes tambem bloqueia para nao descartar IPs.
Lista vazia, ausente ou equivalente ao unico IP principal e aceita.
O cadastro por timestamp em segundos ainda nao foi modificado; a validacao
protege esta carga contra colisoes, nao corrige o gerador de IDs do runtime.

Datas legadas sem fuso exigem --source-timezone explicito; com fuso sao
convertidas para UTC. Hora solta ou data sem hora nao vira observacao.
Fuso IANA invalido e lacunas/ambiguidades de horario de verao bloqueiam.

Nao copia username/password, referencias de credenciais, tokens, dados brutos
ou campos tecnicos host_id/host_name/operatingSystem/processors/memory/uptime/
details/coletado_em. Alguns desses campos sao simulados pelo verificador atual:
nao podem virar telemetria comprovada por estarem no JSON. O resumo conta a
presenca dos campos tecnicos excluidos, mas nunca imprime seus valores.
Consultas de hardware/servicos/logs sob demanda ficam para uma etapa propria.

## Seguranca e consistencia

Nao resolve segredos do environment.json, nao importa web_config e nao exporta
nomes, IPs ou contas na saida. Campos extras desconhecidos nao entram na projecao.
Descricoes e nomes operacionais explicitamente selecionados continuam sendo
texto livre do cadastro; nao constituem uma garantia de que o operador nunca
digitou informacao sensivel nesses campos. Revisar antes de liberar leitores.

Hash da fonte cobre o arquivo original completo, inclusive campos excluidos,
mas apenas o hash e armazenado, nao o payload bruto. O JSON ORIGINAL PODE CONTER
SENHAS: copias de seguranca precisam ACL restrita; nunca enviar ao chat ou Git.
Esta etapa nao corrige nem replica o mecanismo atual de armazenamento de segredos.

Tabelas de inventario sanitizado pertencem a sentinel_owner. PUBLIC sem acesso,
sentinel_reader tem SELECT e sentinel_collector somente SELECT/INSERT, sem
UPDATE/DELETE. sentinel_api herda o papel de inventario ja configurado; nenhum
grant de leitura de contatos/admins e acrescentado. Escopo AD deve ser aplicado
pelas futuras rotas SQL antes de devolver dados a usuarios.

Carga transacional, advisory lock dedicado, locks de tabela compativeis com
SELECT/INSERT, PK/FK/UNIQUE. Exige as duas tabelas vazias, RJ presente no destino
e confere as linhas inseridas antes do commit. Nao faz UPSERT nem deduplica.
O chamador controla commit/rollback e sucesso so e impresso apos commit.
Advisory lock protege escritores cooperantes; SQL externo precisa respeitar
o protocolo. Nao e transacao distribuida com arquivos nem altera o runtime.

## Sequencia no Rigel

1. Publicar os arquivos novos e simular sem SQL:

```powershell
& 'C:\Automacao\.venv31410\Scripts\python.exe' `
    'C:\Automacao\scripts\database\import_vm_catalog.py'
```

2. Revisar 1 VM, 1 regional, unknown e 1 data ausente. Nao exigir fuso para uma
   data que nao existe. Se o arquivo mudou, revisar o novo conteudo primeiro.
3. Fazer novo backup pg_dump custom-format de sentinel e validar pg_restore --list.
4. Congelar data/vms.json e estrutura_regionais.json em pasta de backup com ACL
   restrita (ambos podem conter segredos). Pausar edicoes durante a copia e
   comparar hashes originais/copia. Nao substituir o arquivo atual do Sentinel.
5. Simular as copias com --source COPIA_VMS.json --regionals COPIA_REGIONAIS.json.
   Se houver datas legadas, informar o mesmo fuso em todas as etapas. Digest
   inclui as duas copias, o fuso escolhido, origem e registros tipados.
6. Aplicar somente 018_vm_catalog.sql como sentinel_admin com psql -X,
   ON_ERROR_STOP=1, sentinel em loopback:5433. O DDL valida tambem o data_directory.
7. --check-database com ambas as copias explicitas. Somente no RIGEL, usando
   sentinel_collector via DPAPI. Esperar duas tabelas vazias e RJ presente.
8. --apply --expected-digest HASH_EXATO da copia revisada, com os mesmos argumentos.
   Nao repetir a carga em tabelas ocupadas. Em erro conferir destino antes de repetir.
9. Conferir contagens, sem exportar registros:

```sql
SELECT count(*) AS vms, count(*) FILTER (WHERE ultima_verificacao IS NULL) AS sem_verificacao
FROM operacional.maquinas_virtuais;
SELECT status_declarado, count(*) AS vms FROM operacional.maquinas_virtuais GROUP BY status_declarado;
SELECT codigo_regional, count(*) AS vms FROM operacional.maquinas_virtuais GROUP BY codigo_regional;
```

Nenhuma gravacao remota foi executada pelo desenvolvimento. Testes locais
operational_vm_catalog_test.py usam JSON sintetico/mocks SQL; a migracao real
precisa homologacao no Rigel. Nao habilitar sincronizacao automatica enquanto
o modulo de VMs e suas evidencias de coleta ainda nao estiverem definidos.
