# Preparação da integração com o Sentinel

Atualizado em **02/10/2026**.

## Objetivo

Incorporar o núcleo homologado do AlertAD à operação do Sentinel, validar Teams
e e-mail em homologação, decidir depois se haverá interface web e somente então
preparar a entrada em produção.

O `ESCOPO_V1.md` continua sendo a fonte de verdade do núcleo. Este documento
trata apenas da fase posterior de integração.

## Evidências disponíveis

- coleta contínua do `ForwardedEvents` local no Rigel;
- execução pela conta de serviço utilizada pelo Sentinel;
- 28 eventos relevantes persistidos e mensagens conferidas;
- checkpoint real avançado até a sequência lógica 50203;
- schema SQLite 5, sem falhas, entregas pendentes ou ocorrências abertas;
- resolução assistida de `MemberSid` por PowerShell/ADWS aprovada;
- 171 testes automatizados aprovados antes da homologação;
- nenhum envio real por Teams ou e-mail realizado nesta fase.

Os números acima são evidências operacionais sanitizadas. Banco, XMLs e logs
reais não devem ser copiados para o Git ou para ambientes de desenvolvimento.

## Leitura técnica do Sentinel atual

- a raiz do repositório continua sendo a fonte operacional da aplicação Flask;
- novos serviços reutilizáveis devem entrar em `services/`;
- o Sentinel já possui configuração Graph com tenant, aplicação, segredo,
  remetente e cache fora do Git;
- o envio de e-mail existente suporta Microsoft Graph;
- não foi encontrado emissor ativo de mensagens para chat do Teams;
- o centro de notificações web trabalha com snapshots operacionais e estado de
  leitura por usuário, não com a fila transacional do AlertAD.

Nenhum valor de credencial foi lido ou registrado durante essa análise.

## Arquitetura recomendada — decisão pendente de aprovação

Adicionar o AlertAD como um serviço independente em `services/alertad_v1/` no
repositório do Sentinel, preservando:

- processo próprio;
- lock de instância próprio;
- SQLite próprio em armazenamento local;
- checkpoint e deduplicação próprios;
- ciclo de entrega independente do Flask/Waitress;
- mesma conta de serviço aprovada no Rigel.

O Sentinel passa a ser o repositório, instalador e ponto operacional comum, mas
o worker não é iniciado como thread de `web_config.py`. Reinícios da interface
web não podem interromper coleta ou entrega.

Se um front for aprovado depois, ele consumirá um contrato de leitura
sanitizado. Ele não abrirá transações de escrita no SQLite do AlertAD e não
despachará notificações.

### Alternativas não recomendadas

1. **Thread dentro do Flask:** mistura ciclos de vida, pode criar instâncias
   concorrentes e atrela coleta aos reinícios do site.
2. **Sentinel escrevendo diretamente no SQLite:** cria dois proprietários para
   checkpoint, ocorrências e entregas.
3. **Reimplementar retentativas no Sentinel:** perde as garantias já testadas de
   atomicidade, `Retry-After`, estados por canal e recuperação após crash.

## Responsabilidades

### AlertAD

- ler somente `ForwardedEvents` local;
- analisar, filtrar, enriquecer e deduplicar eventos;
- persistir checkpoint, snapshots, ocorrências e entregas;
- enviar Teams/e-mail e controlar retentativas;
- expor diagnóstico sanitizado e, se necessário, uma leitura futura para o front.

### Sentinel

- empacotar e iniciar o serviço AlertAD;
- fornecer caminhos e configuração externa autorizada;
- manter a identidade de execução;
- incluir saúde e ocorrências no front apenas se essa etapa for aprovada;
- não administrar WEF, WinRM ou Domain Controllers por meio do AlertAD.

## Configuração e segredos

O arquivo `environment.json` do Sentinel continua fora do Git. A integração
deve mapear os valores em memória, sem criar uma segunda cópia versionada:

| Sentinel | AlertAD | Uso |
|---|---|---|
| `microsoft_graph.tenant_id` | `M365_TENANT_ID` | autenticação Graph |
| `microsoft_graph.client_id` | `M365_CLIENT_ID` | e-mail por aplicação |
| `microsoft_graph.client_secret` | `M365_CLIENT_SECRET` | e-mail por aplicação |
| `microsoft_graph.sender_upn` | `M365_SENDER_UPN` | remetente autorizado |

Ainda precisam ser definidos externamente:

- destinatários de homologação do AlertAD;
- aplicação/cliente delegado permitido para `ChatMessage.Send`;
- conta delegada do Teams;
- chat de homologação;
- caminho protegido do cache delegado.

O ID do chat, destinatários, tokens, segredos e UPNs reais não entram no código,
nos testes ou neste documento.

## Fases e gates

### Fase 1 — integrar o núcleo

1. Aprovar a arquitetura de serviço independente. **Aprovado em 02/10/2026.**
2. Disponibilizar contrato SQLite estritamente somente leitura e sanitizado para
   o sino administrativo. **Implementado no AlertAD; integração pendente.**
3. Criar `services/alertad_v1/` no Sentinel e incorporar o pacote preservando o
   histórico do projeto de origem.
4. Criar launcher do Sentinel sem duplicar regras do worker.
5. Definir caminhos separados para HML e produção.
6. Executar a suíte AlertAD dentro do ambiente do Sentinel.
7. Repetir somente `diagnose` e uma coleta controlada no Rigel.

**Gate:** mesmo resultado funcional da HML atual, sem Graph e sem regressões.

### Fase 2 — Teams e e-mail

1. Testar cada canal isoladamente com destino de homologação.
2. Usar mensagem sintética sem dados corporativos no primeiro envio.
3. Confirmar permissões, remetente/conta e destino.
4. Executar um evento real autorizado com os dois canais ativos.
5. Confirmar estados independentes, falha permanente, falha temporária e
   `Retry-After` por mocks; não provocar falhas reais desnecessárias.

**Gate:** entrega controlada confirmada e nenhuma credencial em logs.

### Fase 3 — sino obrigatório e página completa opcional

O sino administrativo faz parte da integração aprovada. Ele reutilizará o
estado individual de leitura do Sentinel e será protegido no backend por
`can_operate_sentinel`; ocultar apenas o componente visual não é autorização.

A decisão pendente se limita a uma página completa. Ela deve considerar se os
operadores precisam visualizar no Sentinel:

- saúde do worker e idade do último checkpoint;
- ocorrências abertas;
- entregas pendentes ou permanentemente falhas;
- histórico resumido de alertas.

Se esses dados não forem necessários para operação diária, o sino será o único
front da v1. Se forem necessários, serão adicionadas rotas somente leitura
protegidas pelas mesmas permissões administrativas do Sentinel.

### Fase 4 — produção

1. Separar banco, logs, configuração, cache e destinos de HML/produção.
2. Validar ACLs e backup sem copiar segredos.
3. Definir retenção somente após medir a janela real de replay.
4. Executar implantação controlada com rollback para o serviço HML.
5. Obter aceite dos responsáveis por AD, Sentinel e Microsoft Graph.

## Decisões necessárias antes de alterar o Sentinel

1. Aprovar o modelo de serviço independente em `services/alertad_v1/`.
2. Aprovar o reaproveitamento da aplicação Graph atual para o e-mail.
3. Definir se o Teams usará uma aplicação delegada existente ou dedicada.
4. Informar apenas no ambiente corporativo os destinos de homologação.

Essas decisões não exigem compartilhar valores sensíveis com o agente.
