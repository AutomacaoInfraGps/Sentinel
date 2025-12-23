"""
Script para corrigir o erro de sintaxe no arquivo web_config.py
"""

# Lê o arquivo web_config.py
with open('web_config.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Corrige a linha 379
lines[378] = "        return jsonify({'success': False, 'message': f'Erro interno: {str(e)}'})\n"

# Salva o arquivo corrigido
with open('web_config.py', 'w', encoding='utf-8') as f:
    f.writelines(lines)

print("✅ Arquivo web_config.py corrigido com sucesso!")