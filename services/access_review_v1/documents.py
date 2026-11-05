"""Documentos finais preservados por execucao e exportacao restrita."""
from datetime import datetime, timezone
import json
from pathlib import Path
import os
import re
import shutil
from tempfile import SpooledTemporaryFile
from uuid import UUID
from zipfile import ZipFile, ZIP_DEFLATED
from zoneinfo import ZoneInfo
from filelock import FileLock
from .settings import AREAS, DATA_ROOT


def _final_name(area, name):
    if area == 'windows':
        return name == 'Auditoria Galaxia Servidores Windows - Teste Completo.docx'
    return bool(re.fullmatch(rf'Revisao-{re.escape(area)}-\d{{8}}-\d{{6}}-?\d{{3}}\.docx', name))


def _directory(root, execution_id):
    root = Path(root).resolve()
    directory = root / 'dados' / 'documentos' / str(UUID(str(execution_id)))
    if not directory.resolve().is_relative_to(root):
        raise ValueError('Diretório de documentos inválido.')
    return directory


def approve_documents(root, area, documents, execution_id, *, source_root=None):
    """Preserva uma copia final para nao perder o Windows na proxima rodada."""
    if area not in AREAS:
        raise ValueError('Área inválida.')
    documents = list(documents)
    if not documents or any(not _final_name(area, document.name) for document in documents):
        raise ValueError('Nenhum documento final reconhecido para aprovação.')
    directory = _directory(root, execution_id)
    registry = directory / 'manifest.json'
    try:
        record = json.loads(registry.read_text(encoding='utf-8'))
    except FileNotFoundError:
        record = {'id': str(UUID(str(execution_id))), 'created_at': datetime.now(timezone.utc).isoformat(), 'documents': {}}
    output = (Path(source_root or root) / 'dados' / 'execucoes').resolve()
    if not output.is_relative_to(Path(root).resolve()):
        raise ValueError('Diretório de origem inválido.')
    for document in documents:
        if document.is_symlink() or not document.resolve().is_relative_to(output):
            raise ValueError('Documento fora da pasta de resultados.')
        target = directory / AREAS[area][1] / document.name
        if not target.resolve().is_relative_to(directory.resolve()):
            raise ValueError('Destino inválido.')
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(document, target)
        stat = target.stat()
        record['documents'][target.relative_to(directory).as_posix()] = {
            'area': area, 'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns}
    directory.mkdir(parents=True, exist_ok=True)
    temporary = registry.with_suffix('.tmp')
    temporary.write_text(json.dumps(record), encoding='utf-8')
    os.replace(temporary, registry)


def list_document_executions(root=DATA_ROOT):
    result = []
    base = Path(root).resolve()
    for path in (base / 'dados' / 'documentos').glob('*/manifest.json'):
        try:
            if not path.resolve().is_relative_to(base):
                continue
            item = json.loads(path.read_text(encoding='utf-8'))
            execution_id = str(UUID(item['id']))
            if path.parent.name != execution_id or not item['documents']:
                continue
            date = datetime.fromisoformat(item['created_at']).astimezone(ZoneInfo('America/Sao_Paulo'))
            areas = sorted({AREAS[doc['area']][0] for doc in item['documents'].values()})
            area_options = [{'id': area, 'label': label} for area, (label, _) in AREAS.items()
                            if any(doc['area'] == area for doc in item['documents'].values())]
            result.append({'id': execution_id, 'label': date.strftime('RevAcc_%Y-%m-%d_%H:%M:%S'),
                           'created_at': item['created_at'], 'count': len(item['documents']), 'areas': areas,
                           'area_options': area_options})
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return sorted(result, key=lambda item: item['created_at'], reverse=True)[:100]


def build_documents_zip(root=DATA_ROOT, *, execution_id, audit_ids=None):
    if audit_ids is not None and (not isinstance(audit_ids, list) or not audit_ids or
            any(area not in AREAS for area in audit_ids) or len(set(audit_ids)) != len(audit_ids)):
        raise ValueError('Selecione uma ou mais áreas válidas.')
    root = Path(root).resolve()
    directory = _directory(root, execution_id)
    archive = SpooledTemporaryFile(max_size=8 * 1024 * 1024, mode='w+b')
    try:
        with FileLock(str(root / 'execution.lock')).acquire(timeout=0):
            record = json.loads((directory / 'manifest.json').read_text(encoding='utf-8'))
            available = {doc['area'] for doc in record['documents'].values()}
            if audit_ids and not set(audit_ids).issubset(available):
                raise FileNotFoundError('A execução não possui todos os documentos selecionados.')
            count = 0
            with ZipFile(archive, 'w', ZIP_DEFLATED) as bundle:
                for relative, approved in record['documents'].items():
                    area = approved['area']
                    if audit_ids is not None and area not in audit_ids:
                        continue
                    document = directory / relative
                    if area not in AREAS or relative != f'{AREAS[area][1]}/{document.name}' or not _final_name(area, document.name):
                        raise ValueError('Registro de documento inválido.')
                    if document.is_symlink() or not document.resolve().is_relative_to(directory.resolve()):
                        raise ValueError('Documento inválido.')
                    stat = document.stat()
                    if stat.st_size != approved['size'] or stat.st_mtime_ns != approved['mtime_ns']:
                        raise ValueError('Documento alterado após aprovação.')
                    bundle.write(document, arcname=relative)
                    count += 1
            if not count:
                raise FileNotFoundError('Nenhum documento aprovado nesta execução.')
        archive.seek(0)
        return archive
    except Exception:
        archive.close()
        raise
