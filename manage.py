#!/usr/bin/env python3
"""
Interface de Linha de Comando para Gerenciamento do Sistema
Permite gerenciar servidores, configurações e executar operações de forma intuitiva
"""

import argparse
import sys
from pathlib import Path
from gerenciar_servidores import GerenciadorServidores
from config import PROJECT_ROOT

def cmd_listar_servidores(args):
    """Lista todos os servidores configurados"""
    gerenciador = GerenciadorServidores()
    servidores = gerenciador.listar_servidores(mostrar_inativos=args.todos)
    
    if not servidores:
        print("📭 Nenhum servidor configurado")
        return
    
    print(f"\n📋 Servidores configurados ({len(servidores)}):")
    print("-" * 80)
    
    for servidor in servidores:
        status = "🟢 ATIVO" if servidor.get("ativo", True) else "🔴 INATIVO"
        print(f"{status} {servidor['id']}")
        print(f"   Nome: {servidor['nome']}")
        print(f"   Tipo: {servidor['tipo'].upper()}")
        print(f"   IP: {servidor['ip']}:{servidor.get('porta', 443)}")
        print(f"   Usuário: {servidor['usuario']}")
        print(f"   Grupo: {servidor.get('grupo', 'N/A')}")
        if servidor.get('descricao'):
            print(f"   Descrição: {servidor['descricao']}")
        print()

def cmd_adicionar_servidor(args):
    """Adiciona um novo servidor"""
    gerenciador = GerenciadorServidores()
    
    # Coleta informações se não fornecidas
    nome = args.nome or input("📝 Nome do servidor: ")
    tipo = args.tipo or input("🔧 Tipo (idrac/ilo): ").lower()
    ip = args.ip or input("🌐 IP do servidor: ")
    usuario = args.usuario or input("👤 Usuário: ")
    senha = args.senha or input("🔐 Senha: ")
    
    # Informações opcionais
    grupo = args.grupo or "regionais"
    descricao = args.descricao or ""
    porta = args.porta or 443
    timeout = args.timeout or 10
    
    # Adiciona o servidor
    sucesso = gerenciador.adicionar_servidor(
        nome=nome,
        tipo=tipo,
        ip=ip,
        usuario=usuario,
        senha=senha,
        grupo=grupo,
        descricao=descricao,
        porta=porta,
        timeout=timeout
    )
    
    if sucesso:
        # Testa conectividade se solicitado
        if args.testar:
            print("\n🔍 Testando conectividade...")
            servidor_id = gerenciador._gerar_id_servidor(nome)
            sucesso_teste, mensagem = gerenciador.testar_conectividade(servidor_id)
            
            if sucesso_teste:
                print(f"✅ {mensagem}")
            else:
                print(f"⚠️ {mensagem}")
        
        # Atualiza arquivo legado
        gerenciador.gerar_arquivo_conexoes_legado()

def cmd_remover_servidor(args):
    """Remove um servidor"""
    gerenciador = GerenciadorServidores()
    
    identificador = args.identificador
    if not identificador:
        # Lista servidores para escolha
        servidores = gerenciador.listar_servidores()
        if not servidores:
            print("📭 Nenhum servidor configurado")
            return
        
        print("\n📋 Servidores disponíveis:")
        for i, servidor in enumerate(servidores, 1):
            print(f"  {i}. {servidor['nome']} ({servidor['id']})")
        
        try:
            escolha = int(input("\n🔢 Escolha o número do servidor: ")) - 1
            identificador = servidores[escolha]['id']
        except (ValueError, IndexError):
            print("❌ Escolha inválida")
            return
    
    # Confirmação
    if not args.force:
        confirmacao = input(f"⚠️ Confirma remoção do servidor '{identificador}'? (s/N): ")
        if confirmacao.lower() not in ['s', 'sim', 'y', 'yes']:
            print("❌ Operação cancelada")
            return
    
    # Remove o servidor
    sucesso = gerenciador.remover_servidor(identificador)
    
    if sucesso:
        # Atualiza arquivo legado
        gerenciador.gerar_arquivo_conexoes_legado()

def cmd_editar_servidor(args):
    """Edita um servidor existente"""
    gerenciador = GerenciadorServidores()
    
    identificador = args.identificador
    if not identificador:
        print("❌ ID ou nome do servidor é obrigatório")
        return
    
    # Coleta campos para edição
    campos = {}
    
    if args.nome:
        campos['nome'] = args.nome
    if args.tipo:
        campos['tipo'] = args.tipo.lower()
    if args.ip:
        campos['ip'] = args.ip
    if args.usuario:
        campos['usuario'] = args.usuario
    if args.senha:
        campos['senha'] = args.senha
    if args.grupo:
        campos['grupo'] = args.grupo
    if args.descricao:
        campos['descricao'] = args.descricao
    if args.porta:
        campos['porta'] = args.porta
    if args.timeout:
        campos['timeout'] = args.timeout
    if args.ativo is not None:
        campos['ativo'] = args.ativo
    
    if not campos:
        print("❌ Nenhum campo fornecido para edição")
        return
    
    # Edita o servidor
    sucesso = gerenciador.editar_servidor(identificador, **campos)
    
    if sucesso:
        # Atualiza arquivo legado
        gerenciador.gerar_arquivo_conexoes_legado()

def cmd_testar_servidor(args):
    """Testa conectividade com um servidor"""
    gerenciador = GerenciadorServidores()
    
    identificador = args.identificador
    if not identificador:
        # Lista servidores para escolha
        servidores = gerenciador.listar_servidores()
        if not servidores:
            print("📭 Nenhum servidor configurado")
            return
        
        print("\n📋 Servidores disponíveis:")
        for i, servidor in enumerate(servidores, 1):
            print(f"  {i}. {servidor['nome']} ({servidor['id']})")
        
        try:
            escolha = int(input("\n🔢 Escolha o número do servidor: ")) - 1
            identificador = servidores[escolha]['id']
        except (ValueError, IndexError):
            print("❌ Escolha inválida")
            return
    
    print(f"\n🔍 Testando conectividade com '{identificador}'...")
    sucesso, mensagem = gerenciador.testar_conectividade(identificador)
    
    if sucesso:
        print(f"✅ {mensagem}")
    else:
        print(f"❌ {mensagem}")

def cmd_testar_todos(args):
    """Testa conectividade com todos os servidores"""
    gerenciador = GerenciadorServidores()
    servidores = gerenciador.listar_servidores()
    
    if not servidores:
        print("📭 Nenhum servidor configurado")
        return
    
    print(f"\n🔍 Testando conectividade com {len(servidores)} servidores...")
    print("-" * 60)
    
    sucessos = 0
    falhas = 0
    
    for servidor in servidores:
        print(f"🔍 {servidor['nome']} ({servidor['ip']})... ", end="")
        sucesso, mensagem = gerenciador._testar_servidor(servidor)
        
        if sucesso:
            print("✅ OK")
            sucessos += 1
        else:
            print(f"❌ {mensagem}")
            falhas += 1
    
    print("-" * 60)
    print(f"📊 Resultado: {sucessos} sucessos, {falhas} falhas")

def cmd_exportar(args):
    """Exporta configuração para backup"""
    gerenciador = GerenciadorServidores()
    arquivo = args.arquivo or f"backup_servidores_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    gerenciador.exportar_configuracao(arquivo)

def cmd_importar(args):
    """Importa configuração de backup"""
    gerenciador = GerenciadorServidores()
    
    if not Path(args.arquivo).exists():
        print(f"❌ Arquivo não encontrado: {args.arquivo}")
        return
    
    # Confirmação
    if not args.force:
        confirmacao = input("⚠️ Esta operação substituirá a configuração atual. Continuar? (s/N): ")
        if confirmacao.lower() not in ['s', 'sim', 'y', 'yes']:
            print("❌ Operação cancelada")
            return
    
    sucesso = gerenciador.importar_configuracao(args.arquivo)
    if sucesso:
        gerenciador.gerar_arquivo_conexoes_legado()

def cmd_sincronizar(args):
    """Sincroniza com arquivo legado"""
    gerenciador = GerenciadorServidores()
    gerenciador.gerar_arquivo_conexoes_legado()
    print("🔄 Sincronização concluída")

def cmd_status(args):
    """Mostra status geral do sistema"""
    gerenciador = GerenciadorServidores()
    
    print("\n📊 Status do Sistema")
    print("=" * 30)
    
    # Verifica arquivos
    env_file = PROJECT_ROOT / "environment.json"
    print(f"📁 Arquivos:")
    print(f"   environment.json: {'✅' if env_file.exists() else '❌'}")
    print(f"   servidores.json: {'✅' if gerenciador.arquivo_servidores.exists() else '❌'}")
    print(f"   Conexoes.txt: {'✅' if gerenciador.arquivo_conexoes_legado.exists() else '❌'}")
    
    try:
        # Estatísticas reais com verificação de conectividade
        stats = gerenciador.obter_estatisticas_reais()
        
        print(f"\n🖥️ Servidores:")
        print(f"   📋 Total: {stats['total_servidores']}")
        print(f"   🔧 Configurados: {stats['servidores_configurados']}")
        print(f"   🟢 Online: {stats['servidores_online']}")
        print(f"   🔴 Offline: {stats['servidores_offline']}")
        print(f"   ⏸️ Inativos: {stats['servidores_inativos']}")
        
        # Mostra servidores com problemas
        if stats['servidores_offline'] > 0:
            print(f"\n⚠️ Servidores com Problemas:")
            status_detalhado = stats.get('status_detalhado', {})
            for servidor_id, status in status_detalhado.items():
                if not status.get('online', False) and status.get('status') != 'inativo':
                    print(f"   ❌ {servidor_id}: {status.get('mensagem', 'Erro desconhecido')}")
        
        # Tipos de servidor
        if stats.get('tipos'):
            print(f"\n🔧 Por Tipo:")
            for tipo, quantidade in stats['tipos'].items():
                print(f"   {tipo}: {quantidade}")
        
        # Status geral
        if stats['servidores_offline'] == 0 and stats['servidores_configurados'] > 0:
            print(f"\n✅ Sistema OK - Todos os servidores online!")
        elif stats['servidores_configurados'] == 0:
            print(f"\n⚠️ Nenhum servidor configurado")
        else:
            print(f"\n⚠️ {stats['servidores_offline']} servidor(es) com problemas")
    
    except Exception as e:
        print(f"\n❌ Erro ao verificar status: {e}")
        # Fallback para método simples
        servidores = gerenciador.listar_servidores(mostrar_inativos=True)
        ativos = len([s for s in servidores if s.get("ativo", True)])
        inativos = len(servidores) - ativos
        
        print(f"\n🖥️ Servidores (modo básico):")
        print(f"   📋 Total: {len(servidores)}")
        print(f"   🟢 Ativos: {ativos}")
        print(f"   🔴 Inativos: {inativos}")
    
    print(f"\n💡 Comandos úteis:")
    print(f"   python manage.py test-all     # Testar conectividade")
    print(f"   python iniciar_web.py         # Interface web")
    print(f"   python manage.py --help       # Ajuda completa")

def main():
    """Função principal da CLI"""
    parser = argparse.ArgumentParser(
        description="Sistema de Gerenciamento de Servidores",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos de uso:
  python manage.py list                              # Lista servidores
  python manage.py add --nome "Servidor1" --ip "10.1.1.1" --tipo idrac
  python manage.py remove servidor1                  # Remove servidor
  python manage.py test servidor1                    # Testa conectividade
  python manage.py test-all                          # Testa todos
  python manage.py export backup.json               # Exporta configuração
  python manage.py import backup.json               # Importa configuração
        """
    )
    
    subparsers = parser.add_subparsers(dest='comando', help='Comandos disponíveis')
    
    # Comando: list
    parser_list = subparsers.add_parser('list', help='Lista servidores')
    parser_list.add_argument('--todos', action='store_true', help='Inclui servidores inativos')
    parser_list.set_defaults(func=cmd_listar_servidores)
    
    # Comando: add
    parser_add = subparsers.add_parser('add', help='Adiciona servidor')
    parser_add.add_argument('--nome', help='Nome do servidor')
    parser_add.add_argument('--tipo', choices=['idrac', 'ilo'], help='Tipo do servidor')
    parser_add.add_argument('--ip', help='IP do servidor')
    parser_add.add_argument('--usuario', help='Usuário')
    parser_add.add_argument('--senha', help='Senha')
    parser_add.add_argument('--grupo', default='regionais', help='Grupo do servidor')
    parser_add.add_argument('--descricao', help='Descrição do servidor')
    parser_add.add_argument('--porta', type=int, default=443, help='Porta (padrão: 443)')
    parser_add.add_argument('--timeout', type=int, default=10, help='Timeout (padrão: 10)')
    parser_add.add_argument('--testar', action='store_true', help='Testa conectividade após adicionar')
    parser_add.set_defaults(func=cmd_adicionar_servidor)
    
    # Comando: remove
    parser_remove = subparsers.add_parser('remove', help='Remove servidor')
    parser_remove.add_argument('identificador', nargs='?', help='ID ou nome do servidor')
    parser_remove.add_argument('--force', action='store_true', help='Remove sem confirmação')
    parser_remove.set_defaults(func=cmd_remover_servidor)
    
    # Comando: edit
    parser_edit = subparsers.add_parser('edit', help='Edita servidor')
    parser_edit.add_argument('identificador', help='ID ou nome do servidor')
    parser_edit.add_argument('--nome', help='Novo nome')
    parser_edit.add_argument('--tipo', choices=['idrac', 'ilo'], help='Novo tipo')
    parser_edit.add_argument('--ip', help='Novo IP')
    parser_edit.add_argument('--usuario', help='Novo usuário')
    parser_edit.add_argument('--senha', help='Nova senha')
    parser_edit.add_argument('--grupo', help='Novo grupo')
    parser_edit.add_argument('--descricao', help='Nova descrição')
    parser_edit.add_argument('--porta', type=int, help='Nova porta')
    parser_edit.add_argument('--timeout', type=int, help='Novo timeout')
    parser_edit.add_argument('--ativo', type=bool, help='Ativo (true/false)')
    parser_edit.set_defaults(func=cmd_editar_servidor)
    
    # Comando: test
    parser_test = subparsers.add_parser('test', help='Testa conectividade')
    parser_test.add_argument('identificador', nargs='?', help='ID ou nome do servidor')
    parser_test.set_defaults(func=cmd_testar_servidor)
    
    # Comando: test-all
    parser_test_all = subparsers.add_parser('test-all', help='Testa todos os servidores')
    parser_test_all.set_defaults(func=cmd_testar_todos)
    
    # Comando: export
    parser_export = subparsers.add_parser('export', help='Exporta configuração')
    parser_export.add_argument('arquivo', nargs='?', help='Arquivo de destino')
    parser_export.set_defaults(func=cmd_exportar)
    
    # Comando: import
    parser_import = subparsers.add_parser('import', help='Importa configuração')
    parser_import.add_argument('arquivo', help='Arquivo de origem')
    parser_import.add_argument('--force', action='store_true', help='Importa sem confirmação')
    parser_import.set_defaults(func=cmd_importar)
    
    # Comando: sync
    parser_sync = subparsers.add_parser('sync', help='Sincroniza com arquivo legado')
    parser_sync.set_defaults(func=cmd_sincronizar)
    
    # Comando: status
    parser_status = subparsers.add_parser('status', help='Mostra status do sistema')
    parser_status.set_defaults(func=cmd_status)
    
    # Parse argumentos
    args = parser.parse_args()
    
    if not args.comando:
        parser.print_help()
        return
    
    # Executa comando
    try:
        args.func(args)
    except KeyboardInterrupt:
        print("\n❌ Operação cancelada pelo usuário")
    except Exception as e:
        print(f"❌ Erro inesperado: {e}")
        if '--debug' in sys.argv:
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    main()