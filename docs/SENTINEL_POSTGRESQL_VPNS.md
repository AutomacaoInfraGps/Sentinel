# VPNs: auditoria antes da modelagem

Firewalls/licencas, servidores e switches ja tiveram persistencia paralela
validada pelo operador. A etapa VPN comeca SEM migracao SQL, importacao ou flag.

## Lacunas encontradas no codigo

- GerenciadorFortigate.obter_vpn_ipsec usa o resumo SSH do hub. Cada registro
  contem tunel, comentario, interface, status e ultima_verificacao HH:MM:SS.
- O fallback FortiManager informa device no envelope, mas nao nos registros.
- _prepare_vpn_operational_records preserva essa hora sem data, acrescenta nome,
  regional e status. Nao acrescenta dispositivo ou VDOM.
- publish_group_records e publish_map_snapshot compartilham o estado operacional.
  A publicacao do grupo nao comprova a data da observacao individual, nem uma
  consulta nova ao equipamento. O mapa e uma consolidacao derivada.

Nao usar regional como identidade do firewall: o tunel observado pertence ao
hub e a regional pode ser o destino remoto. Nao supor VDOM root nem reconstruir
observacao como "hoje + HH:MM:SS". Nao fundir tuneis so pelo nome.

## Conferencia no Rigel

Depois de commit/push e pull, executar no usuario operacional habitual:

```powershell
& 'C:\Automacao\.venv31410\Scripts\python.exe' `
    C:\Automacao\scripts\database\audit_vpn_sources.py
```

O comando le os JSONs locais existentes e o catalogo de regionais. Nao importa
configuracao de credenciais, nao acessa DPAPI, rede, Flask ou PostgreSQL e nao
grava arquivos. Exporta somente contagens e classificacoes fixas. Nao exporta
nomes, IPs, comentarios, codigos regionais, tokens ou valores de erros.

Ausencia de dispositivo/VDOM em um registro nao prova falta de configuracao do
coletor. A cobertura precisa ser corrigida na origem, com metadados verificados,
antes da carga inicial. Contagens de vinculo exato sao diagnostico de dados,
nao uma decisao de autorizacao de usuarios.

## Proximas etapas, ainda nao executadas

1. Conferir a auditoria real, inclusive duplicidades e horarios.
2. Preservar contexto verificado de dispositivo, VDOM, origem e instante de
   coleta nos registros, distinguindo consulta direta e fallback.
3. Validar nova publicacao sem mudar agendamento, filtros AD ou leitores atuais.
4. Preparar tabela e importador tipado, backup, simulacao e carga congelada.
5. Habilitar persistencia paralela somente apos homologacao manual.

Dados antigos sem identidade ou data suficiente nao ganham valores ficticios.
Nao ha conexao nova com a SofIA nesta etapa. Leituras futuras continuam exigindo
escopo autorizado no backend; VPN sem regional nao concede acesso global.
