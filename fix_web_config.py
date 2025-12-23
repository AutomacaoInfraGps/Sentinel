"""
Script para corrigir o erro de sintaxe no arquivo web_config.py
"""

import re

# Lê o arquivo web_config.py
with open('web_config.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Corrige o erro de sintaxe na linha 379
fixed_content = re.sub(
    r"return jsonify\(\{'success': False, 'message': f'Erro interno: \{str\(e\)\}'\}\)",
    "return jsonify({'success': False, 'message': f'Erro interno: {str(e)}'})",
    content
)

# Salva o arquivo corrigido
with open('web_config.py', 'w', encoding='utf-8') as f:
    f.write(fixed_content)

print("✅ Arquivo web_config.py corrigido com sucesso!")