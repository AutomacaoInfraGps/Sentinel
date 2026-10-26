"""Grava acessos no cofre do Sentinel sem argumentos de senha ou eco no terminal."""
import argparse
from getpass import getpass
from core.secret_store import JsonSecretStore, SecretStoreError


def main():
    parser = argparse.ArgumentParser(description='Configurar acesso da Revisao de Acessos no cofre do Sentinel.')
    parser.add_argument('sistema', choices=('zabbix', 'grafana', 'admanager', 'fortianalyzer', 'fortimanager'))
    args = parser.parse_args()
    username = getpass('Usuario (entrada oculta): ').strip()
    password = getpass('Senha (entrada oculta): ')
    if not username or not password:
        parser.error('Usuario e senha nao podem ficar vazios.')
    try:
        JsonSecretStore().put_many({f'access-review/{args.sistema}/username': username,
                                   f'access-review/{args.sistema}/password': password})
    except SecretStoreError:
        parser.exit(1, 'Nao foi possivel atualizar o cofre do Sentinel.\n')
    print('Acesso salvo no cofre para a conta Windows atual.')


if __name__ == '__main__':
    main()
