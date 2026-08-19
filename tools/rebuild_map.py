import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from web_config import _montar_dados_mapa_monitoramento
from web_config import _montar_dados_mapa_monitoramento, _mapa_salvar_cache

print('Chamando _montar_dados_mapa_monitoramento()')
res = _montar_dados_mapa_monitoramento()
print('Retorno (tipo):', type(res))
print('Salvando cache...')
saved = _mapa_salvar_cache(res)
print('Cache salvo. keys:', list(saved.keys())[:10])
