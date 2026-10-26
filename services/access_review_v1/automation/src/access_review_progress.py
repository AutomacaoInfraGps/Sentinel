"""Publica apenas marcos operacionais sanitizados para a barra de progresso."""

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


def publish_detail(stage, *, target='', status='running', error=None):
    """Eventos estruturados: nunca serializar excecoes, stdout ou credenciais."""
    value = os.environ.get('SENTINEL_ACCESS_REVIEW_PROGRESS_FILE', '')
    if not value:
        return
    try:
        path = Path(value).with_suffix('.events.jsonl').resolve()
        runtime = (Path(os.environ['SENTINEL_ACCESS_REVIEW_HOME']) / 'runtime').resolve()
        if not path.is_relative_to(runtime):
            return
        clean = lambda text: re.sub(r'[\x00-\x1f\x7f]', ' ', str(text))[:160]
        payload = dict(stage=clean(stage), target=clean(target), status=status,
                       error_type=type(error).__name__ if error else '',
                       occurred_at=datetime.now(timezone.utc).isoformat())
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(payload, ensure_ascii=False) + '\n')
    except (KeyError, OSError, ValueError):
        pass


def publish_progress(stage, percent, *, current=None, total=None):
    target_value = os.environ.get('SENTINEL_ACCESS_REVIEW_PROGRESS_FILE', '').strip()
    if not target_value:
        return
    try:
        target = Path(target_value)
        root = Path(os.environ['SENTINEL_ACCESS_REVIEW_HOME']).resolve()
        runtime = (root / 'runtime').resolve()
        resolved = target.resolve()
        if not resolved.is_relative_to(runtime):
            return
        payload = {'stage': str(stage)[:40], 'percent': max(0, min(100, int(percent)))}
        if isinstance(current, int) and isinstance(total, int) and 0 <= current <= total <= 1000:
            payload.update(current=current, total=total)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        temporary = resolved.with_name(f'{resolved.name}.{os.getpid()}.tmp')
        temporary.write_text(json.dumps(payload, separators=(',', ':')), encoding='utf-8')
        os.replace(temporary, resolved)
    except (KeyError, OSError, TypeError, ValueError):
        # Progresso nunca pode interromper a revisão.
        return


if __name__ == '__main__':
    # Argumentos operacionais fixos usados pelos auxiliares PowerShell.
    if len(sys.argv) == 4:
        publish_detail(sys.argv[1], target=sys.argv[2], status=sys.argv[3])
