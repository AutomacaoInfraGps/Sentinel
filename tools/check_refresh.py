import requests
import os
import sys
from datetime import datetime

url = 'http://localhost:5000/api/mapa/dados?refresh=1'
import os
cache = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'output', 'mapa_monitoramento_cache.json'))

try:
    r = requests.get(url, timeout=120)
    print('HTTP', r.status_code)
    try:
        j = r.json()
        print('regionais=', len(j.get('regionais', [])))
    except Exception as e:
        print('response not json:', e)
        txt = r.text if hasattr(r, 'text') else None
        if txt:
            print('response text (first 1000 chars):')
            print(txt[:1000])
except Exception as e:
    print('request failed:', e)

if os.path.exists(cache):
    mtime = datetime.utcfromtimestamp(os.path.getmtime(cache)).isoformat() + 'Z'
    print('cache:', cache)
    print('lastwrite:', mtime)
else:
    print('cache missing:', cache)

# exit code 0
