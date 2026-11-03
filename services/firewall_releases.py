"""Catálogo público FortiOS. Nunca envia inventário corporativo à Fortinet."""
import json
import logging
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import requests
from bs4 import BeautifulSoup
from filelock import FileLock, Timeout
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASE = 'https://docs.fortinet.com'
INDEX = BASE + '/product/fortigate/'
_VERSION = re.compile(r'(?<!\d)(\d+)\.(\d+)\.(\d+)(?!\d)')
_MODEL = re.compile(r'\b(?:FG|FWF)-[A-Z0-9]+(?:-[A-Z0-9]+)*\b')


def version(value):
    match = _VERSION.search(str(value or ''))
    return tuple(map(int, match.groups())) if match else None


def model(value):
    text = str(value or '').strip().upper()
    text = re.sub(r'^FORTIGATE[-\s]*', 'FG-', text)
    text = re.sub(r'^FORTIWIFI[-\s]*', 'FWF-', text)
    return text if _MODEL.fullmatch(text) else None


def _public_url(value, base=BASE):
    url = urljoin(base, value)
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or parsed.netloc != 'docs.fortinet.com':
        raise ValueError('Link externo ao catálogo oficial')
    return url


def _page(session, url):
    url = _public_url(url)
    # Validar cada redirecionamento antes de segui-lo.
    for _ in range(6):
        response = session.get(_public_url(url), timeout=(5, 20), allow_redirects=False)
        if response.status_code in (301, 302, 303, 307, 308):
            url = _public_url(response.headers['Location'], url)
            continue
        response.raise_for_status()
        return BeautifulSoup(response.text, 'html.parser'), url
    raise ValueError('Redirecionamentos excedidos')


def collect():
    with requests.Session() as session:
        session.headers['User-Agent'] = 'Mozilla/5.0 (compatible; SentinelReleaseCatalog/1.0)'
        session.mount(BASE, HTTPAdapter(max_retries=Retry(
            total=2, backoff_factor=1, status_forcelist=(429, 500, 502, 503, 504))))
        page, _ = _page(session, INDEX)
        lines = sorted({a['href'] for a in page.select('a[href]')
                        if re.fullmatch(r'/product/fortigate/\d+\.\d+', a['href'])})
        if not lines:
            raise ValueError('Linhas não encontradas')
        releases = []
        unverified = set()
        for line in lines:
            page, url = _page(session, line)
            links = {_public_url(a['href'], url) for a in page.select('a[href]')
                     if re.search(r'/document/fortigate/\d+\.\d+\.\d+/fortios-release-notes/?$', a['href'])}
            if not links:
                raise ValueError('Release Notes ausentes em uma linha')
            # Todos os patches: modelos podem entrar ou sair entre releases.
            for link in sorted(links, key=version, reverse=True):
                document, source = _page(session, link)
                tables = [t for t in document.select('table') if _MODEL.search(t.get_text(' ', strip=True))]
                if not tables or 'supported models' not in document.get_text(' ', strip=True).lower():
                    unverified.add(line.rsplit('/', 1)[-1])
                    continue
                models = sorted(set(_MODEL.findall(tables[0].get_text(' ', strip=True))))
                if not models:
                    raise ValueError('Lista de modelos vazia')
                releases.append({'version': '.'.join(map(str, version(link))), 'models': models, 'url': source})
        return {'checked_at': datetime.now(timezone.utc).isoformat(),
                'lines': [line.rsplit('/', 1)[-1] for line in lines], 'releases': releases,
                'unverified_lines': sorted(unverified)}


def assess(snapshot, hardware, firmware, stale=False):
    result = {'state': 'unknown', 'label': 'Verificação indisponível', 'url': INDEX,
              'message': 'Não foi possível verificar este modelo e firmware.',
              'checked_at_display': 'Não disponível', 'stale': stale, 'update_kind': None}
    installed, identity = version(firmware), model(hardware)
    if not snapshot:
        result['message'] = 'Catálogo ainda indisponível. A consulta ocorre em segundo plano; recarregue a página mais tarde.'
        return result
    checked = snapshot.get('checked_at', '')
    try:
        checked = datetime.fromisoformat(checked).astimezone(__import__('zoneinfo').ZoneInfo('America/Sao_Paulo')).strftime('%d/%m/%Y - %H:%M')
    except (ValueError, TypeError):
        pass
    result['checked_at_display'] = checked or 'Não disponível'
    suffix = f' Consulta: {checked}.'
    if stale:
        suffix += ' Catálogo desatualizado; última consulta não foi concluída ou está em andamento.'
    if installed and identity:
        line = '.'.join(map(str, installed[:2]))
        if line not in snapshot['lines']:
            result.update(state='absent', label='Linha ausente do catálogo',
                          message=f'A linha {line} não foi encontrada na documentação pública consultada da Fortinet.')
        else:
            compatible = [r for r in snapshot['releases'] if identity in r['models'] and version(r['version']) > installed]
            patches = [r for r in compatible if version(r['version'])[:2] == installed[:2]]
            others = [r for r in compatible if version(r['version'])[:2] != installed[:2]]
            target = max(patches or others, key=lambda r: version(r['version']), default=None)
            if target:
                result['available_version'] = target['version']
                result['update_kind'] = 'same_major' if version(target['version'])[0] == installed[0] else 'new_major'
                result.update(state='update', label='Atualização disponível', url=target['url'],
                              message=f"Versão compatível disponível: {target['version']}. Instalada: {firmware}.")
                if patches and others:
                    result['message'] += ' Outra linha compatível: ' + max(others, key=lambda r: version(r['version']))['version'] + '.'
                result['message'] += ' Verifique as restrições e o caminho de upgrade nas Release Notes.'
            elif not any(tuple(map(int, x.split('.'))) >= installed[:2] for x in snapshot.get('unverified_lines', [])) and any(identity in r['models'] and version(r['version'])[:2] == installed[:2] for r in snapshot['releases']):
                result.update(state='current', label='Sem versão superior no catálogo',
                              message='Nenhuma versão superior compatível foi encontrada no catálogo consultado.')
    if snapshot.get('unverified_lines'):
        suffix += ' Algumas releases não possuem modelos legíveis em HTML; cobertura parcial.'
    result['message'] += suffix
    if stale:
        result['label'] += ' · consulta desatualizada'
    return result


class ReleaseCatalog:
    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.Lock()
        self.running = False
        self.attempt = 0

    def snapshot(self):
        try:
            value = json.loads(self.path.read_text(encoding='utf-8'))
            if not isinstance(value['lines'], list) or not value['releases']:
                return None
            for release in value['releases']:
                if not version(release['version']) or not isinstance(release['models'], list):
                    return None
                _public_url(release['url'])
            return value
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def get(self):
        snapshot = self.snapshot()
        try:
            stale = not snapshot or time.time() - datetime.fromisoformat(snapshot['checked_at']).timestamp() > 86400
        except (ValueError, KeyError, TypeError):
            stale = True
        with self.lock:
            if stale and not self.running and time.time() - self.attempt > 900:
                self.running = True
                self.attempt = time.time()
                threading.Thread(target=self._refresh, daemon=True, name='fortios-release-catalog').start()
        return snapshot, stale

    def _refresh(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with FileLock(str(self.path) + '.lock', timeout=0):
                existing = self.snapshot()
                if existing and time.time() - datetime.fromisoformat(existing['checked_at']).timestamp() < 86400:
                    return
                snapshot = collect()
                temporary = self.path.with_suffix('.tmp')
                temporary.write_text(json.dumps(snapshot), encoding='utf-8')
                temporary.replace(self.path)
        except Timeout:
            pass
        except Exception as exc:
            logging.getLogger(__name__).warning('Catálogo FortiOS não atualizado (%s); preservando cache.', type(exc).__name__)
        finally:
            with self.lock:
                self.running = False


def format_firmware(value):
    """Padroniza apenas a apresentação do build, sem alterar o inventário."""
    return re.sub(r'\bbuild\s*(\d+)', r'Build \1', str(value or 'N/A'), flags=re.IGNORECASE)
