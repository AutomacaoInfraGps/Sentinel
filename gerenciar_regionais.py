"""
Gerenciador de Regionais e Servidores
Estrutura hierárquica: Regional → Servidores (iDRAC/ILO)
"""

import json
import os
from typing import Dict, List, Optional
from datetime import datetime

class GerenciadorRegionais:
    """Gerencia a estrutura hierárquica de regionais e servidores"""
    
    def __init__(self, arquivo_regionais="estrutura_regionais.json"):
        self.arquivo_regionais = arquivo_regionais
        self.regionais = self._carregar_regionais()
    
    def _carregar_regionais(self) -> Dict:
        """Carrega a estrutura de regionais do arquivo"""
        if os.path.exists(self.arquivo_regionais):
            with open(self.arquivo_regionais, 'r', encoding='utf-8') as f:
                return json.load(f)
        else:
            return {"regionais": {}, "configuracao": {"versao": "2.0"}}
    
    def salvar_regionais(self):
        """Salva a estrutura de regionais no arquivo"""
        self.regionais["configuracao"]["ultima_atualizacao"] = datetime.now().isoformat()
        print("SALVANDO EM:", os.path.abspath(self.arquivo_regionais))  # << ADICIONA ISSO  
        with open(self.arquivo_regionais, 'w', encoding='utf-8') as f:
            json.dump(self.regionais, f, indent=2, ensure_ascii=False)
    
    def listar_regionais(self) -> List[str]:
        """Lista todas as regionais"""
        return list(self.regionais.get("regionais", {}).keys())
    
    def obter_regional(self, codigo_regional: str) -> Optional[Dict]:
        """Obtém informações de uma regional específica"""
        return self.regionais.get("regionais", {}).get(codigo_regional)
    
    def adicionar_regional(self, codigo: str, nome: str, descricao: str = ""):
        """Adiciona uma nova regional"""
        if "regionais" not in self.regionais:
            self.regionais["regionais"] = {}
        
        self.regionais["regionais"][codigo] = {
            "nome": nome,
            "descricao": descricao,
            "servidores": []
        }
        self.salvar_regionais()

    def remover_regional(self, codigo_regional: str):
        """Remove uma regional do sistema e salva no arquivo"""
        codigo_regional = codigo_regional.upper()

        if codigo_regional not in self.regionais.get("regionais", {}):
            return False, "Regional não existe"

        # Remove do dicionário em memória
        del self.regionais["regionais"][codigo_regional]

        # Salva no arquivo estrutura_regionais.json
        self.salvar_regionais()

        return True, "Regional removida com sucesso"
    
    
    
    def adicionar_servidor(self, codigo_regional: str, servidor: Dict):
        """Adiciona um servidor a uma regional"""
        if codigo_regional not in self.regionais.get("regionais", {}):
            raise ValueError(f"Regional {codigo_regional} não encontrada")
        
        # Validação básica do servidor
        campos_obrigatorios = ["id", "nome", "tipo", "ip", "usuario", "senha"]
        for campo in campos_obrigatorios:
            if campo not in servidor:
                raise ValueError(f"Campo obrigatório '{campo}' não encontrado")
        
        # Adiciona campos padrão se não existirem
        servidor.setdefault("porta", 443)
        servidor.setdefault("timeout", 10)
        servidor.setdefault("ativo", True)
        
        self.regionais["regionais"][codigo_regional]["servidores"].append(servidor)
        self.salvar_regionais()
        
    def remover_servidor(self, codigo_regional: str, id_servidor: str):
        """Remove um servidor de uma regional"""
        codigo_regional = codigo_regional.upper()

        regional = self.regionais.get("regionais", {}).get(codigo_regional)
        if not regional:
            return False, "Regional não encontrada"

        servidores = regional.get("servidores", [])

        servidor_encontrado = None
        for s in servidores:
            if s.get("id") == id_servidor:
                servidor_encontrado = s
                break

        if not servidor_encontrado:
            return False, "Servidor não encontrado"

        servidores.remove(servidor_encontrado)
        self.salvar_regionais()

        return True, f"Servidor {servidor_encontrado.get('nome')} removido com sucesso"
    
    def listar_servidores_regional(self, codigo_regional: str) -> List[Dict]:
        """Lista todos os servidores de uma regional"""
        regional = self.obter_regional(codigo_regional)
        if regional:
            return regional.get("servidores", [])
        return []
    
    def obter_servidor(self, codigo_regional: str, id_servidor: str) -> Optional[Dict]:
        """Obtém um servidor específico de uma regional"""
        servidores = self.listar_servidores_regional(codigo_regional)
        for servidor in servidores:
            if servidor.get("id") == id_servidor:
                return servidor
        return None
    
    def atualizar_servidor(self, codigo_regional: str, id_servidor: str, novos_dados: Dict):
        """Atualiza um servidor existente dentro de uma regional e salva no arquivo"""
        codigo_regional = codigo_regional.upper()

        regional = self.regionais.get("regionais", {}).get(codigo_regional)
        if not regional:
            raise ValueError("Regional não encontrada")

        servidores = regional.get("servidores", [])

        for i, servidor in enumerate(servidores):
            if servidor.get("id") == id_servidor:
                # Atualiza os campos existentes
                servidores[i].update(novos_dados)

                # Salva no JSON
                self.salvar_regionais()
                return True

        raise ValueError("Servidor não encontrado")


    def listar_todos_servidores(self) -> List[Dict]:
        """Lista todos os servidores de todas as regionais"""
        todos_servidores = []
        
        for codigo_regional, regional in self.regionais.get("regionais", {}).items():
            for servidor in regional.get("servidores", []):
                servidor_completo = servidor.copy()
                servidor_completo["regional"] = codigo_regional
                servidor_completo["nome_regional"] = regional.get("nome", codigo_regional)
                todos_servidores.append(servidor_completo)
        
        return todos_servidores
    
    
    def migrar_estrutura_antiga(self, arquivo_antigo="servidores.json"):
        """Migra da estrutura antiga (servidores.json) para a nova estrutura"""
        if not os.path.exists(arquivo_antigo):
            print(f"Arquivo {arquivo_antigo} não encontrado")
            return
        
        with open(arquivo_antigo, 'r', encoding='utf-8') as f:
            dados_antigos = json.load(f)
        
        print("🔄 Migrando estrutura antiga...")
        
        for servidor in dados_antigos.get("servidores", []):
            # Extrai o código da regional do nome
            nome = servidor.get("nome", "")
            
            if nome.startswith("RG_"):
                # Converte nome para código da regional
                codigo_regional = nome.replace(" ", "_").upper()
                
                # Cria a regional se não existir
                if codigo_regional not in self.regionais.get("regionais", {}):
                    self.adicionar_regional(
                        codigo_regional,
                        nome,
                        servidor.get("descricao", "")
                    )
                
                # Cria o servidor para a regional
                servidor_novo = {
                    "id": servidor.get("id", f"srv_{len(self.listar_servidores_regional(codigo_regional)) + 1:02d}"),
                    "nome": f"Servidor {nome.replace('RG_', '')} 01",
                    "tipo": servidor.get("tipo", "idrac"),
                    "ip": servidor.get("ip"),
                    "usuario": servidor.get("usuario"),
                    "senha": servidor.get("senha"),
                    "porta": servidor.get("porta", 443),
                    "timeout": servidor.get("timeout", 10),
                    "ativo": servidor.get("ativo", True),
                    "modelo": "Dell PowerEdge" if servidor.get("tipo") == "idrac" else "HPE ProLiant",
                    "funcao": "Aplicação"
                }
                
                self.adicionar_servidor(codigo_regional, servidor_novo)
                print(f"✅ Migrado: {nome} → {codigo_regional}")
        
        print("✅ Migração concluída!")
        

    def gerar_relatorio(self) -> str:
        """Gera um relatório da estrutura atual"""
        relatorio = []
        relatorio.append("📊 RELATÓRIO DE REGIONAIS E SERVIDORES")
        relatorio.append("=" * 50)
        
        total_regionais = len(self.regionais.get("regionais", {}))
        total_servidores = len(self.listar_todos_servidores())
        
        relatorio.append(f"📍 Total de Regionais: {total_regionais}")
        relatorio.append(f"🖥️  Total de Servidores: {total_servidores}")
        relatorio.append("")
        
        for codigo, regional in self.regionais.get("regionais", {}).items():
            relatorio.append(f"🏢 {regional.get('nome', codigo)}")
            relatorio.append(f"   Código: {codigo}")
            relatorio.append(f"   Descrição: {regional.get('descricao', 'N/A')}")
            
            servidores = regional.get("servidores", [])
            relatorio.append(f"   Servidores: {len(servidores)}")
            
            for servidor in servidores:
                status = "🟢" if servidor.get("ativo", True) else "🔴"
                tipo_icon = "🔧" if servidor.get("tipo") == "idrac" else "⚙️"
                relatorio.append(f"     {status} {tipo_icon} {servidor.get('nome')} ({servidor.get('ip')})")
            
            relatorio.append("")
        
        return "\n".join(relatorio)

def main():
    """Função principal para demonstração"""
    gerenciador = GerenciadorRegionais()
    
    print("🏢 Gerenciador de Regionais e Servidores")
    print("=" * 40)
    
    # Migra estrutura antiga se existir
    if os.path.exists("servidores.json"):
        resposta = input("Deseja migrar a estrutura antiga? (s/n): ")
        if resposta.lower() == 's':
            gerenciador.migrar_estrutura_antiga()
    
    # Gera relatório
    print("\n" + gerenciador.gerar_relatorio())
    
    # Menu interativo
    while True:
        print("\n📋 MENU:")
        print("1. Listar regionais")
        print("2. Adicionar regional")
        print("3. Adicionar servidor")
        print("4. Listar servidores")
        print("5. Gerar relatório")
        print("0. Sair")
        
        opcao = input("\nEscolha uma opção: ")
        
        if opcao == "1":
            regionais = gerenciador.listar_regionais()
            print(f"\n📍 Regionais ({len(regionais)}):")
            for regional in regionais:
                info = gerenciador.obter_regional(regional)
                print(f"  • {info.get('nome', regional)} ({regional})")
        
        elif opcao == "2":
            codigo = input("Código da regional: ").upper()
            nome = input("Nome da regional: ")
            descricao = input("Descrição (opcional): ")
            gerenciador.adicionar_regional(codigo, nome, descricao)
            print("✅ Regional adicionada!")
        
        elif opcao == "3":
            regionais = gerenciador.listar_regionais()
            if not regionais:
                print("❌ Nenhuma regional cadastrada")
                continue
            
            print("Regionais disponíveis:")
            for i, regional in enumerate(regionais, 1):
                info = gerenciador.obter_regional(regional)
                print(f"  {i}. {info.get('nome', regional)}")
            
            try:
                escolha = int(input("Escolha a regional: ")) - 1
                codigo_regional = regionais[escolha]
                
                servidor = {
                    "id": input("ID do servidor: "),
                    "nome": input("Nome do servidor: "),
                    "tipo": input("Tipo (idrac/ilo): ").lower(),
                    "ip": input("IP: "),
                    "usuario": input("Usuário: "),
                    "senha": input("Senha: "),
                    "modelo": input("Modelo (opcional): "),
                    "funcao": input("Função (opcional): ")
                }
                
                gerenciador.adicionar_servidor(codigo_regional, servidor)
                print("✅ Servidor adicionado!")
                
            except (ValueError, IndexError):
                print("❌ Opção inválida")
        
        elif opcao == "4":
            servidores = gerenciador.listar_todos_servidores()
            print(f"\n🖥️  Servidores ({len(servidores)}):")
            for servidor in servidores:
                status = "🟢" if servidor.get("ativo", True) else "🔴"
                tipo_icon = "🔧" if servidor.get("tipo") == "idrac" else "⚙️"
                print(f"  {status} {tipo_icon} {servidor.get('nome')} ({servidor.get('ip')}) - {servidor.get('nome_regional')}")
        
        elif opcao == "5":
            print("\n" + gerenciador.gerar_relatorio())
        
        elif opcao == "0":
            break
        
        else:
            print("❌ Opção inválida")

    

if __name__ == "__main__":
    main()