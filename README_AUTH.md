# Sistema de Autenticação Active Directory

## Configuração Implementada

### Configurações do AD
- **Domínio DNS**: GALAXIA.LOCAL
- **Domínio NetBIOS**: GALAXIA
- **Servidor Principal**: SIRIUS (10.254.12.11)
- **OU Autorizada**: `OU=Usuarios Administrativos,OU=Galaxia,DC=Galaxia,DC=local`

### Usuários Autorizados
Baseado na consulta `dsquery`, os usuários na OU administrativa são:
- Marcus Vinicius Batista Lima (admin.lima)
- Michel Pereira dos Santos
- Kleyton Leopoldo e Silva Eleuterio
- Felipe Barbosa Oliveira
- Ricardo Orquisa
- Joao Paulo Da Gama Neto
- Nelio Alves De Oliveira Santos

## Como Usar

### Função Principal
```python
from auth_ad import verificar_usuario_ad

# Autentica usuário
sucesso, user_info, mensagem = verificar_usuario_ad('admin.lima', 'senha')

if sucesso:
    print(f"Usuário autenticado: {user_info['displayName']}")
    print(f"DN: {user_info['dn']}")
else:
    print(f"Falha: {mensagem}")
```

### Formato de Usuário
- **Formato usado**: `GALAXIA\username`
- **Autenticação**: NTLM (padrão Windows AD)
- **Exemplo**: `GALAXIA\admin.lima`

## Validações Implementadas

1. **Autenticação**: Verifica credenciais contra o AD
2. **Autorização**: Confirma se o usuário está na OU administrativa
3. **Informações**: Retorna dados completos do usuário autenticado

## Estrutura de Retorno

```python
# Sucesso
(True, {
    'username': 'admin.lima',
    'displayName': 'Marcus Vinicius Batista Lima',
    'dn': 'CN=Marcus Vinicius Batista Lima,OU=Usuarios Administrativos,OU=Galaxia,DC=Galaxia,DC=local',
    'email': 'admin.lima@Galaxia.local'
}, 'Usuário autenticado com sucesso')

# Falha
(False, None, 'Usuário ou senha inválidos')
```

## Teste Seguro

Para testar sem risco de bloquear contas:
```bash
python test_auth_safe.py
```

## ⚠️ Importante

- **Evite múltiplos testes**: Testes repetidos com senha errada bloqueiam a conta
- **Use credenciais corretas**: Teste apenas quando tiver certeza da senha
- **Monitoramento**: O sistema registra tentativas de autenticação nos logs

## Arquivos

- `auth_ad.py`: Módulo principal de autenticação
- `test_auth_safe.py`: Teste seguro da configuração
- `README_AUTH.md`: Esta documentação