# Sistema de Autenticação Active Directory

## Configuração Implementada

As configurações do AD podem ser fornecidas via variáveis de ambiente:

- `AD_DOMAIN_DNS`
- `AD_DOMAIN_NETBIOS`
- `AD_DC_SERVER`
- `AD_AUTHORIZED_OU`
- `AD_SEARCH_BASE`

### Configurações do AD
- **Domínio DNS**: DOMINIO.LOCAL
- **Domínio NetBIOS**: DOMINIO
- **Servidor Principal**: DC01 (192.0.2.11)
- **OU Autorizada**: `OU=Usuarios Administrativos,OU=Empresa,DC=Dominio,DC=local`

### Usuários Autorizados
Baseado na consulta `dsquery`, os usuários na OU administrativa devem ser validados sem expor nomes reais na documentação.

## Como Usar

### Função Principal
```python
from auth_ad import verificar_usuario_ad

# Autentica usuário
sucesso, user_info, mensagem = verificar_usuario_ad('usuario.exemplo', 'senha')

if sucesso:
    print(f"Usuário autenticado: {user_info['displayName']}")
    print(f"DN: {user_info['dn']}")
else:
    print(f"Falha: {mensagem}")
```

### Formato de Usuário
- **Formato usado**: `DOMINIO\username`
- **Autenticação**: NTLM (padrão Windows AD)
- **Exemplo**: `DOMINIO\usuario.exemplo`

## Validações Implementadas

1. **Autenticação**: Verifica credenciais contra o AD
2. **Autorização**: Confirma se o usuário está na OU administrativa
3. **Informações**: Retorna dados completos do usuário autenticado

## Estrutura de Retorno

```python
# Sucesso
(True, {
    'username': 'usuario.exemplo',
    'displayName': 'Usuario Exemplo',
    'dn': 'CN=Usuario Exemplo,OU=Usuarios Administrativos,OU=Empresa,DC=Dominio,DC=local',
    'email': 'usuario.exemplo@dominio.local'
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