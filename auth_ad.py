"""
Módulo de Autenticação Active Directory
Autentica usuários contra AD e verifica se estão na OU autorizada
"""

import json
import os
import re
import socket
import subprocess
import time
from collections import defaultdict, deque
from threading import Lock
from typing import Optional, Dict, Tuple
import logging

from user_model import User, get_user, remove_user, save_user
from regional_access import (
    effective_user_groups,
    has_sentinel_login_access,
    is_administrative_ou_dn,
    observe_support_groups,
)
from security_hardening import is_safe_next_url

# Configuração de logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

LOGIN_FAILURE_LIMIT = 3
LOGIN_FAILURE_WINDOW_SECONDS = 15 * 60
_login_failures = defaultdict(deque)
_login_failures_lock = Lock()


def _login_key(username):
    return str(username or "").strip().casefold()


def _prune_login_failures(username, now=None):
    now = now if now is not None else time.monotonic()
    history = _login_failures[_login_key(username)]
    while history and now - history[0] >= LOGIN_FAILURE_WINDOW_SECONDS:
        history.popleft()
    return history


def _login_is_limited(username):
    with _login_failures_lock:
        return len(_prune_login_failures(username)) >= LOGIN_FAILURE_LIMIT


def _record_login_failure(username):
    with _login_failures_lock:
        _prune_login_failures(username).append(time.monotonic())


def _clear_login_failures(username):
    with _login_failures_lock:
        _login_failures.pop(_login_key(username), None)

class AuthAD:
    """Classe para autenticação Active Directory"""
    
    def __init__(self):
        # Configurações do AD (baseadas nos comandos dsquery/dsget)
        self.domain = "GALAXIA.LOCAL"  # Domínio DNS
        self.domain_netbios = "GALAXIA"  # Nome NetBIOS do domínio
        self.dc_server = "SIRIUS"  # Servidor de domínio principal
        self.ou_autorizada = "OU=Usuarios Administrativos,OU=Galaxia,DC=Galaxia,DC=local"
        
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
    
    def _buscar_dados_usuario_powershell(self, username: str, password: str) -> Optional[Dict]:
        """Consulta o AD nativo quando o bind LDAP da aplicação não é aceito."""
        script = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$plainPassword = [Console]::In.ReadToEnd()
$securePassword = ConvertTo-SecureString $plainPassword -AsPlainText -Force
$credential = New-Object System.Management.Automation.PSCredential(
    ($env:SENTINEL_AD_USER + '@' + $env:SENTINEL_AD_DOMAIN),
    $securePassword
)
$user = Get-ADUser `
    -Identity $env:SENTINEL_AD_USER `
    -Server $env:SENTINEL_AD_SERVER `
    -Credential $credential `
    -Properties DisplayName,mail,memberOf
$groups = @($user.memberOf | ForEach-Object { [string]$_ })
try {
    $groups += @(
        Get-ADPrincipalGroupMembership `
            -Identity $user `
            -Server $env:SENTINEL_AD_SERVER `
            -Credential $credential | ForEach-Object { [string]$_.DistinguishedName }
    )
} catch {
    # memberOf continua sendo uma fonte segura quando a expansão não está disponível.
}
$payload = [ordered]@{
    username = $env:SENTINEL_AD_USER
    display_name = [string]$user.DisplayName
    email = [string]$user.mail
    dn = [string]$user.DistinguishedName
    groups = @($groups | Select-Object -Unique)
}
$payload | ConvertTo-Json -Compress -Depth 4
"""
        process_env = os.environ.copy()
        process_env.update({
            "SENTINEL_AD_DOMAIN": self.domain,
            "SENTINEL_AD_USER": username,
            "SENTINEL_AD_SERVER": self.dc_server,
        })
        try:
            result = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    script,
                ],
                input=password,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
                env=process_env,
            )
            if result.returncode != 0:
                logger.warning(
                    "Consulta nativa ao AD falhou para %s: %s",
                    username,
                    (result.stderr or result.stdout).strip(),
                )
                return None
            payload = json.loads(result.stdout.lstrip("\ufeff").strip())
            if not payload.get("dn"):
                return None
            payload["groups"] = list(dict.fromkeys(payload.get("groups") or []))
            return payload
        except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
            logger.warning("Erro na consulta nativa ao AD para %s: %s", username, exc)
            return None
    
    def autenticar_usuario(self, username: str, password: str) -> Tuple[bool, Optional[Dict], str]:
        """
        Autentica usuário no AD usando método alternativo (sem MD4)
        
        Returns:
            Tuple[bool, Optional[Dict], str]: (sucesso, dados_usuario, mensagem)
        """
        if not username or not password:
            return False, None, "Usuário e senha são obrigatórios"
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", username) or len(password) > 512:
            return False, None, "Usuário ou senha inválidos"
        
        if not self.server_ip:
            return False, None, "Servidor AD não encontrado"

        if _login_is_limited(username):
            return False, None, "Muitas tentativas. Aguarde 15 minutos antes de tentar novamente"

        # A consulta nativa valida a credencial e retorna OU e grupos na mesma
        # operação, sem colocar a senha na linha de comando.
        user_data = self._buscar_dados_usuario_powershell(username, password)
        
        if not user_data:
            _record_login_failure(username)
            logger.warning("Credencial inválida ou consulta ao AD recusada para %s", username)
            return False, None, "Usuário ou senha inválidos"

        _clear_login_failures(username)
        
        # Contas administrativas legadas continuam autorizadas pela OU. Contas
        # privilegiadas e suportes regionais também podem entrar pelos grupos.
        autorizado_por_ou = self._usuario_na_ou_autorizada(user_data['dn'])
        user_data['groups'] = list(effective_user_groups(
            user_data.get('groups'),
            user_data.get('dn'),
        ))
        autorizado_por_grupo = has_sentinel_login_access(username, user_data.get('groups'))
        if autorizado_por_ou or autorizado_por_grupo:
            origem = "OU administrativa" if autorizado_por_ou else "grupo de segurança"
            logger.info("Usuário %s autorizado por %s", username, origem)
            return True, user_data, "Autenticação bem-sucedida"
        else:
            logger.warning("Usuário %s não possui OU ou grupo autorizado", username)
            return False, None, "Usuário não possui permissão para acessar este sistema"
    
    def _usuario_na_ou_autorizada(self, user_dn: str) -> bool:
        """Verifica se o usuário está na OU autorizada"""
        return is_administrative_ou_dn(user_dn, self.ou_autorizada)
    
    def testar_conexao(self) -> Tuple[bool, str]:
        """Testa o canal usado pelo módulo ActiveDirectory do PowerShell."""
        if not self.server_ip:
            return False, "Servidor AD não encontrado"

        try:
            with socket.create_connection((self.server_ip, 9389), timeout=5):
                pass
            return True, f"Conexão segura com {self.dc_server} ({self.server_ip}) bem-sucedida"
        except OSError:
            logger.exception("Falha ao testar o canal AD Web Services")
            return False, "Não foi possível conectar ao serviço seguro do Active Directory"
    
    def listar_usuarios_ou(self) -> list:
        """A enumeração anônima de usuários foi desativada por segurança."""
        logger.warning("Tentativa de usar a listagem legada de usuários do AD")
        return []

# Instância global
auth_ad = AuthAD()

def verificar_usuario_ad(username: str, password: str) -> Tuple[bool, Optional[Dict], str]:
    """Função helper para verificar usuário"""
    return auth_ad.autenticar_usuario(username, password)

def testar_conexao_ad() -> Tuple[bool, str]:
    """Função helper para testar conexão"""
    return auth_ad.testar_conexao()

def init_auth(app):
    """Inicializa autenticação no Flask app"""
    
    @app.route('/login', methods=['GET', 'POST'])
    def login():
        """Página de login com autenticação AD"""
        from flask import request, render_template, redirect, url_for, flash, session
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
                session.clear()
                user = User(user_info)
                save_user(user)
                login_user(user)
                session.permanent = True
                observe_support_groups(user.groups)
                
                flash(f'Bem-vindo, {user.display_name}!', 'success')
                
                # Redireciona para página solicitada ou dashboard
                next_page = request.args.get('next')
                return redirect(next_page) if is_safe_next_url(next_page) else redirect(url_for('index'))
            else:
                flash(f'Erro de autenticação: {mensagem}', 'error')
        
        return render_template('login.html')
    
    @app.route('/logout', methods=['POST'])
    def logout():
        """Logout do usuário"""
        from flask import redirect, url_for, flash
        from flask_login import logout_user, current_user
        
        if current_user.is_authenticated:
            username = current_user.id
            logout_user()
            remove_user(username)
            flash('Logout realizado com sucesso', 'info')
        
        return redirect(url_for('login'))
