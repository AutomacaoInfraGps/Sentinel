"""
Modelo de usuário para Flask-Login
"""

from flask_login import UserMixin
from typing import Dict, Optional
import json
from datetime import datetime

class User(UserMixin):
    """Classe de usuário para Flask-Login"""
    
    def __init__(self, user_data: Dict):
        self.id = user_data['username']
        self.username = user_data['username']
        self.display_name = user_data.get('display_name', self.username)
        self.email = user_data.get('email', '')
        self.dn = user_data.get('dn', '')
        self.groups = user_data.get('groups', [])
        self.login_time = datetime.now()
    
    def get_id(self):
        """Retorna o ID único do usuário"""
        return self.username
    
    def is_authenticated(self):
        """Retorna True se o usuário está autenticado"""
        return True
    
    def is_active(self):
        """Retorna True se o usuário está ativo"""
        return True
    
    def is_anonymous(self):
        """Retorna True se o usuário é anônimo"""
        return False
    
    def to_dict(self) -> Dict:
        """Converte o usuário para dicionário"""
        return {
            'username': self.username,
            'display_name': self.display_name,
            'email': self.email,
            'dn': self.dn,
            'groups': self.groups,
            'login_time': self.login_time.isoformat()
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'User':
        """Cria usuário a partir de dicionário"""
        user = cls(data)
        if 'login_time' in data:
            user.login_time = datetime.fromisoformat(data['login_time'])
        return user
    
    def __repr__(self):
        return f'<User {self.username}>'

# Cache simples de usuários (em produção, usar Redis ou banco)
_user_cache = {}

def get_user(user_id: str) -> Optional[User]:
    """Recupera usuário do cache"""
    return _user_cache.get(user_id)

def save_user(user: User):
    """Salva usuário no cache"""
    _user_cache[user.get_id()] = user

def remove_user(user_id: str):
    """Remove usuário do cache"""
    if user_id in _user_cache:
        del _user_cache[user_id]

def get_all_users() -> Dict[str, User]:
    """Retorna todos os usuários logados"""
    return _user_cache.copy()