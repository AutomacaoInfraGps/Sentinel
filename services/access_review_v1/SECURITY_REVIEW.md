# Revisao de seguranca — 2026-10-20

Escopo: fronteira entre Sentinel e Revisao de Acessos, os coletores incorporados e os dados operacionais do modulo. A revisao foi feita sobre codigo, testes e exemplos sem segredos. Credenciais preenchidas, cofre, bancos e logs operacionais nao foram abertos. A revisao nao e uma auditoria completa de todos os modulos preexistentes do Sentinel.

## Correcoes realizadas

| Ponto encontrado | Correcao |
| --- | --- |
| Proprietario de um job que perdeu permissao de operador ainda podia consulta-lo | Jobs da Revisao de Acessos exigem operador na consulta atual, independentemente da autoria |
| Resposta do job carregava campos internos desnecessarios | Resposta seleciona explicitamente estado, mensagens, identificadores e eventos amigaveis |
| Os tres coletores web ignoravam certificados HTTPS automaticamente | Validacao TLS ativa por padrao; excecao somente por configuracao local explicita |
| Credenciais de auditoria usavam um ENV em texto simples | Manifesto `credential_ref` resolvido pelo mesmo cofre DPAPI CurrentUser do Sentinel; ENV deixou de ser lido |
| Processo filho herdava todas as variaveis do Sentinel | Lista permitida de variaveis de sistema e contexto interno; segredos de outros modulos nao sao repassados |
| Limite de fila podia ser excedido entre processos | Contagem e insercao atomicas sob `BEGIN IMMEDIATE` no SQLite |
| Timeout/parada poderia deixar descendentes com janelas de captura | Job Object Windows com encerramento dos descendentes no fechamento do handle; testes reais com processos sinteticos |
| Diagnosticos web armazenavam excecao bruta e URL da pagina | Mensagem fixa, etapa e tipo da excecao, sem call log do navegador ou URL com possiveis parametros sensiveis |
| API aceitava corpo/itens adicionais desnecessarios | Limite de 8 KiB, campos permitidos e no maximo quatro areas |
| Limpeza poderia seguir diretorio de evidencias redirecionado para fora da instancia | Limpeza verifica contencao do diretorio resolvido e de cada arquivo |
| Progresso detalhado poderia incentivar a exposicao da saida bruta dos bots | Canal temporario aceita apenas etapa predefinida, percentual e contadores; mensagens exibidas sao mapeadas pelo Sentinel |
| Nova geracao poderia misturar capturas de execucoes diferentes | Recuperacao exige origem UUID, comprovacao de coleta concluida, insumos por execucao e SHA-256 validado antes da fila e novamente no worker; usa diretorio de trabalho isolado, sem credenciais |

## Controles preservados

- Login, grupos de operadores e CSRF seguem os controles existentes de `security_hardening.py` e `enforce_operation_permissions`.
- O modulo nao recebe excecao de login/CSRF como servico interno.
- Cabecalhos de seguranca e `Cache-Control: no-store` sao aplicados pelo Sentinel.
- Comandos, caminhos de scripts e modos sao definidos pelo codigo; a API nao aceita comandos ou argumentos livres.
- O sino usa a autorizacao atual do operador. Jinja faz escape no historico e o JavaScript usa `textContent` nos eventos.
- SQL usa parametros; gravacoes da fila e resultados usam transacoes. O consumidor e serializado entre processos.
- Dados operacionais permanecem em `instance/access_review`, fora das rotas estaticas e do Git.
- `.gitignore` cobre ENV preenchido, bancos e sidecars, certificados e chaves. Nenhum desses tipos apareceu na lista de arquivos versionados conferida nesta revisao.

## Evidencias de teste

29 testes passaram na execucao conjunta:

```powershell
.\venv\Scripts\python.exe -m unittest tests.unit.access_review_runner_test tests.unit.access_review_notifications_test tests.unit.access_review_api_test tests.unit.access_review_security_test
```

Os testes HTTP exercitam as funcoes reais de rota e autorizacao extraidas do codigo, com Flask-Login e `configure_security` reais, isolando a inicializacao operacional do restante do Sentinel. Cobrem anonimato, usuario regional, perda de permissao, CSRF, cabecalhos, resposta minima, selecao, tamanho do corpo e limite de fila. Os demais testes cobrem cofre simulado, concorrencia SQLite, fila, retomada, timeout, validacao de documento, idempotencia, retencao e notificacoes. Processos Python sinteticos validaram o encerramento do processo e de um descendente pelo Windows Job Object. Nao houve coleta nos sistemas reais.

## Condicoes operacionais para homologacao

1. Cadastrar os acessos no cofre com `configure_credentials`, usando a mesma conta Windows do processo Sentinel. Nenhum segredo real foi migrado ou alterado durante a revisao. O legado `credentials.env`, se existir, precisa ser removido pela equipe apos validar o cadastro no cofre.
2. Manter contas de consulta com menor privilegio e uma sessao grafica dedicada, pois as evidencias capturam o monitor completo.
3. Restringir ACLs NTFS de configuracoes, modelos, cofre, diagnosticos, documentos e bancos. Nas tres pastas locais inspecionadas (`instance/access_review`, `credentials` e `dados`), nao apareceram permissoes Allow para Everyone, Authenticated Users ou BUILTIN Users. Isso nao certifica outros grupos ou as permissoes do servidor de destino. ACLs nao foram alteradas.
4. Usar HTTPS com cadeia corporativa confiavel. O endpoint atual do ADManager foi confirmado como HTTP e recebeu `allow_http: true` somente em sua configuracao; Linux e Firewalls permanecem com HTTP bloqueado nos exemplos. Como o login do ADManager trafega sem TLS, essa excecao exige rede interna controlada e aceitacao do responsavel pelo ambiente. `verify_tls: false` continua desabilitado.
5. Homologar login, coleta, logout, captura e validacao DOCX nas quatro areas. Os testes automaticos nao substituem essa etapa.

As correcoes e os testes fornecem evidencias para a revisao do PR. A aceitacao das condicoes do ambiente e a aprovacao final pertencem aos mantenedores do Sentinel.
