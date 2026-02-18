# Teste completo simulando a API
from gerenciar_fortigate import GerenciadorFortigate
from gerenciar_regionais import GerenciadorRegionais
import json

print('🔍 Teste completo da funcionalidade de links com verificação de IP')
print('=' * 60)

# Inicializar gerenciadores
gf = GerenciadorFortigate()
gr = GerenciadorRegionais()

# Autenticar no Fortigate
print('🔐 Autenticando no Fortigate...')
if not gf.autenticar():
    print('❌ Falha na autenticação')
    exit(1)
print('✅ Autenticação bem-sucedida')

# Obter link de teste
codigo_regional = 'RG_GLOBAL_SEGURANCA'
id_link = 'link_rg_global_seguranca_01'

print(f'🔍 Obtendo link {id_link} da regional {codigo_regional}...')
link = gr.obter_link(codigo_regional, id_link)
if not link:
    print('❌ Link não encontrado')
    exit(1)

print(f'📋 Link encontrado: {link["nome"]} - IP: {link["ip"]} - Provedor: {link["provedor"]}')

# Obter interfaces do Fortigate
print('🔍 Obtendo interfaces do Fortigate...')
interfaces_result = gf.obter_interfaces()
if not interfaces_result['success']:
    print('❌ Erro ao obter interfaces')
    exit(1)

# Mapeamento automático baseado no nome do link
link_nome = link.get('nome', '').upper()
mapeamento_interfaces = {
    'WAN_CONNECT_01': 'wan1',
    'WAN_CONNECT_02': 'wan2',
    'WAN1': 'wan1',
    'WAN2': 'wan2',
    'INTERNET_01': 'wan1',
    'INTERNET_02': 'wan2',
    'LINK_01': 'wan1',
    'LINK_02': 'wan2',
    'LINK_WAN1': 'wan1',
    'LINK_WAN2': 'wan2',
    'CONNECT_01': 'wan1',
    'CONNECT_02': 'wan2'
}

interface_mapeada = None
for chave, interface in mapeamento_interfaces.items():
    if chave in link_nome:
        interface_mapeada = interface
        break

if interface_mapeada:
    print(f'🔗 Mapeamento automático: {link_nome} -> {interface_mapeada}')
    interface_name = interface_mapeada
else:
    print('❌ Mapeamento não encontrado')
    exit(1)

# Testar o link com verificação de IP
print(f'🧪 Testando conectividade do link {interface_name} com IP {link["ip"]}...')
resultado = gf.testar_link(interface_name, link['ip'])

print('📊 Resultado do teste:')
print(json.dumps(resultado, indent=2, ensure_ascii=False))

# Atualizar o link na regional
if resultado['success']:
    link['status'] = resultado['status']
    link['ultima_verificacao'] = resultado['ultima_verificacao']
    gr.atualizar_link(codigo_regional, id_link, link)
    print('💾 Status do link atualizado na regional')

print('✅ Teste completo finalizado!')