# Expansao da base operacional

## Principios

Persistir fatos operacionais por fonte e categoria, nao criar uma tabela para
cada equipamento ou regional. Preservar coletores, frequencias, regras e telas.
Gravacao paralela primeiro; novas leituras somente depois da comparacao.
"Todos os dados" nao significa copiar indiscriminadamente JSONs, tokens, senhas,
chaves Wi-Fi ou dados pessoais para tabelas operacionais. Credenciais continuam
no cofre DPAPI. Auditorias de administradores/AD exigem tratamento separado.

## Mapeamento inicial do codigo

| Categoria | Caminho atual | Proximo cuidado |
| --- | --- | --- |
| Firewalls/licencas | dashboard_firewalls_cache, FortiManager | Ja sincronizados; nao repetir carga inicial |
| Servidores | estrutura_regionais e dados_dashboard | Identidade persistente e origem do status |
| Switches | switches_status_cache, Zabbix | hostid, instancia de origem, manutencao e vinculo regional |
| APs | data/unifi.json | MAC/ID, controladora/site e vinculo regional |
| Redes Wi-Fi | sites UniFi mais redes observadas | Identidade da WLAN/site; SSID sozinho nao basta |
| Links | estrutura regional e links_internet_auto | ID/interface, regional e firewall de origem |
| VPNs | APIs FortiGate, agrupamento regional | Tunel mais dispositivo/VDOM; nome sozinho nao basta |
| Mapa/alertas | composicao hibrida das fontes acima | Projecao derivada, nao uma coleta unica simultanea |

O mapa contem filtros, fallbacks e itens sem vinculo. Pode mostrar menos/mais
registros que uma fonte nativa de outra data. Seu horario de publicacao nao e o
horario de observacao de cada equipamento. Nao o usar sozinho como autoridade
para marcar todo equipamento ausente, offline ou como recem-coletado.

Os pontos atuais estao em `_montar_dados_mapa_monitoramento` e
`_salvar_cache_dashboard` de web_config.py. O gerenciador de atualizacoes do
Rigel tem diferencas locais historicas: nao substituir como parte desta etapa.

## Auditoria antes das proximas migracoes

`scripts/database/audit_operational_sources.py` usa somente biblioteca padrao,
le arquivos fixos e nao abre banco, API, Flask ou cofre. Retorna contagens,
presenca de campos permitidos e classificacao de horarios, nunca valores dos
equipamentos, nomes de campos desconhecidos, credenciais ou registros brutos.
Nao cria backups nem grava arquivos. Rodar localmente nao valida o Rigel.

Depois de commit/push e pull no Rigel:

```powershell
& 'C:\Automacao\.venv31410\Scripts\python.exe' `
    C:\Automacao\scripts\database\audit_operational_sources.py --summary
```

Sem --summary inclui candidatos de identidade e cobertura de campos. Uma chave
unica no cache nao prova estabilidade no tempo; IDs precisam ser confirmados
na origem. Ausente, lista vazia, lista invalida e itens sem vinculo sao separados.
Timestamp nao ISO e apenas classificado, nao convertido ou presumido invalido
para o negocio. Nao usar mtime como nova data de coleta.

## Sequencia de implantacao

1. Conferir volumes/identidades/horarios reais do Rigel e a cobertura de regionais.
2. Definir tabela e chave de origem por categoria, com regional nullable para
   quarentena tecnica de itens sem vinculo (sem acesso por usuarios regionais).
3. Criar migracao transacional, backup e carga simulada. Rever privilegios minimos.
4. Homologar escrita manual do snapshot congelado e comparar contagens/ausencias.
5. Acrescentar hook na publicacao da fonte original, independente por fonte.
6. Ativar gravacao paralela controlada e conferir atualidade, falhas e recuperacao.
7. Somente depois disponibilizar leituras com escopo AD validado no backend.

Nao ha novas tabelas, cargas ou hooks implementados nesta etapa de auditoria.
Os resultados do Rigel orientam a proxima categoria; nao executar uma migracao
generica para todas as fontes sem essas validacoes.
