# Escopo da v1 — AlertAD

## 1. Objetivo

Entregar uma automação executada no Rigel que receba eventos de alteração de
membros de grupos do Active Directory, identifique alterações em grupos de risco,
resolva o usuário pelo `MemberSid`, evite duplicidades e envie alertas independentes
por Teams e e-mail.

Os eventos dos DCs são disponibilizados no Windows Event Log do Rigel por meio da
infraestrutura baseada em WinRM. O AlertAD fará a leitura local e incremental do
canal `ForwardedEvents`, em lotes de até 500 eventos.

## 2. Divisão de responsabilidades

### Responsabilidade do agente

- desenvolver e revisar todo o código-fonte da v1;
- criar scripts auxiliares e arquivos de configuração de exemplo, sem dados reais;
- criar e executar testes automatizados locais com mocks, fakes e amostras anonimizadas;
- criar migrações e rotinas de manutenção do SQLite;
- preparar validações, mensagens de erro e proteções contra configurações inválidas;
- documentar os comandos e procedimentos que o usuário deverá executar;
- analisar resultados, logs sanitizados e erros fornecidos pelo usuário;
- corrigir o código quando os testes locais ou os testes conduzidos pelo usuário
  revelarem problemas.

### Responsabilidade do usuário e das equipes da empresa

- acessar os Domain Controllers, Rigel, Active Directory, Teams e Microsoft Graph;
- executar scripts nos servidores e validar os resultados no ambiente corporativo;
- instalar dependências e configurar a inicialização automática no Rigel;
- criar contas, conceder permissões e liberar conectividade de rede;
- inserir e proteger credenciais, tokens, destinatários e `chat_id`;
- fornecer somente amostras anonimizadas e logs sem dados sensíveis ao agente;
- executar testes reais de ADWS, Teams, e-mail e leitura dos eventos no Rigel;
- aprovar retenção, diretórios, permissões e entrada em produção.

O agente não deverá solicitar, inserir, visualizar ou validar credenciais reais. Os
testes automatizados deverão substituir integrações externas por implementações
simuladas. O sucesso no ambiente corporativo será confirmado pelo usuário seguindo
as instruções produzidas pelo agente.

## 3. Escopo funcional

### Eventos monitorados

- `4728` e `4729`: inclusão e remoção em grupo global;
- `4732` e `4733`: inclusão e remoção em grupo local;
- `4756` e `4757`: inclusão e remoção em grupo universal.

### Grupos monitorados

- Domain Admins;
- Administrators;
- Backup Operators;
- Enterprise Admins;
- Schema Admins;
- grupos cujo nome começa com `GGS_Suporte`, sem diferenciar maiúsculas e minúsculas.

### Comportamento esperado

- consultar eventos de forma incremental;
- ler no máximo 500 eventos por lote;
- retomar do último checkpoint após uma reinicialização;
- filtrar os grupos antes de consultar o AD;
- usar `MemberName` quando preenchido e consultar o `MemberSid` por PowerShell/ADWS
  somente quando o nome estiver ausente ou for `-`;
- enviar o alerta mesmo quando a resolução do SID falhar;
- impedir alertas duplicados;
- controlar Teams e e-mail de forma independente;
- separar eventos inválidos e erros permanentes para análise;
- não registrar credenciais, tokens ou segredos.

## 4. Arquitetura inicial proposta

```text
Domain Controllers
          ↓ WinRM / encaminhamento configurado pela infraestrutura
Windows Event Log no Rigel: ForwardedEvents
          ↓ Leitura local em lotes de 500
EventSource do AlertAD
          ↓
Parser e filtro de grupos
          ↓
Resolução do MemberSid por PowerShell/ADWS
          ↓
SQLite: evento, checkpoint e entregas
          ↓
Worker de notificações
          ↓
Teams e e-mail
```

O canal continuará configurável, mas `ForwardedEvents` será o padrão para o Rigel.
O AlertAD não configurará WinRM, assinaturas ou encaminhamento; ele consumirá
somente os eventos que já estiverem disponíveis localmente nesse canal.

## 5. Tarefas de implementação

### Etapa 0 — preparação dos insumos e instruções

- o agente cria checklists e comandos seguros para as validações;
- o canal `ForwardedEvents` já foi confirmado como fonte local no Rigel;
- o usuário valida que eventos originados nos três DCs aparecem nesse canal;
- o usuário fornece amostras anonimizadas dos seis tipos de evento;
- o usuário confirma que o XML preserva o DC de origem e o `EventRecordID` do log
  utilizado no Rigel;
- o usuário configura WinRM, assinaturas e encaminhamento fora do código;
- o usuário valida o módulo ActiveDirectory e `Get-ADUser` a partir do Rigel;
- o usuário providencia conta de serviço, permissões e períodos de retenção;
- o agente registra as interfaces confirmadas e ajusta o código sem receber os
  valores sensíveis.

Resultado: o agente recebe somente contratos, formatos e resultados sanitizados
necessários para desenvolver o código.

### Etapa 1 — configuração e contratos

- adicionar tamanho de lote configurável, com padrão 500;
- definir intervalo do polling;
- evoluir `EventSource` para receber checkpoint e devolver lote e próximo checkpoint;
- criar modelos para lote, item coletado e resultado da leitura;
- validar configurações na inicialização;
- preparar contratos para resolução de diretório e armazenamento de ocorrências.

Resultado: interfaces internas estáveis e independentes do método de coleta.

### Etapa 2 — fonte local de eventos no Rigel

- o agente implementa o adaptador local do Windows Event Log para `EventSource`;
- tornar o nome do canal configurável, com padrão `ForwardedEvents`;
- filtrar os seis IDs de evento durante a leitura;
- limitar cada leitura a 500 eventos;
- preservar XML, origem, canal, horário e `EventRecordID`;
- ordenar os eventos de forma determinística;
- implementar checkpoint e pequena sobreposição de leitura;
- tratar rotação ou limpeza do canal de eventos;
- registrar falhas sem incluir conteúdo sensível;
- criar instruções para o usuário configurar a conta e o canal de leitura;
- testar a fonte com fixtures e comandos simulados sempre que o Windows Event Log
  real não estiver disponível no ambiente de desenvolvimento.

Resultado: o AlertAD lê os eventos já disponíveis no Rigel sem reler o canal
completo e sem acessar remotamente os Domain Controllers.

### Etapa 3 — parsing e regras

- validar o parser com amostras reais dos seis eventos;
- manter processamento isolado por evento;
- filtrar grupos fora do escopo antes da consulta ao diretório;
- preservar deduplicação mesmo com sobreposição do polling;
- registrar campos ausentes como pontos de atenção;
- garantir que um evento malformado não interrompa o lote.

Resultado: somente eventos relevantes seguem para enriquecimento e alerta.

### Etapa 4 — resolução do `MemberSid`

- implementar `DirectoryResolver` com `Get-ADUser` local por PowerShell/ADWS;
- usar a identidade Windows do worker, com conta de serviço somente leitura ou
  gMSA, sem senha armazenada pelo AlertAD;
- permitir servidor ADWS aprovado opcional ou descoberta normal do domínio;
- buscar nome da conta, domínio, nome de exibição e tipo do objeto;
- validar se o objeto é usuário;
- criar cache temporário de SID para reduzir consultas repetidas;
- definir timeout e classificação das falhas ADWS/PowerShell;
- usar o SID como alternativa quando a resolução falhar;
- persistir o resultado utilizado no alerta;
- criar testes automatizados com subprocesso PowerShell simulado;
- disponibilizar simulação de `MemberName` ausente com `Get-Credential` apenas
  para homologação assistida, sem persistir a credencial;
- documentar a identidade de execução, módulo ActiveDirectory, ADWS e conta de
  leitura, sem credenciais no código ou nos argumentos.

Resultado: o alerta identifica o usuário sempre que o AD estiver disponível, sem
ocultar uma alteração quando a consulta falhar.

### Etapa 5 — persistência SQLite

- criar migração segura do esquema atual;
- persistir os campos normalizados necessários para reconstruir o alerta;
- persistir checkpoint da coleta;
- persistir mensagem ou snapshot utilizado em cada alerta;
- armazenar estado, tentativas, último erro e próxima tentativa por canal;
- criar armazenamento separado para eventos inválidos;
- registrar erros permanentes de entrega;
- implementar limpeza automática conforme a retenção aprovada;
- habilitar índices e configurações adequadas para um único worker;
- impedir uso do arquivo SQLite em compartilhamento de rede.

Proposta de retenção a validar:

- eventos e entregas: 90 dias;
- eventos inválidos e erros permanentes: 180 dias;
- logs operacionais: 30 dias;
- XML bruto excepcional: no máximo 30 dias, protegido.

Resultado: o serviço retoma após reinício sem perder alertas pendentes.

### Etapa 6 — worker principal

- implementar ciclo contínuo de polling;
- consumir todos os lotes disponíveis, 500 por vez;
- processar eventos individualmente;
- avançar o checkpoint somente após persistência segura;
- recuperar eventos e entregas pendentes após reinício;
- impedir duas instâncias concorrentes sobre o mesmo banco;
- implementar desligamento controlado;
- continuar operando quando um evento individual falhar;
- controlar atraso para não consultar continuamente o log local quando não houver dados.

Resultado: processamento contínuo, recuperável e sem duplicidade.

### Etapa 7 — notificações e retentativas

- ligar os adaptadores Graph existentes ao worker;
- validar configurações do Teams e do e-mail;
- classificar falhas temporárias e permanentes;
- enviar imediatamente na primeira tentativa;
- agendar as três primeiras novas tentativas com intervalo de 30 segundos;
- agendar a quarta nova tentativa após 5 minutos;
- agendar a quinta nova tentativa após 15 minutos;
- respeitar `Retry-After`, utilizando o maior intervalo aplicável;
- persistir `next_attempt_at` para sobreviver a reinicializações;
- garantir que a falha de um canal não bloqueie o outro;
- encaminhar falhas permanentes para análise, sem repetição automática;
- testar Teams e e-mail com clientes HTTP e tokens simulados;
- fornecer instruções para o usuário configurar e executar os testes reais, sem
  incluir valores sensíveis no repositório.

Resultado: até um envio inicial e cinco novas tentativas independentes por canal.

### Etapa 8 — eventos inválidos e ocorrências operacionais

- definir categorias de evento inválido e erro permanente;
- persistir horário, origem, componente, motivo e identificadores disponíveis;
- evitar armazenamento desnecessário de dados sensíveis;
- impedir que o mesmo evento inválido gere ocorrências infinitas;
- criar comandos ou relatórios para listar e marcar ocorrências como resolvidas;
- preparar uma saída estruturada e estável para integrações futuras.

Resultado: problemas ficam disponíveis para análise sem interromper a automação.

### Etapa 9 — logs, segurança e operação

- implementar logs estruturados com rotação;
- remover ou mascarar tokens, segredos e dados sensíveis;
- preparar o código e instruções para o usuário proteger banco, cache delegado e
  configurações por permissões do sistema;
- criar indicadores básicos: eventos lidos, filtrados, alertados e com falha;
- registrar tempo entre ocorrência e envio do alerta;
- criar comandos de status, diagnóstico e teste controlado;
- documentar instalação, inicialização, parada, recuperação e renovação do Teams;
- fornecer os arquivos e comandos necessários para o usuário configurar a
  inicialização automática no Rigel.

Resultado: operação suportável sem depender de uma sessão de usuário aberta.

### Etapa 10 — testes e aceite

- ampliar testes unitários para novos modelos e regras;
- testar lotes vazios, parciais, completos e com mais de 500 eventos;
- testar checkpoint, sobreposição e deduplicação;
- testar interrupção no meio de um lote e recuperação após reinício;
- testar resolução ADWS com sucesso, ausência e timeout;
- testar evento inválido no meio de um lote válido;
- testar erros temporários, permanentes e `Retry-After`;
- testar o cronograma das cinco novas tentativas;
- testar falhas independentes de Teams e e-mail;
- medir tempo e memória para lotes de 500 eventos;
- criar roteiro para o usuário realizar o teste controlado no ambiente corporativo;
- criar verificações automatizadas para reduzir o risco de segredos em logs e
  relatórios;
- analisar somente resultados e logs sanitizados devolvidos pelo usuário;
- corrigir falhas de código identificadas durante a homologação conduzida pelo
  usuário.

Resultado: testes automatizados aprovados localmente e roteiro de homologação pronto.
A confirmação no ambiente corporativo será feita pelo usuário.

## 6. Critérios de aceite da entrega do agente

- implementar o processamento contínuo sobre `ForwardedEvents` no Rigel;
- utilizar lotes de até 500 eventos e checkpoint persistente;
- reconhecer corretamente os seis IDs suportados;
- alertar somente para os grupos monitorados;
- resolver o usuário pelo `MemberSid` ou apresentar o SID como alternativa;
- não repetir alertas do mesmo evento;
- retomar corretamente após reinicialização;
- enviar Teams e e-mail de maneira independente;
- aplicar a política definida de novas tentativas;
- separar eventos inválidos e erros permanentes;
- medir localmente o fluxo e fornecer ao usuário meios de validar a meta aproximada
  de 30 segundos no ambiente real;
- manter credenciais e tokens fora do código e dos logs;
- possuir testes automatizados aprovados e instruções operacionais atualizadas;
- não conter credenciais, endereços sensíveis ou dados corporativos reais;
- permitir que todas as integrações externas sejam substituídas por fakes nos testes.

## 7. Ações fora da responsabilidade do agente

- acessar ou alterar qualquer servidor corporativo;
- instalar ou iniciar serviços nos Domain Controllers ou no Rigel;
- alterar regras de firewall, rede, certificados ou políticas do domínio;
- criar contas ou conceder permissões no Active Directory e Microsoft 365;
- inserir, testar ou armazenar credenciais reais;
- executar envios reais para Teams ou e-mail;
- homologar sozinho o funcionamento no ambiente corporativo;
- configurar WinRM, assinaturas ou encaminhamento de eventos;
- interface gráfica própria;
- alteração automática de usuários ou grupos;
- reversão automática de alterações suspeitas;
- armazenamento de todos os eventos do canal configurado;
- alta disponibilidade com múltiplos workers;
- substituição das ferramentas corporativas de monitoramento.

## 8. Insumos necessários do usuário

- exemplos reais e anonimizados dos eventos recebidos no Rigel;
- confirmação de que os eventos dos três DCs chegam ao Rigel;
- permissão de leitura da conta de execução sobre `ForwardedEvents`;
- módulo ActiveDirectory, conectividade ADWS e conta de serviço somente leitura
  ou gMSA para o worker;
- conta de execução no Rigel;
- credenciais e consentimentos do Microsoft Graph;
- remetente e destinatários de homologação;
- `chat_id` e conta delegada do Teams;
- diretórios protegidos para SQLite, logs e cache de autenticação;
- aprovação da retenção e do procedimento de suporte.

## 9. Complexidade relativa do desenvolvimento

| Etapa | Complexidade | Principal motivo |
|---|---:|---|
| Preparação de instruções | Baixa/Média | Depende dos formatos informados pelo usuário |
| Contratos e configuração | Média | Define as interfaces usadas por toda a solução |
| Fonte local do Rigel | Média/Alta | Checkpoint, rotação do log e API do Windows Event Log |
| Parsing e regras | Baixa/Média | Núcleo existente já cobre boa parte |
| Resolução ADWS | Média | Identidade do worker, PowerShell e tipos de objetos |
| Persistência | Alta | Migração e consistência após falhas |
| Worker principal | Alta | Orquestração, recuperação e ausência de duplicidade |
| Notificações e retentativas | Média/Alta | Agendamento e estados independentes |
| Ocorrências operacionais | Média | Modelagem e proteção de dados |
| Operação e segurança | Média/Alta | Código defensivo e instruções sem acesso real |
| Testes automatizados | Alta | Abrange falhas, reinícios e integrações simuladas |

## 10. Ordem recomendada de desenvolvimento pelo agente

1. Receber amostras anonimizadas diretamente de `ForwardedEvents`.
2. Fechar contratos, configurações e modelo de dados.
3. Implementar persistência e migrações.
4. Implementar e testar a fonte local incremental do Rigel.
5. Implementar a resolução local por PowerShell/ADWS.
6. Construir o worker e recuperação após falhas.
7. Integrar notificações e política de retentativas.
8. Implementar ocorrências, logs e retenção.
9. Executar testes automatizados completos e entregar instruções para o usuário
   instalar e homologar no Rigel.

## 11. Definição de pronto

A entrega do agente será considerada pronta quando:

- todo o código previsto estiver implementado no repositório;
- os testes automatizados forem executados com sucesso;
- integrações externas tiverem testes com mocks ou fakes;
- arquivos de exemplo não contiverem valores sensíveis;
- migrações e rotinas de recuperação estiverem testadas;
- instruções de instalação, configuração e homologação estiverem disponíveis;
- limitações que só podem ser validadas no ambiente corporativo estiverem claramente
  identificadas para o usuário.

O funcionamento real será confirmado posteriormente pelo usuário ao executar as
instruções nos servidores e informar resultados sanitizados para eventuais correções.

