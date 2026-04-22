"""
Módulo de Autenticação Active Directory
Autentica usuários contra AD e verifica se estão na OU autorizada
"""

import os
import socket
from ldap3 import Server, Connection, ALL, NTLM, SIMPLE, SUBTREE
from ldap3.core.exceptions import LDAPException
from typing import Optional, Dict, Tuple
import logging

# Configuração de logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _build_search_base(domain: str) -> str:
    parts = [part for part in domain.split('.') if part]
    if not parts:
        return "DC=Empresa,DC=local"
    return ",".join(f"DC={part}" for part in parts)

class AuthAD:
    """Classe para autenticação Active Directory"""
    
    def __init__(self):
        # Configurações do AD via ambiente para evitar expor dados internos no código.
        self.domain = os.getenv("AD_DOMAIN_DNS", "DOMINIO.LOCAL")
        self.domain_netbios = os.getenv("AD_DOMAIN_NETBIOS", "DOMINIO")
        self.dc_server = os.getenv("AD_DC_SERVER", "DC01")
        self.ou_autorizada = os.getenv(
            "AD_AUTHORIZED_OU",
            "OU=Usuarios Administrativos,OU=Empresa,DC=Dominio,DC=local"
        )
        self.search_base = os.getenv("AD_SEARCH_BASE", _build_search_base(self.domain.title()))
        
        # Tenta descobrir o servidor automaticamente
        self.server_ip = self._descobrir_servidor_ad()
        
    def _descobrir_servidor_ad(self) -> Optional[str]:
        """Descobre o IP do servidor AD"""
        try:
            # Tenta resolver o nome do servidor
            server_ip = socket.gethostbyname(self.dc_server)
            logger.info(f"Servidor AD encontrado: {self.dc_server} ({server_ip})")
            return server_ip
        except socket.gaierror:
            logger.warning(f"Não foi possível resolver {self.dc_server}")
            
            # Tenta descobrir via DNS
            try:
                import subprocess
                result = subprocess.run(
                    ["nslookup", f"_ldap._tcp.{self.domain}"],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                # Parse básico do resultado
                lines = result.stdout.split('\n')
                for line in lines:
                    if 'Address:' in line and not line.strip().endswith('53'):
                        ip = line.split('Address:')[1].strip()
                        logger.info(f"Servidor AD descoberto via DNS: {ip}")
                        return ip
            except Exception as e:
                logger.error(f"Erro ao descobrir servidor AD: {e}")
            
            return None
    
    def autenticar_usuario(self, username: str, password: str) -> Tuple[bool, Optional[Dict], str]:
        """
        Autentica usuário no AD e verifica se está na OU autorizada
        
        Returns:
            Tuple[bool, Optional[Dict], str]: (sucesso, dados_usuario, mensagem)
        """
        if not username or not password:
            return False, None, "Usuário e senha são obrigatórios"
        
        if not self.server_ip:
            return False, None, "Servidor AD não encontrado"
        
        try:
            # Configura servidor LDAP
            server = Server(
                self.server_ip,
                port=389,
                get_info=ALL,
                use_ssl=False
            )
            
            # Usa apenas o formato NetBIOS que funciona melhor com NTLM
            # Baseado nos testes: DOMINIO\usuario é o formato correto
            user_format = f"{self.domain_netbios}\\{username}"
            
            conn = None
            user_dn_real = None
            
            try:
                logger.info(f"Tentando autenticação NTLM com: {user_format}")
                
                # Usa apenas NTLM que é o padrão para Windows AD
                conn = Connection(
                    server,
                    user=user_format,
                    password=password,
                    authentication=NTLM,
                    auto_bind=True,
                    raise_exceptions=True
                )
                logger.info(f"Autenticação bem-sucedida!")
                
            except Exception as e:
                logger.error(f"Falha na autenticação: {e}")
                return False, None, "Usuário ou senha inválidos"
            
            # Se chegou até aqui, a autenticação foi bem-sucedida
            
            logger.info(f"Usuário {username} autenticado com sucesso")
            
            # Busca informações completas do usuário
            search_base = self.search_base
            search_filter = f"(sAMAccountName={username})"
            
            conn.search(
                search_base=search_base,
                search_filter=search_filter,
                search_scope=SUBTREE,
                attributes=['cn', 'displayName', 'mail', 'distinguishedName', 'memberOf']
            )
            
            if not conn.entries:
                conn.unbind()
                return False, None, "Erro ao carregar dados do usuário"
            
            user_entry = conn.entries[0]
            user_dn_full = str(user_entry.distinguishedName)
            
            # Verifica se o usuário está na OU autorizada
            if self._usuario_na_ou_autorizada(user_dn_full):
                user_data = {
                    'username': username,
                    'display_name': str(user_entry.displayName) if user_entry.displayName else username,
                    'email': str(user_entry.mail) if user_entry.mail else '',
                    'dn': user_dn_full,
                    'groups': [str(group) for group in user_entry.memberOf] if user_entry.memberOf else []
                }
                
                conn.unbind()
                logger.info(f"Usuário {username} autorizado (OU: {self.ou_autorizada})")
                return True, user_data, "Autenticação bem-sucedida"
            else:
                conn.unbind()
                logger.warning(f"Usuário {username} não está na OU autorizada")
                return False, None, "Usuário não possui permissão para acessar este sistema"
        
        except LDAPException as e:
            logger.error(f"Erro LDAP ao autenticar {username}: {e}")
            if "invalidCredentials" in str(e):
                return False, None, "Usuário ou senha inválidos"
            else:
                return False, None, f"Erro de autenticação: {str(e)}"
        
        except Exception as e:
            logger.error(f"Erro inesperado ao autenticar {username}: {e}")
            return False, None, f"Erro interno: {str(e)}"
    
    def _usuario_na_ou_autorizada(self, user_dn: str) -> bool:
        """Verifica se o usuário está na OU autorizada"""
        # Normaliza as strings para comparação
        user_dn_lower = user_dn.lower()
        ou_autorizada_lower = self.ou_autorizada.lower()
        
        # Verifica se a OU autorizada está contida no DN do usuário
        return ou_autorizada_lower in user_dn_lower
    
    def testar_conexao(self) -> Tuple[bool, str]:
        """Testa a conexão com o servidor AD"""
        if not self.server_ip:
            return False, "Servidor AD não encontrado"
        
        try:
            server = Server(
                self.server_ip,
                port=389,
                get_info=ALL,
                use_ssl=False
            )
            
            # Tenta uma conexão anônima para testar
            conn = Connection(server)
            conn.bind()
            conn.unbind()
            
            return True, f"Conexão com {self.dc_server} ({self.server_ip}) bem-sucedida"
        
        except Exception as e:
            return False, f"Erro ao conectar com AD: {str(e)}"
    
    def listar_usuarios_ou(self) -> list:
        """Lista usuários da OU autorizada (para debug/admin)"""
        if not self.server_ip:
            return []
        
        try:
            # Usa credenciais do usuário atual do Windows
            server = Server(self.server_ip, port=389, get_info=ALL, use_ssl=False)
            conn = Connection(server, authentication=NTLM, auto_bind=True)
            
            # Busca usuários na OU específica
            conn.search(
                search_base=self.ou_autorizada,
                search_filter="(objectClass=user)",
                search_scope=SUBTREE,
                attributes=['sAMAccountName', 'displayName', 'mail']
            )
            
            usuarios = []
            for entry in conn.entries:
                usuarios.append({
                    'username': str(entry.sAMAccountName),
                    'display_name': str(entry.displayName) if entry.displayName else '',
                    'email': str(entry.mail) if entry.mail else ''
                })
            
            conn.unbind()
            return usuarios
        
        except Exception as e:
            logger.error(f"Erro ao listar usuários da OU: {e}")
            return []

# Instância global
auth_ad = AuthAD()

def verificar_usuario_ad(username: str, password: str) -> Tuple[bool, Optional[Dict], str]:
    """Função helper para verificar usuário"""
    return auth_ad.autenticar_usuario(username, password)

def testar_conexao_ad() -> Tuple[bool, str]:
    """Função helper para testar conexão"""
    return auth_ad.testar_conexao()

# === INTEGRAÇÃO COM FLASK ===

from flask_login import UserMixin

class User(UserMixin):
    """Classe de usuário para Flask-Login"""
    
    def __init__(self, user_id, display_name=None, email=None):
        self.id = user_id
        self.display_name = display_name or user_id
        self.email = email
    
    def get_id(self):
        return self.id
    
    @property
    def is_authenticated(self):
        return True
    
    @property
    def is_active(self):
        return True
    
    @property
    def is_anonymous(self):
        return False
    
    def __repr__(self):
        return f'<User {self.id}>'

# Cache de usuários para evitar múltiplas consultas AD
_user_cache = {}

def get_user(user_id):
    """Obtém usuário do cache ou cria novo"""
    if user_id in _user_cache:
        return _user_cache[user_id]
    
    # Cria usuário básico se não estiver no cache
    user = User(user_id)
    _user_cache[user_id] = user
    return user

def init_auth(app):
    """Inicializa autenticação no Flask app"""
    
    @app.route('/login', methods=['GET', 'POST'])
    def login():
        """Página de login com autenticação AD"""
        from flask import request, render_template, redirect, url_for, flash
        from flask_login import login_user, current_user
        
        # Se já está logado, redireciona
        if current_user.is_authenticated:
            return redirect(url_for('index'))
        
        if request.method == 'POST':
            username = request.form.get('username', '').strip()
            password = request.form.get('password', '')
            
            if not username or not password:
                flash('Usuário e senha são obrigatórios', 'error')
                return render_template('login.html')
            
            # Tenta autenticar no AD
            sucesso, user_info, mensagem = verificar_usuario_ad(username, password)
            
            if sucesso:
                # Cria usuário e faz login
                user = User(
                    user_id=username,
                    display_name=user_info.get('display_name'),
                    email=user_info.get('email')
                )
                _user_cache[username] = user
                login_user(user)
                
                flash(f'Bem-vindo, {user.display_name}!', 'success')
                
                # Redireciona para página solicitada ou dashboard
                next_page = request.args.get('next')
                return redirect(next_page) if next_page else redirect(url_for('index'))
            else:
                flash(f'Erro de autenticação: {mensagem}', 'error')
        
        return render_template('login.html')
    
    @app.route('/logout')
    def logout():
        """Logout do usuário"""
        from flask import redirect, url_for, flash
        from flask_login import logout_user, current_user
        
        if current_user.is_authenticated:
            username = current_user.id
            logout_user()
            # Remove do cache
            if username in _user_cache:
                del _user_cache[username]
            flash('Logout realizado com sucesso', 'info')
        
        return redirect(url_for('login'))