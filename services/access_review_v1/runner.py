"""Executa revisões incorporadas, valida documentos e publica no sino interno."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from datetime import datetime, timezone
from uuid import uuid4
from filelock import FileLock, Timeout
from .settings import AREAS, CODE_ROOT, DATA_ROOT, configuration_diagnostics, configuration_issues, load_settings
from .notifications import store_audit_execution
from .automation.src.validar_documentos import validate
from .process_guard import ProcessGuard
from .documents import approve_documents
from .recovery import preserve_evidence, prepare_recovery, recovery_available, clear_recovery_pngs

ALLOWED_MODES = frozenset({'completa', 'somente_montagem'})

COLLECTION_FAILURES = {
    'windows': 'Não foi possível concluir a coleta dos Servidores Windows. Confirme a sessão gráfica, RSAT/ADUC, Server Manager e as permissões de leitura.',
    'linux': 'Não foi possível concluir a coleta de Linux. Confirme a disponibilidade do Zabbix e do Grafana e os acessos cadastrados no cofre.',
    'admanager': 'Não foi possível concluir a coleta do ADManager Plus. Confirme se o serviço está acessível, a URL HTTP está correta e o acesso foi cadastrado no cofre.',
    'firewalls': 'Não foi possível concluir a coleta de Firewalls. Confirme FortiAnalyzer, FortiManager, ADOMs e os acessos cadastrados no cofre.',
}

PROGRESS_MESSAGES = {
    'windows_aborted': 'revisão AD encerrada após cinco regionais consecutivas com falha',
    'preparing': 'preparando a execução',
    'collecting': 'iniciando a coleta',
    'collected': 'coleta concluída',
    'collecting_done': 'finalizando a coleta',
    'assembling': 'montando o documento',
    'assembled': 'documento montado; iniciando validação',
    'linux_zabbix_login': 'acessando o Zabbix',
    'linux_zabbix_users': 'coletando usuários do Zabbix',
    'linux_grafana_login': 'acessando o Grafana',
    'linux_grafana_users': 'coletando usuários do Grafana',
    'linux_grafana_pages': 'capturando páginas do Grafana',
    'admanager_login': 'acessando o ADManager Plus',
    'admanager_settings': 'coletando configurações do ADManager Plus',
    'admanager_delegation': 'coletando delegações do ADManager Plus',
    'admanager_logout': 'encerrando a sessão do ADManager Plus',
    'fortianalyzer_login': 'acessando o FortiAnalyzer',
    'fortianalyzer_adom': 'coletando o ADOM do FortiAnalyzer',
    'fortimanager_login': 'acessando o FortiManager',
    'fortimanager_adom': 'coletando o ADOM do FortiManager',
    'firewall_devices': 'coletando dispositivos gerenciados',
    'windows_plan': 'preparando o plano de Servidores Windows',
    'windows_inventory': 'atualizando o inventário de Servidores Windows',
    'windows_capture': 'iniciando as capturas de Servidores Windows',
    'windows_archive': 'preparando as evidências de Servidores Windows',
    'windows_server_manager': 'capturando o Server Manager',
    'windows_aduc': 'abrindo o Active Directory Users and Computers',
    'windows_initial': 'capturando o bloco inicial do Active Directory',
    'windows_sections': 'capturando seções do Active Directory',
}


def _child_environment(root):
    # Nao repassar senhas/API keys de outros modulos para os coletores.
    allowed = {'systemroot', 'windir', 'systemdrive', 'comspec', 'path', 'pathext', 'temp', 'tmp',
               'userprofile', 'appdata', 'localappdata', 'programfiles', 'programfiles(x86)',
               'programdata', 'public', 'username', 'userdomain', 'logonserver', 'psmodulepath'}
    result = {key: value for key, value in os.environ.items() if key.casefold() in allowed}
    result.update(SENTINEL_ACCESS_REVIEW_HOME=str(root.resolve()), SENTINEL_ACCESS_REVIEW_CODE=str(CODE_ROOT),
                  SENTINEL_ACCESS_REVIEW_PYTHON=sys.executable, PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
    return result


class AccessReviewRunnerError(RuntimeError):
    pass


def cancellation_path(root, job_id):
    from uuid import UUID
    return Path(root) / 'runtime' / f'cancel-{UUID(str(job_id)).hex}.flag'


def _selected_audits(audit_ids):
    selected = list(AREAS) if audit_ids is None else audit_ids
    if not isinstance(selected, list) or not selected or any(not isinstance(a, str) or a not in AREAS for a in selected) or len(set(selected)) != len(selected):
        raise AccessReviewRunnerError('Selecione uma ou mais areas validas, sem repeticoes.')
    return selected


def _failure_message(area, mode):
    if mode == 'somente_montagem':
        return (f'Não foi possível gerar novamente o documento de {AREAS[area][0]}. '
                'As evidências podem ter sido alteradas após a verificação; execute uma revisão completa para renová-las.')
    return COLLECTION_FAILURES[area]


def _read_progress(path):
    try:
        if not path.is_file() or path.stat().st_size > 4096:
            return None
        value = json.loads(path.read_text(encoding='utf-8-sig'))
        stage = value.get('stage') if isinstance(value, dict) else None
        percent = value.get('percent') if isinstance(value, dict) else None
        if stage not in PROGRESS_MESSAGES or isinstance(percent, bool) or not isinstance(percent, int):
            return None
        result = {'stage': stage, 'percent': max(0, min(100, percent))}
        current, total = value.get('current'), value.get('total')
        if all(isinstance(item, int) and not isinstance(item, bool) for item in (current, total)) and 0 <= current <= total <= 1000:
            result.update(current=current, total=total)
        return result
    except (OSError, ValueError):
        return None


def _progress_message(value):
    message = PROGRESS_MESSAGES[value['stage']]
    if value['stage'] in {'windows_sections', 'firewall_devices'} and value.get('total'):
        message = f"{message} ({value['current']} de {value['total']})"
    return message


def _drain_details(path, offset, report, area):
    """Le somente eventos produzidos pela tentativa atual, com limites."""
    try:
        if not path.is_file() or path.stat().st_size > 2_000_000:
            return offset
        with path.open('r', encoding='utf-8') as stream:
            stream.seek(offset)
            for _ in range(500):
                line = stream.readline(4096)
                if not line:
                    break
                try:
                    item = json.loads(line)
                    stage = str(item.get('stage', ''))[:120]
                    target = str(item.get('target', ''))[:160]
                    state = item.get('status')
                    if state not in {'running', 'completed', 'warning', 'failed'}:
                        continue
                    error = str(item.get('error_type', ''))[:64]
                    message = f'{AREAS[area][0]} — {stage}'
                    if target:
                        message += f' | Alvo: {target}'
                    if error:
                        hints = {'TimeoutError': 'O elemento ou sistema não respondeu no prazo.',
                                 'ValueError': 'Os dados ou a estrutura encontrada diferem do esperado.',
                                 'PermissionError': 'A conta não possui acesso ao recurso.',
                                 'RuntimeError': 'A operação ou elemento esperado não pôde ser concluído.'}
                        message += f' | {error}: {hints.get(error, "Falha na operação; confira o alvo e a etapa.")}'
                    report(area, state, message)
                except (ValueError, TypeError, AttributeError):
                    continue
            return stream.tell()
    except OSError:
        return offset


def _wait_with_progress(process, timeout, progress_file, callback, tick=None, cancelled=None):
    if not hasattr(process, 'poll'):
        return process.wait(timeout=timeout)
    deadline = time.monotonic() + timeout
    last_value = None
    while True:
        if callable(cancelled) and cancelled():
            _terminate_tree(process)
            raise AccessReviewRunnerError('Execução interrompida pelo operador. As evidências existentes foram preservadas.')
        if callable(tick):
            tick()
        value = _read_progress(progress_file)
        if value != last_value:
            last_value = value
            if value and callable(callback):
                callback(value)
        returncode = process.poll()
        if returncode is not None:
            value = _read_progress(progress_file)
            if value != last_value and value and callable(callback):
                callback(value)
            return returncode
        if time.monotonic() >= deadline:
            raise subprocess.TimeoutExpired(getattr(process, 'args', 'access-review'), timeout)
        time.sleep(.35)


def _windows_failure_message(root, started_ns, document_created):
    result_path = root / 'dados' / 'execucoes' / 'ServidoresWindows' / 'Resultado-Teste-Completo.json'
    try:
        if result_path.stat().st_mtime_ns < started_ns:
            raise ValueError()
        result = json.loads(result_path.read_text(encoding='utf-8-sig'))
        steps = result.get('etapas') if isinstance(result, dict) else None
        failed = [name for name, state in steps.items() if isinstance(name, str) and str(state).startswith('FALHA')]
        if not failed:
            raise ValueError()
        labels = []
        if 'Server Manager' in failed:
            labels.append('Server Manager')
        if 'Bloco inicial' in failed:
            labels.append('bloco inicial do Active Directory')
        section_count = len([name for name in failed if name not in {'Server Manager', 'Bloco inicial'}])
        if section_count:
            labels.append(f'{section_count} seção(ões) do Active Directory')
        prefix = ('O documento chegou a ser montado, mas ' if document_created else '')
        return (f"{prefix}a coleta de Servidores Windows registrou falha em {', '.join(labels)}. "
                'Os últimos prints podem existir mesmo quando uma etapa anterior ficou incompleta.')
    except (OSError, TypeError, ValueError):
        return COLLECTION_FAILURES['windows']


def runner_status(*, root=DATA_ROOT, selected=None, mode='completa'):
    diagnostics = configuration_diagnostics(root, selected, mode)
    issues = [f"{item['message']} {item['action']}" for item in diagnostics]
    return {'configured': not issues, 'available': not issues, 'issues': issues,
            'diagnostics': diagnostics,
            'message': ('Revisão de Acessos pronta para executar.' if not issues else
                        'Há pendências nas revisões selecionadas. Abra a ajuda para saber como resolver.')}


def _terminate_tree(process):
    if os.name == 'nt':
        subprocess.run(['taskkill.exe', '/PID', str(process.pid), '/T', '/F'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    else:
        process.kill()
    process.wait(timeout=15)


def run_access_review(mode, *, audit_ids=None, progress=None, event=None, root=DATA_ROOT,
                      popen_factory=subprocess.Popen, execution_id=None, source_execution_id=None):
    if mode not in ALLOWED_MODES:
        raise AccessReviewRunnerError('Modo de execucao invalido.')
    selected = _selected_audits(audit_ids)
    execution_id = execution_id or str(uuid4())
    root = Path(root)
    cancel_file = cancellation_path(root, execution_id) if execution_id else None
    def check_cancelled():
        if cancel_file and cancel_file.exists():
            raise AccessReviewRunnerError('Execução interrompida pelo operador. As evidências existentes foram preservadas.')
    check_cancelled()
    issues = configuration_issues(root, selected, mode) if not source_execution_id else []
    if source_execution_id and (mode != 'somente_montagem' or any(
        not recovery_available(root, source_execution_id, area, verify_hash=True) for area in selected
    )):
        raise AccessReviewRunnerError('As evidências da execução original não estão disponíveis para gerar os documentos.')
    if issues:
        raise AccessReviewRunnerError(' '.join(issues))
    config = load_settings(root)
    lock = FileLock(str(root / 'execution.lock'))
    try:
        lock.acquire(timeout=43200)
    except Timeout as exc:
        raise AccessReviewRunnerError('Existe uma revisão em execução. Aguarde a fila.') from exc
    rows = []
    batch_documents = []
    removed = 0
    def report(area, state, message):
        if callable(event):
            event(area, state, message)
    try:
        child_env = _child_environment(root)
        for index, area in enumerate(selected):
            check_cancelled()
            work_root = prepare_recovery(root, source_execution_id, area, execution_id) if source_execution_id else root
            label, folder = AREAS[area]
            started_at = datetime.now(timezone.utc).isoformat()
            ok = False
            friendly = ''
            highest_area_progress = 0
            last_progress_value = None
            collection_complete = mode == 'somente_montagem'

            def publish_area_progress(value):
                nonlocal highest_area_progress, last_progress_value
                last_progress_value = value
                highest_area_progress = max(highest_area_progress, value['percent'])
                if callable(progress):
                    overall = int(2 + ((index + (highest_area_progress / 100)) / len(selected)) * 93)
                    progress(overall, f'{label}: {_progress_message(value)}.')

            for attempt in range(1, config['tentativas'] + 1):
                check_cancelled()
                last_progress_value = None
                collection_complete = mode == 'somente_montagem'
                report(area, 'running', f'{label}: tentativa {attempt} de {config["tentativas"]}.')
                if callable(progress):
                    overall = int(2 + ((index + (highest_area_progress / 100)) / len(selected)) * 93)
                    progress(overall, f'{label}: iniciando tentativa {attempt} de {config["tentativas"]}.')
                output = work_root / 'dados' / 'execucoes' / folder
                previous = {p.name: (p.stat().st_mtime_ns, p.stat().st_size) for p in output.glob('*.docx')}
                process_started_ns = time.time_ns()
                progress_file = work_root / 'runtime' / f'progress-{uuid4().hex}.json'
                collection_marker = Path(str(progress_file) + '.collected')
                detail_file = progress_file.with_suffix('.events.jsonl')
                detail_offset = 0
                def drain_details():
                    nonlocal detail_offset
                    detail_offset = _drain_details(detail_file, detail_offset, report, area)
                progress_file.parent.mkdir(parents=True, exist_ok=True)
                attempt_env = dict(child_env)
                attempt_env['SENTINEL_ACCESS_REVIEW_HOME'] = str(work_root.resolve())
                attempt_env['SENTINEL_ACCESS_REVIEW_PROGRESS_FILE'] = str(progress_file)
                command = ['powershell.exe', '-NoLogo', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                           '-File', str(CODE_ROOT / 'execute.ps1'), '-Area', area]
                if mode == 'somente_montagem':
                    command.append('-SomenteMontagem')
                try:
                    process = popen_factory(command, cwd=str(root), env=attempt_env, stdin=subprocess.DEVNULL,
                                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    guard = None
                    try:
                        if popen_factory is subprocess.Popen:
                            guard = ProcessGuard(process)
                        try:
                            returncode = _wait_with_progress(
                                process, config['timeout_seconds'], progress_file, publish_area_progress, drain_details,
                                lambda: bool(cancel_file and cancel_file.exists())
                            )
                        except subprocess.TimeoutExpired:
                            _terminate_tree(process)
                            friendly = ('O tempo limite desta etapa foi atingido e a automação foi encerrada com segurança. '
                                        'Confirme se o sistema respondeu e tente novamente.')
                            if last_progress_value:
                                friendly += f' Etapa em andamento: {_progress_message(last_progress_value)}.'
                            returncode = -1
                    except OSError:
                        _terminate_tree(process)
                        raise
                    finally:
                        if guard:
                            guard.close()
                        detail_offset = _drain_details(detail_file, detail_offset, report, area)
                        detail_file.unlink(missing_ok=True)
                        progress_file.unlink(missing_ok=True)
                    collection_complete = mode == 'somente_montagem' or collection_marker.is_file()
                    collection_marker.unlink(missing_ok=True)
                    documents = [p for p in output.glob('*.docx') if previous.get(p.name) != (p.stat().st_mtime_ns, p.stat().st_size)]
                    if area == 'windows':
                        documents = [p for p in documents if p.name.endswith('Teste Completo.docx')]
                    if returncode == 0:
                        collection_complete = True
                        publish_area_progress({'stage': 'assembled', 'percent': 97})
                        ok = bool(documents) and all(validate(p)['valido'] for p in documents)
                        friendly = ('' if ok else
                                    'O documento foi criado, mas não passou pela validação. Use “Gerar novamente” se as evidências ainda estiverem disponíveis.')
                    elif not friendly:
                        friendly = (_windows_failure_message(root, process_started_ns, bool(documents))
                                    if area == 'windows' and mode == 'completa' else _failure_message(area, mode))
                        if last_progress_value:
                            friendly += f' Etapa em andamento quando ocorreu a falha: {_progress_message(last_progress_value)}.'
                except OSError:
                    progress_file.unlink(missing_ok=True)
                    friendly = ('Não foi possível iniciar a automação. Confirme se o PowerShell está disponível '
                                'e se a conta do Sentinel possui permissão para executar o módulo.')
                if ok:
                    break
                if last_progress_value and last_progress_value['stage'] == 'windows_aborted':
                    report(area, 'failed', 'Servidores Windows: cinco regionais consecutivas falharam. Revisão AD encerrada; seguindo para a próxima área.')
                    break
                report(area, 'retry' if attempt < config['tentativas'] else 'failed', f'{label}: {friendly}')
                if attempt < config['tentativas']:
                    for _ in range(config['intervalo_segundos']):
                        check_cancelled()
                        time.sleep(1)
            row = {'id': area, 'nome': label, 'status': 'OK' if ok else 'FALHA', 'tentativas': attempt,
                   'inicio': started_at, 'fim': datetime.now(timezone.utc).isoformat()}
            row['failure_stage'] = None if ok else ('document' if collection_complete else 'collection')
            if not ok and collection_complete:
                try:
                    preserve_evidence(work_root, execution_id, area)
                    if work_root != root:
                        import shutil
                        source = work_root / 'dados' / 'recuperacao' / execution_id / area
                        target = root / 'dados' / 'recuperacao' / execution_id / area
                        shutil.copytree(source, target, dirs_exist_ok=True)
                except (OSError, ValueError):
                    report(area, 'warning', f'{label}: evidências incompletas; nova geração indisponível.')
            if not ok:
                row['erro_amigavel'] = friendly
            rows.append(row)
            if ok:
                approve_documents(root, area, documents, execution_id, source_root=work_root)
                batch_documents.extend(documents)
                report(area, 'completed', f'{label}: documento validado e revisão concluída.')
            if callable(progress):
                progress(int(2 + ((index+1) / len(selected)) * 93), f'{index+1} de {len(selected)} áreas processadas.')
        success = all(row['status'] == 'OK' for row in rows)
        check_cancelled()
        if success:
            success = bool(batch_documents) and all(validate(document)['valido'] for document in batch_documents)
            if not success:
                for row in rows:
                    row.update(status='FALHA', failure_stage='document', erro_amigavel='A conferência final do lote falhou. Os prints foram preservados.')
                report(selected[-1], 'failed', 'A conferência final dos documentos falhou; nenhum print foi removido.')
        if success and config.get('remover_prints_apos_validacao', True):
            for area in selected:
                label, folder = AREAS[area]
                cleanup_root = root / 'runtime' / 'regeneracao' / execution_id / area if source_execution_id else root
                evidence = (cleanup_root / 'dados' / 'evidencias' / folder).resolve()
                for picture in evidence.rglob('*.png') if evidence.is_relative_to(root.resolve()) and evidence.exists() else []:
                    resolved = picture.resolve()
                    if resolved.is_relative_to(evidence):
                        try:
                            resolved.unlink()
                            removed += 1
                        except OSError:
                            report(area, 'warning', f'{label}: alguns prints nao puderam ser removidos.')
                if source_execution_id:
                    try:
                        clear_recovery_pngs(root, source_execution_id, area)
                    except OSError:
                        report(area, 'warning', f'{label}: não foi possível limpar todos os prints de recuperação.')
        now = datetime.now(timezone.utc).isoformat()
        payload = {'execucao_id': execution_id or str(uuid4()), 'origem': 'automacao-auditoria',
                   'source_execution_id': source_execution_id,
                   'titulo': 'Revisao de Acessos concluida' if success else 'Revisao de Acessos com falhas',
                   'mensagem': f'{len(rows)} area(s) processada(s).', 'status': 'SUCESSO' if success else 'FALHA',
                   'severidade': 'informacao' if success else 'critico', 'data': now,
                   'resumo': {'executado_em': now, 'somente_montagem': mode == 'somente_montagem',
                              'navegador_compartilhado': False, 'documentos_validos': success,
                              'prints_removidos': removed, 'auditorias': rows}}
        store_audit_execution(payload, path=root / 'executions.sqlite3')
        failed_labels = [row['nome'] for row in rows if row['status'] != 'OK']
        return {'success': success, 'mode': mode, 'audits': selected, 'execution_id': payload['execucao_id'],
                'message': ('Revisão concluída.' if success else
                            f"Não foi possível concluir: {', '.join(failed_labels)}. Consulte a orientação exibida na etapa.")}
    finally:
        lock.release()
