#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Script de linha de comando para gerenciar VMs
Uso: python manage_vms.py [comando] [argumentos]

Comandos disponíveis:
- list: Lista todas as VMs
- add: Adiciona uma nova VM
- remove: Remove uma VM
- update-regional: Atualiza a regional de uma VM
- cli: Interface interativa
"""

import sys
import argparse
from gerenciar_vms import GerenciadorVMsLocal

def main():
    parser = argparse.ArgumentParser(description='Gerenciador de VMs')
    subparsers = parser.add_subparsers(dest='comando', help='Comandos disponíveis')
    
    # Comando list
    subparsers.add_parser('list', help='Lista todas as VMs')
    
    # Comando add
    parser_add = subparsers.add_parser('add', help='Adiciona uma nova VM')
    parser_add.add_argument('--name', required=True, help='Nome da VM')
    parser_add.add_argument('--ip', required=True, help='IP da VM')
    parser_add.add_argument('--username', required=True, help='Usuário da VM')
    parser_add.add_argument('--password', required=True, help='Senha da VM')
    parser_add.add_argument('--regional', required=True, help='Regional da VM (ex: PARANA, SAO_PAULO)')
    parser_add.add_argument('--description', default='', help='Descrição da VM')
    
    # Comando remove
    parser_remove = subparsers.add_parser('remove', help='Remove uma VM')
    parser_remove.add_argument('vm_id', help='ID ou nome da VM')
    
    # Comando update-regional
    parser_update = subparsers.add_parser('update-regional', help='Atualiza a regional de uma VM')
    parser_update.add_argument('vm_id', help='ID ou nome da VM')
    parser_update.add_argument('regional', help='Nova regional (ex: PARANA, SAO_PAULO)')
    
    # Comando cli
    subparsers.add_parser('cli', help='Interface interativa')
    
    args = parser.parse_args()
    
    if not args.comando:
        parser.print_help()
        return
    
    gerenciador = GerenciadorVMsLocal()
    
    if args.comando == 'list':
        gerenciador.listar_vms()
    
    elif args.comando == 'add':
        gerenciador.adicionar_vm(
            args.name, 
            args.ip, 
            args.username, 
            args.password, 
            args.regional, 
            args.description
        )
    
    elif args.comando == 'remove':
        gerenciador.remover_vm(args.vm_id)
    
    elif args.comando == 'update-regional':
        gerenciador.atualizar_regional_vm(args.vm_id, args.regional)
    
    elif args.comando == 'cli':
        from gerenciar_vms import gerenciar_vms_cli
        gerenciar_vms_cli()

if __name__ == "__main__":
    main()