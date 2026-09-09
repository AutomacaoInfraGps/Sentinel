"""
Modelo de usuário para Flask-Login
"""

from datetime import datetime
from threading import RLock
from typing import Dict, Optional

from flask_login import UserMixin

class User(UserMixin):
    """Classe de usuário para Flask-Login"""
    
    def __init__(self, user_data: Dict):
        self.username = str(user_data['username']).strip()
        self.id = self.username
        self.display_name = user_data.get('display_name', self.username)
        self.email = user_data.get('email', '')
        self.dn = str(user_data.get('dn') or '').strip()
        self.groups = tuple(
            str(group).strip()
            for group in (user_data.get('groups') or [])
            if str(group).strip()
        )
        self.login_time = datetime.now()
    
    def get_id(self):
        """Retorna o ID único do usuário"""
        return self.username
    
    @property
    def is_authenticated(self):
        """Retorna True se o usuário está autenticado"""
        return True
    
    @property
    def is_active(self):
        """Retorna True se o usuário está ativo"""
        return True
    
    @property
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
            'groups': list(self.groups),
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
_user_cache_lock = RLock()

def get_user(user_id: str) -> Optional[User]:
    """Recupera usuário do cache"""
    with _user_cache_lock:
        return _user_cache.get(str(user_id))

def save_user(user: User):
    """Salva usuário no cache"""
    with _user_cache_lock:
        _user_cache[user.get_id()] = user

def remove_user(user_id: str):
    """Remove usuário do cache"""
    with _user_cache_lock:
        _user_cache.pop(str(user_id), None)

def get_all_users() -> Dict[str, User]:
    """Retorna todos os usuários logados"""
    with _user_cache_lock:
        return _user_cache.copy()
