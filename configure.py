#!/usr/bin/env python3
"""
Wizard de Configuração Inicial do Sistema
Interface interativa para configurar o sistema pela primeira vez
"""

import json
import os
import sys
from pathlib import Path
from datetime import datetime
from gerenciar_servidores import GerenciadorServidores
from config import PROJECT_ROOT, ENV_CONFIG, ENVIRONMENT_FILE

class WizardConfiguracao:
    """Wizard interativo para configuração inicial"""
    
    def __init__(self):
        self.gerenciador = GerenciadorServidores()
        self.configuracao = {}
        
    def executar(self):
        """Executa o wizard completo"""
        print("🧙‍♂️ Wizard de Configuração Inicial")
        print("=" * 50)
        print("Este assistente irá configurar o sistema pela primeira vez.")
        print("Você pode pressionar Ctrl+C a qualquer momento para cancelar.\n")
        
        try:
            # Etapa 1: Verificação inicial
            if not self._verificacao_inicial():
                return False
            
            # Etapa 2: Configuração de credenciais
            if not self._configurar_credenciais():
                return False
            
            # Etapa 3: Configuração de servidores
            if not self._configurar_servidores():
                return False
            
            # Etapa 4: Teste de conectividade
            if not self._testar_configuracao():
                return False
            
            # Etapa 5: Finalização
            self._finalizar_configuracao()
            
            return True
            
        except KeyboardInterrupt:
            print("\n❌ Configuração cancelada pelo usuário")
            return False
        except Exception as e:
            print(f"\n❌ Erro durante configuração: {e}")
            return False
    
    def _verificacao_inicial(self) -> bool:
        """Verifica o estado atual do sistema"""
        print("🔍 Etapa 1: Verificação Inicial")
        print("-" * 30)
        
        # Verifica se já existe configuração
        env_file = ENVIRONMENT_FILE
        servidores_file = PROJECT_ROOT / "servidores.json"
        
        tem_env = env_file.exists()
        tem_servidores = servidores_file.exists()
        
        print(f"📄 environment.json: {'✅ Existe' if tem_env else '❌ Não encontrado'}")
        print(f"📄 servidores.json: {'✅ Existe' if tem_servidores else '❌ Não encontrado'}")
        
        if tem_env and tem_servidores:
            resposta = input("\n⚠️ Configuração existente detectada. Reconfigurar? (s/N): ")
            if resposta.lower() not in ['s', 'sim', 'y', 'yes']:
                print("✅ Mantendo configuração existente")
                return False
        
        print("✅ Prosseguindo com configuração\n")
        return True
    
    def _configurar_credenciais(self) -> bool:
        """Configura credenciais dos sistemas"""
        print("🔐 Etapa 2: Configuração de Credenciais")
        print("-" * 40)
        
        # Carrega configuração existente se houver
        env_file = ENVIRONMENT_FILE
        if env_file.exists():
            try:
                with open(env_file, 'r', encoding='utf-8') as f:
                    self.configuracao = json.load(f)
            except:
                self.configuracao = {}
        
        # Configuração do servidor NAOS
        print("\n🖥️ Servidor NAOS:")
        naos_config = self.configuracao.get("naos_server", {})
        
        ip_naos = input(f"   IP [{naos_config.get('ip', '192.0.2.10')}]: ").strip()
        if not ip_naos:
            ip_naos = naos_config.get('ip', '192.0.2.10')
        
        usuario_naos = input(f"   Usuário [{naos_config.get('usuario', 'EXEMPLO\\\\admin')}]: ").strip()
        if not usuario_naos:
            usuario_naos = naos_config.get('usuario', 'EXEMPLO\\admin')
        
        senha_naos = input("   Senha: ").strip()
        if not senha_naos:
            senha_naos = naos_config.get('senha', '')
        
        # Configuração do UniFi Controller
        print("\n📡 UniFi Controller:")
        unifi_config = self.configuracao.get("unifi_controller", {})
        
        host_unifi = input(f"   Host [{unifi_config.get('host', '198.51.100.10')}]: ").strip()
        if not host_unifi:
            host_unifi = unifi_config.get('host', '198.51.100.10')
        
        porta_unifi = input(f"   Porta [{unifi_config.get('port', 8443)}]: ").strip()
        if not porta_unifi:
            porta_unifi = unifi_config.get('port', 8443)
        else:
            porta_unifi = int(porta_unifi)
        
        usuario_unifi = input(f"   Usuário [{unifi_config.get('username', 'admin')}]: ").strip()
        if not usuario_unifi:
            usuario_unifi = unifi_config.get('username', 'admin')
        
        senha_unifi = input("   Senha: ").strip()
        if not senha_unifi:
            senha_unifi = unifi_config.get('password', '')
        
        # Configuração do GPS Amigo
        print("\n🗺️ GPS Amigo:")
        gps_config = self.configuracao.get("gps_amigo", {})
        
        url_gps = input(f"   URL [{gps_config.get('url', 'https://gpsamigo.com.br/login.php')}]: ").strip()
        if not url_gps:
            url_gps = gps_config.get('url', 'https://gpsamigo.com.br/login.php')

        # Configuração do AppGate
        print("\n🔐 AppGate:")
        appgate_config = self.configuracao.get("appgate", {})

        url_appgate = input(f"   URL [{appgate_config.get('url', 'https://firewall.example.local/ng/system/dashboard/1')}]: ").strip()
        if not url_appgate:
            url_appgate = appgate_config.get('url', 'https://firewall.example.local/ng/system/dashboard/1')

        usuario_appgate = input(f"   Usuário [{appgate_config.get('username', 'admin')}]: ").strip()
        if not usuario_appgate:
            usuario_appgate = appgate_config.get('username', 'admin')

        senha_appgate = input("   Senha: ").strip()
        if not senha_appgate:
            senha_appgate = appgate_config.get('password', '')
        
        # Monta configuração
        self.configuracao = {
            **self.configuracao,
            "naos_server": {
                "ip": ip_naos,
                "usuario": usuario_naos,
                "senha": senha_naos
            },
            "unifi_controller": {
                "host": host_unifi,
                "port": porta_unifi,
                "username": usuario_unifi,
                "password": senha_unifi
            },
            "gps_amigo": {
                "url": url_gps
            },
            "appgate": {
                "url": url_appgate,
                "username": usuario_appgate,
                "password": senha_appgate
            },
            "timeouts": {
                "connection_timeout": 10,
                "max_retries": 3
            },
            "cleanup": {
                "remove_temp_files": True,
                "keep_logs": True
            }
        }
        
        # Salva configuração
        try:
            with open(env_file, 'w', encoding='utf-8') as f:
                json.dump(self.configuracao, f, indent=2, ensure_ascii=False)
            print("✅ Credenciais salvas\n")
            return True
        except Exception as e:
            print(f"❌ Erro ao salvar credenciais: {e}\n")
            return False
    
    def _configurar_servidores(self) -> bool:
        """Configura servidores iDRAC/iLO"""
        print("🖥️ Etapa 3: Configuração de Servidores")
        print("-" * 40)
        
        # Verifica se já existem servidores
        servidores_existentes = self.gerenciador.listar_servidores()
        if servidores_existentes:
            print(f"📋 {len(servidores_existentes)} servidores já configurados:")
            for servidor in servidores_existentes:
                print(f"   • {servidor['nome']} ({servidor['tipo'].upper()}) - {servidor['ip']}")
            
            resposta = input("\n➕ Adicionar mais servidores? (s/N): ")
            if resposta.lower() not in ['s', 'sim', 'y', 'yes']:
                print("✅ Mantendo servidores existentes\n")
                return True
        
        print("\n📝 Adicione os servidores iDRAC/iLO:")
        print("   (Deixe o nome em branco para finalizar)")
        
        while True:
            print(f"\n--- Servidor #{len(self.gerenciador.listar_servidores()) + 1} ---")
            
            nome = input("Nome do servidor: ").strip()
            if not nome:
                break
            
            # Tipo do servidor
            while True:
                tipo = input("Tipo (idrac/ilo): ").strip().lower()
                if tipo in ['idrac', 'ilo']:
                    break
                print("❌ Tipo inválido. Use 'idrac' ou 'ilo'")
            
            # IP do servidor
            while True:
                ip = input("IP do servidor: ").strip()
                if self._validar_ip_basico(ip):
                    break
                print("❌ IP inválido")
            
            # Credenciais
            usuario = input("Usuário: ").strip()
            senha = input("Senha: ").strip()
            
            # Informações opcionais
            grupo = input("Grupo [regionais]: ").strip() or "regionais"
            descricao = input("Descrição (opcional): ").strip()
            
            # Adiciona o servidor
            sucesso = self.gerenciador.adicionar_servidor(
                nome=nome,
                tipo=tipo,
                ip=ip,
                usuario=usuario,
                senha=senha,
                grupo=grupo,
                descricao=descricao
            )
            
            if not sucesso:
                resposta = input("❌ Erro ao adicionar servidor. Tentar novamente? (s/N): ")
                if resposta.lower() not in ['s', 'sim', 'y', 'yes']:
                    break
        
        # Verifica se pelo menos um servidor foi configurado
        servidores_finais = self.gerenciador.listar_servidores()
        if not servidores_finais:
            print("⚠️ Nenhum servidor configurado. O sistema funcionará com funcionalidade limitada.")
        else:
            print(f"✅ {len(servidores_finais)} servidores configurados")
        
        print()
        return True
    
    def _testar_configuracao(self) -> bool:
        """Testa a configuração"""
        print("🔍 Etapa 4: Teste de Configuração")
        print("-" * 35)
        
        resposta = input("Executar testes de conectividade? (S/n): ")
        if resposta.lower() in ['n', 'no', 'nao', 'não']:
            print("⏭️ Pulando testes\n")
            return True
        
        print("\n🔍 Testando conectividade com servidores...")
        
        servidores = self.gerenciador.listar_servidores()
        if not servidores:
            print("📭 Nenhum servidor para testar")
            return True
        
        sucessos = 0
        falhas = 0
        
        for servidor in servidores:
            print(f"   🔍 {servidor['nome']} ({servidor['ip']})... ", end="")
            sucesso, mensagem = self.gerenciador._testar_servidor(servidor)
            
            if sucesso:
                print("✅ OK")
                sucessos += 1
            else:
                print(f"❌ {mensagem}")
                falhas += 1
        
        print(f"\n📊 Resultado: {sucessos} sucessos, {falhas} falhas")
        
        if falhas > 0:
            resposta = input("⚠️ Alguns testes falharam. Continuar mesmo assim? (s/N): ")
            if resposta.lower() not in ['s', 'sim', 'y', 'yes']:
                print("❌ Configuração interrompida")
                return False
        
        print("✅ Testes concluídos\n")
        return True
    
    def _finalizar_configuracao(self):
        """Finaliza a configuração"""
        print("🎉 Etapa 5: Finalização")
        print("-" * 25)
        
        # Gera arquivo legado para compatibilidade
        self.gerenciador.gerar_arquivo_conexoes_legado()
        
        # Cria diretórios necessários
        from config import ensure_directories
        ensure_directories()
        
        print("✅ Configuração concluída com sucesso!")
        print("\n📋 Próximos passos:")
        print("   1. Execute: python validate_system.py")
        print("   2. Execute: python executar_tudo.py")
        print("   3. Acesse: output/dashboard_final.html")
        
        print("\n🔧 Comandos úteis:")
        print("   python manage.py list              # Lista servidores")
        print("   python manage.py add               # Adiciona servidor")
        print("   python manage.py test-all          # Testa conectividade")
        print("   python manage.py status            # Status do sistema")
        
        print(f"\n📁 Arquivos de configuração:")
        print(f"   environment.json    # Credenciais dos sistemas")
        print(f"   servidores.json     # Lista de servidores")
        print(f"   Conexoes.txt        # Formato legado (compatibilidade)")
    
    def _validar_ip_basico(self, ip: str) -> bool:
        """Validação básica de IP"""
        try:
            partes = ip.split('.')
            if len(partes) != 4:
                return False
            for parte in partes:
                num = int(parte)
                if not 0 <= num <= 255:
                    return False
            return True
        except:
            return False


def main():
    """Função principal"""
    print("🧙‍♂️ Wizard de Configuração do Sistema de Automação")
    print("=" * 60)
    
    # Verifica se é primeira execução
    if len(sys.argv) > 1 and sys.argv[1] == '--force':
        print("🔄 Modo forçado: reconfigurando sistema...")
    else:
        # Verifica se já está configurado
        env_file = PROJECT_ROOT / "environment.json"
        servidores_file = PROJECT_ROOT / "servidores.json"
        
        if env_file.exists() and servidores_file.exists():
            print("✅ Sistema já configurado!")
            print("\nPara reconfigurar, execute:")
            print("   python configure.py --force")
            print("\nPara gerenciar servidores:")
            print("   python manage.py list")
            return
    
    # Executa wizard
    wizard = WizardConfiguracao()
    sucesso = wizard.executar()
    
    if sucesso:
        print("\n🎉 Sistema configurado com sucesso!")
    else:
        print("\n❌ Configuração não concluída")
        print("Execute novamente quando estiver pronto.")


if __name__ == "__main__":
    main()