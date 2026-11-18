# Auditoria das lacunas da tela de Servidores

## Escopo

Somente leitura de estrutura_regionais.json e do grupo servidores em
output/sentinel_operational_state.json. Sem SQL, cofre, coletores, teste de
conectividade ou chamada a API de hardware. Nao importar web_config,
operational_state, gerenciadores ou config: esses modulos tem efeitos de
inicializacao e nao sao necessarios para examinar arquivos.

```powershell
& 'C:\Automacao\.venv31410\Scripts\python.exe' `
    'C:\Automacao\scripts\database\audit_server_sources.py'
```

Enviar somente o JSON resumido, nao os arquivos. O resumo nao inclui nomes,
IDs, regionais, enderecos, descricoes, erros brutos ou valores de credenciais.
Somente contabiliza campos de acesso ja presentes nos JSONs, sem resolver
referencias DPAPI. Hashes dos arquivos incluem todos os bytes, nao os valores
em texto. Duas leituras confirmam estabilidade de cada arquivo isoladamente;
as fontes nao representam uma transacao atomica conjunta.

## Campos e fontes existentes

002/003 e services/operational_server_postgres.py projetam id, nome, tipo,
ip, modelo, funcao, sistema_operacional, status, ativo, ultima_verificacao e
tempo_resposta do cadastro regional. O cadastro define identidade/existencia;
o escritor paralelo e disparado ao salvar esse cadastro. Nao concluir que
os registros do cache do mapa ja estejam automaticamente no PostgreSQL.

A auditoria declara cobertura de uma projecao do codigo, nao do banco real.
Nao consulta tabelas, privilegios ou marcadores SQL de producao. Conferir
posteriormente no banco, antes de planejar extensao ou troca de leitor.

Na home /servidores, registros operacionais frescos da regional podem ser
preferidos ao cadastro. No detalhe da regional, o JSON continua definindo os
servidores existentes e um operacional mais recente pode sobrepor somente
estado/resposta/erro/verificacao/manutencao/motivo. A rota usa ID e fallback
por IP; isso nao torna IP uma identidade de servidor aprovada para SQL.

O resumo compara IDs textuais exatos dentro da mesma regional. Identidades
normalizadas repetidas sao diagnosticadas, mas nao fundidas. IP apenas na
mesma regional e candidato nao aprovado; IP repetido ou ID/IP que apontam
registros diferentes ficam ambiguos. Nao escolher o primeiro candidato.
Contagens de divergencias entre pares por ID nao significam que o cache
seja mais novo/correto: a auditoria nao aplica TTL, prioridades temporais,
escopo AD por usuario ou a selecao efetiva da pagina.

False e zero sao valores presentes, nao campos vazios. Diferenca de valor
ausente para false/zero e uma divergencia declarada, nao uma alteracao SQL.
ultima_verificacao e evidenciada separadamente de coletado_em; updated_at
e horario de publicacao do cache e nao prova medicao de hardware.

## Hardware sob demanda

O botao de hardware em regional_detalhes.html chama a rota
/api/regional/.../servidor/.../hardware. Essa rota retorna hardware para a
tela; nao foi identificado um caminho de gravacao desse retorno no cadastro
ou no grupo servidores. Ausencia de hardware nesses JSONs nao significa
que o botao nunca coletou nem que todo historico esteja preservado em outro
arquivo. O legado servidores.json e relatorios de preventiva nao sao as
fontes auditadas desta tela nesta etapa.

Campos exibidos incluem sistema operacional, fabricante, modelo, memoria,
CPU, uptime, discos, Bitdefender, temperaturas e ventoinhas. A auditoria mede
presenca de alguns desses campos diretos e sob hardware, e a presenca de
details/detalhes, sem validar seu conteudo como medicao real. Nao interpreta
conteudo arbitrario desses objetos nem executa fallback de coleta local.

O codigo tem caminhos WinRM/WMI, SSH Linux, probe HTTP, Redfish/iDRAC/iLO,
SNMP e fallback local. Uma futura persistencia precisa registrar alvo,
metodo, sucesso/parcialidade, horario com fuso e origem real dos valores.
Nao usar sucesso de probe HTTP como comprovacao de CPU/memoria/discos;
nao atribuir inventario do host local a um alvo remoto. Campos ausentes ou
padroes N/A/false nao provam ausencia de software, componente ou falha.

## Proxima etapa

Revisar resultado do Rigel. Se nao houver hardware persistido, nao inventar
uma carga historica: preparar captura tipada no caminho de coleta real em
etapa propria, preservando leitura atual e controles de acesso. Definir
escopo dos campos extras de cadastro/estado separadamente do hardware.
Nenhuma migracao ou mudanca do escritor/leitor de Servidores foi feita.
