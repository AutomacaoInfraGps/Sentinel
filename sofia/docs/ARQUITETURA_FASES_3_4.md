# Arquitetura Segura da SofIA - Fases 3 e 4

## Status do documento

Este documento substitui a proposta preliminar de evolução da SofIA para uso de
LLM, n8n, WhatsApp e execução de ações reais.

Ele descreve a arquitetura pretendida. Os componentes aqui mencionados não
devem ser considerados liberados enquanto os respectivos critérios de aceite
não forem implementados, testados e aprovados.

## Objetivo

Evoluir a SofIA sem transferir autoridade para a inteligência artificial ou
para o orquestrador de integrações.

A LLM poderá interpretar linguagem natural e sugerir uma intenção estruturada.
Somente o Sentinel poderá:

- identificar e autenticar o solicitante;
- calcular seu escopo no Active Directory;
- autorizar uma ação;
- criar uma solicitação pendente;
- validar a confirmação humana;
- acionar um executor técnico;
- registrar o resultado na auditoria.

## Princípio fundamental

```text
LLM interpreta, mas não autoriza.
n8n transporta e orquestra, mas não decide.
Sentinel autentica, valida e autoriza.
Executor realiza somente ações previamente autorizadas.
Auditoria registra todas as etapas.
```

Nenhuma resposta da LLM, mensagem do WhatsApp, variável do n8n ou dado enviado
pelo navegador deve ser tratado como prova de identidade ou autorização.

## Estado atual

A implementação atual permanece como MVP determinístico e somente leitura:

- usa a sessão autenticada do Flask;
- preserva `username`, `dn` e grupos do AD;
- aplica RBAC e escopo regional no backend;
- possui rate limit e limite de tamanho de mensagem;
- aceita apenas ferramentas explicitamente habilitadas;
- registra metadados de uso em `logs/sofia_audit.jsonl`;
- não executa alterações no AD ou na infraestrutura.

Esse comportamento deve continuar sendo o padrão enquanto as novas etapas são
desenvolvidas.

## Zonas de confiança

Os componentes devem ser tratados como zonas independentes:

1. **Usuário e canal:** widget do Sentinel ou WhatsApp.
2. **n8n:** transporte e coordenação de integrações.
3. **LLM:** interpretação não confiável de linguagem natural.
4. **Sentinel:** autoridade de identidade, RBAC, confirmação e política.
5. **Executor:** processo isolado com a credencial técnica mínima.
6. **Sistemas-alvo:** AD, Zabbix, FortiManager e demais integrações.
7. **Auditoria:** registro protegido e independente da execução.

O comprometimento de uma zona não deve conceder automaticamente acesso à zona
seguinte.

## Arquitetura proposta

```text
Widget autenticado ─────────────────────────┐
                                            │
WhatsApp -> Cloudflare -> webhook do n8n ───┼──> API interna do Sentinel
                                            │              │
                                            │              v
                                            └─> LLM -> intenção estruturada
                                                           │
                                                           v
                                                validação + RBAC + escopo
                                                           │
                                                           v
                                                operação pendente/confirmada
                                                           │
                                                           v
                                                    executor isolado
                                                           │
                                                           v
                                            AD / Zabbix / FortiManager
```

### Widget do Sentinel

O widget continuará chamando o Sentinel diretamente com a sessão Flask do
usuário. O cookie de sessão não deve ser encaminhado nem armazenado no n8n.

Quando houver LLM, o Sentinel poderá solicitar ao n8n apenas a interpretação da
mensagem. A resposta retornada será tratada como entrada não confiável e
validada contra um schema fechado.

### n8n

O n8n será o orquestrador das integrações, não o guardião da autorização.

Responsabilidades permitidas:

- receber eventos de canais externos;
- validar requisitos básicos do webhook;
- encaminhar conteúdo mínimo para a LLM;
- devolver uma intenção estruturada ao Sentinel;
- transportar respostas entre Sentinel e canal;
- controlar tentativas, timeout e disponibilidade do fluxo.

Responsabilidades proibidas:

- usar ou copiar cookies de sessão do Sentinel;
- decidir se um usuário pode executar uma ação;
- consultar diretamente grupos do AD para autorizar ações;
- armazenar a senha de um usuário final;
- possuir a credencial capaz de alterar o AD;
- executar `tools_sentinel.py` diretamente;
- alterar o alvo definido em uma operação já confirmada.

### LLM

A saída da LLM deverá seguir um contrato estruturado, por exemplo:

```json
{
  "intent": "ad.password.reset",
  "entities": {
    "user_hint": "Pedro",
    "regional_hint": "RJ"
  },
  "confidence": 0.91
}
```

Esse resultado não é autorização e não identifica definitivamente o alvo. O
Sentinel deverá validar:

- se a intenção existe em `permissions_matrix.json`;
- se os campos permitidos estão presentes;
- se não existem campos ou comandos adicionais;
- se a ação está habilitada no ambiente;
- se o alvo foi resolvido sem ambiguidade;
- se o usuário possui escopo sobre o alvo.

Dados enviados à LLM devem ser minimizados e redigidos. Senhas, tokens, cookies,
credenciais, inventários completos, grupos privilegiados e conteúdo de logs
sensíveis não devem ser enviados. Antes da escolha do provedor, devem ser
avaliados retenção, uso para treinamento, localização dos dados e contrato
corporativo. Um modelo local continua sendo uma opção quando o dado não puder
sair da rede.

## Identidades

### Usuário do widget

A identidade é a sessão Flask criada pelo login no AD. Toda autorização deve
ser recalculada no backend e nunca derivada de dados enviados pelo JavaScript.

### Serviço n8n

O n8n terá uma identidade própria de máquina, usada apenas para autenticar o
canal entre n8n e Sentinel. Essa identidade prova que a chamada veio do n8n,
mas não representa o usuário humano.

Requisitos:

- credencial exclusiva e rotacionável;
- armazenamento fora do workflow exportado;
- escopo somente para os endpoints necessários;
- expiração e revogação;
- proteção contra replay;
- restrição de rede ao host do n8n;
- TLS também no tráfego interno quando tecnicamente possível.

### Usuário do WhatsApp

O número do telefone, isoladamente, não será considerado identidade suficiente
para ações administrativas.

O vínculo deverá seguir este processo:

1. O usuário entra no Sentinel com sua conta do AD.
2. Solicita a vinculação de um número de WhatsApp.
3. O Sentinel gera um código aleatório, de uso único e curta duração.
4. O código é enviado pelo usuário no canal do WhatsApp.
5. O Sentinel associa o telefone ao SID ou GUID do usuário no AD.
6. A associação é auditada, revisável e revogável.

Na primeira etapa, o WhatsApp será somente leitura. Ações de escrita exigirão
autenticação reforçada e poderão exigir confirmação dentro do Sentinel.

## Autorização e matriz de permissões

O `permissions.py` continuará sendo a fronteira obrigatória. A matriz deverá
definir, para cada ação:

- identificador estável;
- estado: desabilitada, piloto ou produção;
- nível de risco;
- grupos humanos autorizados;
- escopos regionais e OUs permitidas;
- canal permitido;
- necessidade de confirmação;
- necessidade de segunda aprovação;
- executor técnico permitido;
- parâmetros aceitos;
- timeout e política de repetição.

Classificação inicial recomendada:

| Ação | Risco | Regra inicial |
| --- | --- | --- |
| Consulta de status | Baixo | Automática após RBAC |
| Consulta de usuário no AD | Baixo | Somente leitura e escopo por OU |
| Desbloqueio de conta | Médio | Confirmação de uso único |
| Reset de senha | Alto | Confirmação reforçada e piloto controlado |
| Alteração de grupo | Alto | Segunda aprovação |
| Exclusão de usuário ou host | Crítico | Bloqueada inicialmente |
| Comando arbitrário | Crítico | Permanentemente proibido |

## Confirmação humana

Uma resposta textual como "sim" não poderá executar diretamente uma ação.

O Sentinel criará uma operação pendente contendo:

- `operation_id` aleatório;
- `correlation_id` para auditoria;
- solicitante autenticado;
- canal de origem;
- ação normalizada;
- alvo resolvido por identificador imutável;
- resumo exibido ao usuário;
- parâmetros sem segredos;
- horário de criação e expiração;
- estado atual;
- política de aprovação aplicável.

A confirmação deverá ser:

- de uso único;
- vinculada ao mesmo usuário e canal;
- válida por poucos minutos;
- inválida após qualquer alteração dos parâmetros;
- protegida contra repetição;
- novamente submetida a RBAC e validação de escopo antes da execução.

Estados mínimos:

```text
recebida -> interpretada -> validada -> pendente
pendente -> confirmada -> executando -> concluída
pendente -> expirada/cancelada
executando -> falhou
```

Cada transição inválida deverá ser recusada.

## Executor de ações

O executor será separado do n8n e aceitará apenas comandos estruturados já
autorizados pelo Sentinel.

Ele não aceitará:

- texto livre;
- scripts enviados pelo usuário;
- comandos PowerShell montados por concatenação;
- nomes ambíguos como identificador final;
- parâmetros fora da allowlist;
- operação sem `operation_id` confirmado.

O executor deverá ser idempotente sempre que possível. Uma repetição da mesma
operação não poderá aplicar a ação duas vezes silenciosamente.

## Active Directory

### Conta técnica

A preferência é utilizar uma gMSA quando a versão do domínio, o host executor e
o modelo de implantação permitirem. Caso seja necessária uma conta tradicional
como `svc_sofia`, ela deverá ter senha gerenciada e rotacionada fora do código.

Em ambos os casos:

- nunca pertencer a Domain Admins, Enterprise Admins ou grupos equivalentes;
- não permitir login interativo;
- não permitir RDP;
- executar somente no host autorizado;
- receber delegação mínima por OU;
- ter proprietário, finalidade e revisão periódica documentados;
- ser monitorada para uso fora do padrão.

### Delegação

A delegação deverá ser feita nas OUs exatas e apenas para as tarefas aprovadas.
Reset de senha não implica permissão para criar, excluir ou mover usuários.
Movimentação de computadores, alteração de grupos e desbloqueio devem possuir
delegações independentes.

### Controladores de domínio

As escritas serão permitidas somente em controladores graváveis aprovados:

- `sirius` e `shaula`, em São Paulo;
- `mintaka`, no Rio de Janeiro.

Os RODCs permanecerão fora da lista de escrita. O código usará allowlist de DCs,
timeout e failover controlado. Uma indisponibilidade não autoriza escolher um
servidor diferente da allowlist.

### Resolução do alvo

O nome digitado pelo usuário será apenas uma pista de busca. Antes da
confirmação, o Sentinel deverá:

1. localizar candidatos;
2. exigir seleção quando houver ambiguidade;
3. resolver SID, GUID e DN;
4. validar a OU e a regional;
5. salvar o identificador imutável na operação pendente;
6. repetir a validação imediatamente antes da execução.

## Fluxo seguro de reset de senha

1. O usuário solicita o reset pelo widget ou canal autorizado.
2. A LLM devolve somente a intenção e as pistas de entidade.
3. O Sentinel localiza o usuário do AD em modo somente leitura.
4. Em caso de múltiplos resultados, nenhuma operação é criada até a seleção.
5. O Sentinel valida grupo, regional, OU, canal e política de risco.
6. É criada uma operação pendente com expiração curta.
7. O usuário recebe um resumo sem senha: conta, nome, OU e ação.
8. A confirmação é enviada com o `operation_id` de uso único.
9. O Sentinel recalcula RBAC, relê o objeto no AD e valida novamente sua OU.
10. O executor usa a conta técnica delegada no DC gravável permitido.
11. A senha temporária é gerada criptograficamente no executor.
12. A conta é configurada para troca de senha no próximo logon, conforme a política.
13. A senha nunca passa pela LLM, n8n, WhatsApp ou auditoria.
14. O resultado e todas as transições são auditados.

A forma segura de entregar uma senha temporária ainda deverá ser aprovada. Até
essa definição, reset de senha permanecerá desabilitado. Desbloqueio de conta é
o candidato preferencial para a primeira ação piloto.

## n8n em produção

O n8n será instalado em Docker no Rigel ou em VM dedicada, após validação de
capacidade e segregação.

Controles mínimos:

- imagem fixada por versão, sem uso de `latest`;
- banco PostgreSQL persistente;
- chave de criptografia exclusiva e protegida;
- volumes e backups criptografados;
- painel administrativo acessível somente pela LAN administrativa;
- autenticação forte e MFA quando disponível;
- API administrativa desabilitada quando não utilizada;
- nenhum acesso ao Docker socket do host;
- bloqueio de nós de shell, filesystem e código desnecessários;
- proibição de community nodes sem avaliação;
- workflows de desenvolvimento e produção separados;
- retenção limitada de entradas e saídas das execuções;
- atualização periódica com teste prévio;
- execução regular do `n8n audit`;
- monitoramento de webhooks desprotegidos e workflows alterados.

O n8n não armazenará credenciais do AD capazes de executar alterações.

## Cloudflare Tunnel e WhatsApp

O `cloudflared` criará conexão de saída, sem abertura de porta de entrada no
FortiGate. Isso reduz a superfície, mas não torna o webhook privado.

Requisitos:

- hostname exclusivo para integração;
- publicação somente da rota do webhook;
- painel do n8n não publicado no mesmo hostname;
- validação criptográfica da assinatura do provedor do WhatsApp;
- rejeição por timestamp e replay quando suportado;
- WAF e rate limiting;
- limite de tamanho do corpo;
- métodos HTTP restritos;
- logs sem conteúdo sensível;
- token do túnel armazenado como segredo e rotacionado;
- processo documentado de revogação emergencial.

Cloudflare Access poderá proteger interfaces humanas futuras. Webhooks de
provedores externos precisarão de uma política compatível com chamadas de
máquina e continuarão dependendo da validação feita pela aplicação.

## Auditoria

O arquivo `logs/sofia_audit.jsonl` continuará útil durante o desenvolvimento,
mas não será chamado de imutável. Um arquivo local pode ser modificado por uma
conta com acesso ao servidor.

Cada ação real deverá registrar, no mínimo:

- `correlation_id` e `operation_id`;
- usuário solicitante e seu SID;
- canal e endereço de origem;
- intenção original normalizada;
- ação autorizada;
- alvo por GUID/SID e DN;
- grupo e regra que concederam acesso;
- quem confirmou e quem aprovou;
- executor e DC utilizado;
- horários de todas as transições;
- resultado e código de erro sanitizado;
- valores anteriores e posteriores quando não forem secretos.

Nunca registrar:

- senha atual ou temporária;
- cookie de sessão;
- token do n8n, Cloudflare ou provedor;
- credencial da conta técnica;
- prompt completo quando contiver informação sensível.

Para produção, a trilha deverá ser copiada para um destino protegido e separado,
como Windows Event Log, syslog/SIEM ou banco append-only com ACL própria. Pode
ser adicionada uma cadeia de hashes para evidenciar alterações, mas ela não
substitui armazenamento externo protegido.

## Comportamento em falhas

O sistema deverá falhar de forma fechada:

- LLM indisponível: não executar ação;
- resposta fora do schema: rejeitar;
- identidade não vinculada: permitir somente orientação pública;
- AD indisponível: não usar dados antigos para escrever;
- permissão incerta: negar;
- alvo ambíguo: exigir seleção;
- operação expirada: criar uma nova solicitação;
- auditoria indisponível: não executar ação de escrita;
- executor sem confirmação do resultado: marcar como indeterminado e investigar,
  sem repetir automaticamente.

## Fases de implantação

### Fase A - Fundação

- Definir contratos de intenção e ação.
- Expandir `permissions_matrix.json` sem habilitar escrita.
- Implementar operações pendentes e máquina de estados.
- Criar autenticação de serviço entre n8n e Sentinel.
- Evoluir auditoria e correlação.
- Criar ambiente de testes isolado.

### Fase B - LLM somente leitura

- Integrar a LLM ao widget.
- Aplicar schema fechado e validação de saída.
- Minimizar dados enviados.
- Executar apenas tools read-only já autorizadas.
- Testar prompt injection, vazamento e alucinação.

### Fase C - n8n e WhatsApp somente leitura

- Implantar n8n endurecido.
- Publicar somente o webhook pelo Tunnel.
- Validar assinatura do provedor.
- Implementar vínculo WhatsApp-AD.
- Limitar consultas ao mesmo escopo do Sentinel.

### Fase D - Primeira ação controlada

- Criar executor isolado.
- Configurar conta técnica e delegação em OU de laboratório.
- Implementar confirmação de uso único.
- Pilotar desbloqueio de conta com usuários fictícios.
- Executar testes de abuso, replay, concorrência e indisponibilidade.

### Fase E - Reset de senha

- Aprovar canal de entrega da senha temporária.
- Implementar geração e descarte seguro.
- Exigir autenticação reforçada.
- Liberar inicialmente para uma OU piloto.
- Revisar auditoria e incidentes antes da expansão.

### Fase F - Outras automações

Cada nova ação de Zabbix, FortiManager, servidores ou AD deverá passar pelo mesmo
processo de modelagem de risco, autorização, confirmação, execução isolada,
auditoria e piloto.

## Critérios para liberar uma ação de escrita

Uma ação somente poderá ser habilitada quando todos os itens forem verdadeiros:

- [ ] ação cadastrada e desabilitada por padrão na matriz;
- [ ] parâmetros definidos por schema fechado;
- [ ] RBAC e escopo testados no backend;
- [ ] alvo resolvido por identificador imutável;
- [ ] confirmação de uso único implementada;
- [ ] executor não aceita texto livre;
- [ ] conta técnica sem privilégios excedentes;
- [ ] OU piloto configurada;
- [ ] auditoria externa disponível;
- [ ] segredos ausentes de logs e respostas;
- [ ] testes de negação, replay e concorrência aprovados;
- [ ] procedimento de rollback e resposta a incidente documentado;
- [ ] aprovação dos responsáveis técnicos registrada.

## Responsabilidades de alinhamento

- **Active Directory:** Felipe, para conta técnica, gMSA quando possível,
  delegação mínima, OUs piloto e DCs graváveis.
- **Rede e Cloudflare:** João e Michel, para Tunnel, DNS, WAF, restrição de rota,
  monitoramento e revogação.
- **Sentinel/SofIA:** desenvolvimento dos contratos, RBAC, confirmação, executor,
  auditoria e testes.
- **Segurança/Gestão:** aprovação do provedor LLM, tratamento de dados, canais de
  confirmação e critérios de produção.

## Fora do escopo inicial

- autonomia da LLM;
- comandos arbitrários;
- execução direta pelo n8n;
- acesso do n8n à credencial de escrita do AD;
- reset de senha inteiramente pelo WhatsApp;
- exposição pública do painel n8n ou do Sentinel;
- alteração de grupos privilegiados;
- exclusão automática de usuários, computadores ou dispositivos;
- uso de Domain Admin como conta de serviço.

## Referências oficiais

- Microsoft - Delegation of Control in AD DS:
  https://learn.microsoft.com/en-us/windows-server/identity/ad-ds/manage/delegation-control-wizard
- Microsoft - Service Accounts in Windows Server:
  https://learn.microsoft.com/windows/security/identity-protection/access-control/service-accounts
- Cloudflare - Cloudflare Tunnel:
  https://developers.cloudflare.com/tunnel/
- Cloudflare - Tunnel tokens:
  https://developers.cloudflare.com/tunnel/reference/tunnel-tokens/
- n8n - Security audit:
  https://docs.n8n.io/hosting/securing/security-audit/

