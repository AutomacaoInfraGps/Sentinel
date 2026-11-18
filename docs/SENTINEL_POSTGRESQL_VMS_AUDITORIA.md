# VMs: auditoria antes de definir a carga SQL

## Primeira etapa

scripts/database/audit_vm_sources.py le SOMENTE data/vms.json e o catalogo
estrutura_regionais.json. Nao importa web_config/GerenciadorVMs, nao resolve
credenciais, nao acessa AD/WinRM/hipervisor/SQL, nao faz ping e nao cria arquivo
ausente. Um inventario vazio ou invalido nao vira inventario real automaticamente.

Saida padrao: somente contagens de cobertura de campos conhecidos, identidades,
enderecos validos/duplicados, horarios e categorias fixas. Nao imprime nomes,
IPs, IDs de VMs, contas, senhas, detalhes, erros brutos ou valores desconhecidos
de status. Campos de acesso sao contados em conjunto, nunca exportados.
Nao e scanner completo de segredos: nao supor ausencia de credenciais porque
um contador e zero. O JSON original deve continuar protegido e fora de Git/chat.

--unresolved acrescenta somente rotulos regionais pendentes e candidatos a
codigo regional, nao registros de VM. Usar apenas se precisarmos conferir
vinculos; esses rotulos sao informacao interna. A auditoria nao aprova aliases.

## Achados de codigo que afetam o modelo

- Tela /vms le carregar_vms_cadastradas em web_config.py:9372. A fonte e uma lista
  data/vms.json, distinta de estrutura_regionais.servidores.
- Cadastro web gera id vm-<segundos> e salva name/ip/regional/description/status/
  last_check. Auditar IDs repetidos antes de usa-los como chave; timestamp em
  segundos nao garante unicidade entre cadastros simultaneos.
- GerenciadorVMsLocal pode gerar rotulos RG_*, enquanto o catalogo usa REG_*.
  Sao apenas candidatos ate validacao; nao corrigir nem fundir automaticamente.
- O mesmo IP de um servidor cadastrado sugere relacao, nao identidade comprovada
  de host/VM. Auditar sobreposicao sem fundir os dois cadastros por IP/nome.
- Verificar host_id/host_name/operatingSystem/ipAddresses: a tela suporta o
  formato do Server Manager, mas o cadastro manual nao preenche necessariamente
  todos esses campos. IP principal e lista podem estar divergentes.
- verificar_vm em web_config.py usa ping e preenche operatingSystem, processors,
  memory e alguns details com valores explicitamente simulados. lastBoot nesse
  trecho usa o horario atual, nao uma consulta real ao boot. Nenhum desses
  detalhes deve ser importado como telemetria comprovada so por estar presente.
  Running baseado em ping nao comprova estado real da VM no hipervisor.
- /api/vms/<id>/detalhes, /servicos, /logs e /relatorio fazem consultas sob demanda.
  As respostas nao sao automaticamente persistidas no cadastro. A carga inicial
  do JSON nao cobriria esses dados; sera necessario publicar evidencias sanitizadas
  com origem, horario com fuso, sucesso/abrangencia e identidade confiavel.
- Credenciais podem existir no JSON e o runtime usa tambem server_manager do
  environment.json. Esta etapa nao altera o fluxo de credenciais, nao pede
  envio de arquivos/senhas e nao migra credenciais para inventario SQL.

## Operacao

Publicar arquivo novo e executar no Rigel:

```powershell
& 'C:\Automacao\.venv31410\Scripts\python.exe' `
    'C:\Automacao\scripts\database\audit_vm_sources.py'
```

Revisar resumo real antes de desenhar migracao 018 ou sincronizador. Nao ha DDL,
gravacao SQL, alteracao da tela ou da fonte atual nesta etapa. Se o inventario
estiver vazio, confirmar o uso real da aba antes de inventar registros ou
duplicar os 76 servidores do outro dominio. Proximos passos dependem da evidencia
do Rigel, nao da quantidade de VMs existente na maquina local de homologacao.
