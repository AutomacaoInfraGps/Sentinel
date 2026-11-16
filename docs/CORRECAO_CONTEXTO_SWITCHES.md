# Contexto Flask no job de verificacao de switches

## Problema informado

Em 16/11/2026, ao verificar switches pela tela, o operador recebeu
"Working outside of application context". O backup anterior a carga SQL foi
criado, mas a migracao 004 e a carga de switches ainda nao foram confirmadas.
Este erro deve ser homologado antes de continuar a migracao.

## Defeito identificado e correcao

Os endpoints assincronos usam _start_background_job para executar
_run_switches_job em outra thread. Esse job chama _publicar_switches_atualizados,
que monta/publica o mapa e pode usar current_app. A thread nao herda o contexto
Flask da requisicao. O codigo anterior nao criava um contexto para esse caminho.

_run_switches_job agora abre app.app_context() durante toda a execucao e delega
ao corpo _execute_switches_job. A inicializacao de GerenciadorSwitches tambem
fica dentro do try para registrar falhas no job em vez de abandonar a thread.
O helper generico de jobs nao foi alterado; a correcao fica nos jobs de switches
geral, individual, regional e recarga. Nao muda coleta, autenticacao, escopo AD,
rotas, polling, interface, SQL ou firmware de equipamentos.

Nao se cria contexto de requisicao nem se copia sessao/login para o worker.
O app_context serve para config/logger e recursos da aplicacao, nao e autorizacao.
Referencia: https://flask.palletsprojects.com/en/stable/appcontext/

## Testes e homologacao

tests/unit/switch_background_context_test.py executa as funcoes reais extraidas
do modulo em threads, com Flask real e coletores/publicacao simulados. Verifica
os quatro modos, disponibilidade de current_app, ausencia de request context,
liberacao do contexto, falha de inicializacao/autenticacao/publicacao e erro de
regional. Nao acessa rede nem cofre de producao.

Os testes amplos que importam web_config completo podem nao carregar neste
ambiente local por credenciais DPAPI indisponiveis e erro de console durante o
diagnostico dessa indisponibilidade. Nao alterar cofre/permissoes ou codigo de
outros coletores para contornar isso. A verificacao real no Rigel e necessaria.

Depois de commit/push e pull: reiniciar pelo restart_web_service.ps1, conferir
HTTP 200 em /healthz e testar "Verificar switches". Se falhar, obter traceback
do job nos logs antes de inferir outra causa. O erro de contexto nao depende da
tabela SQL de switches, que ainda nao foi criada nesta etapa.

O backup informado foi
E:\Sentinel\PostgreSQL\backups\sentinel-antes-switches-20261116-111727-258.dump
(24525 bytes). Leitura do catalogo nao substitui teste de restauracao.
