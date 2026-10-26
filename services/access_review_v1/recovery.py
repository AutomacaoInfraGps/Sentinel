"""Evidencias de recuperacao isoladas e vinculadas a uma execucao."""
import hashlib
import json
from pathlib import Path
import shutil
from uuid import UUID
from .settings import AREAS, MODELS, DATA_ROOT, _remount_diagnostics


def _base(root, execution_id, area):
    if area not in AREAS:
        raise ValueError('Área inválida.')
    root = Path(root).resolve()
    path = root / 'dados' / 'recuperacao' / str(UUID(str(execution_id))) / area
    if not path.resolve().is_relative_to(root):
        raise ValueError('Diretório de recuperação inválido.')
    return path


def _allowed_relative(relative, area):
    folder = AREAS[area][1]
    path = Path(relative)
    fixed = {'config/auditorias.json', f'modelos/{MODELS[area]}',
             'dados/execucoes/Inventario-Evidencias-ServidoresWindows.json',
             f'dados/execucoes/{folder}/Coleta-ServidoresWindows.json',
             f'dados/execucoes/{folder}/Dados-AuditoriaLinux.json',
             f'dados/execucoes/{folder}/Resultado-AuditoriaFirewalls.json'}
    return relative in fixed or (path.parent.as_posix() == f'dados/evidencias/{folder}' and path.suffix == '.png')


def preserve_evidence(root, execution_id, area):
    root = Path(root).resolve()
    if _remount_diagnostics(root, area):
        raise ValueError('A coleta não possui todas as evidências obrigatórias.')
    base = _base(root, execution_id, area)
    home = base / 'home'
    folder = AREAS[area][1]
    files = [root / 'config' / 'auditorias.json', root / 'modelos' / MODELS[area]]
    files += list((root / 'dados' / 'evidencias' / folder).glob('*.png'))
    extras = {
        'windows': ['dados/execucoes/Inventario-Evidencias-ServidoresWindows.json',
                    'dados/execucoes/ServidoresWindows/Coleta-ServidoresWindows.json'],
        'linux': ['dados/execucoes/Linux/Dados-AuditoriaLinux.json'],
        'firewalls': ['dados/execucoes/Firewalls/Resultado-AuditoriaFirewalls.json'],
    }
    files += [root / name for name in extras.get(area, []) if (root / name).is_file()]
    records = {}
    for source in files:
        if source.is_symlink() or not source.resolve().is_relative_to(root):
            raise ValueError('Evidência fora da instância.')
        relative = source.relative_to(root)
        target = home / relative
        if not target.resolve().is_relative_to(base.resolve()):
            raise ValueError('Destino de recuperação inválido.')
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        records[relative.as_posix()] = {'size': target.stat().st_size,
                                      'sha256': hashlib.sha256(target.read_bytes()).hexdigest()}
    base.mkdir(parents=True, exist_ok=True)
    (base / 'manifest.json').write_text(json.dumps(records), encoding='utf-8')


def recovery_available(root, execution_id, area, *, verify_hash=False):
    try:
        base = _base(root, execution_id, area)
        files = json.loads((base / 'manifest.json').read_text(encoding='utf-8'))
        if not files:
            return False
        for relative, record in files.items():
            if not _allowed_relative(relative, area):
                return False
            path = base / 'home' / relative
            if path.is_symlink() or not path.resolve().is_relative_to((base / 'home').resolve()):
                return False
            if path.stat().st_size != record['size']:
                return False
            if verify_hash and hashlib.sha256(path.read_bytes()).hexdigest() != record['sha256']:
                return False
        return not _remount_diagnostics(base / 'home', area)
    except (OSError, ValueError, TypeError, KeyError):
        return False


def prepare_recovery(root, source_id, area, new_id):
    if not recovery_available(root, source_id, area, verify_hash=True):
        raise ValueError('As evidências desta execução estão incompletas ou foram alteradas.')
    source = _base(root, source_id, area) / 'home'
    target = Path(root) / 'runtime' / 'regeneracao' / str(UUID(str(new_id))) / area
    if not target.resolve().is_relative_to(Path(root).resolve()):
        raise ValueError('Destino inválido.')
    records = json.loads((_base(root, source_id, area) / 'manifest.json').read_text(encoding='utf-8'))
    for relative in records:
        destination = target / relative
        if not destination.resolve().is_relative_to(target.resolve()):
            raise ValueError('Destino inválido.')
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / relative, destination)
    return target


def clear_recovery_pngs(root, execution_id, area):
    evidence = _base(root, execution_id, area) / 'home' / 'dados' / 'evidencias' / AREAS[area][1]
    if not evidence.resolve().is_relative_to(Path(root).resolve()):
        raise ValueError('Diretório inválido.')
    for path in evidence.glob('*.png'):
        if not path.is_symlink() and path.resolve().is_relative_to(evidence.resolve()):
            path.unlink()
