"""
Verificador de Servidores - Versão 2.0
Estrutura hierárquica: Regional → Servidores (iDRAC/ILO)
"""

import requests
import json
import urllib3
from datetime import datetime
from typing import Dict, List, Tuple
import concurrent.futures
from gerenciar_regionais import GerenciadorRegionais

# Desabilita warnings SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

class VerificadorServidoresV2:
    """Verificador de servidores com estrutura hierárquica"""
    
    def __init__(self):
        self.gerenciador = GerenciadorRegionais()
        self.resultados = {}
        
    def verificar_servidor(self, servidor: Dict, codigo_regional: str) -> Dict:
        """Verifica um servidor específico"""
        
        resultado = {
            "regional": codigo_regional,
            "servidor": servidor.get("nome", "N/A"),
            "ip": servidor.get("ip"),
            "tipo": servidor.get("tipo", "idrac"),
            "status": "offline",
            "tempo_resposta": None,
            "erro": None,
            "timestamp": datetime.now().isoformat()
        }
        
        try:
            # Monta URL baseada no tipo
            if servidor.get("tipo") == "ilo":
                url = f"https://{servidor['ip']}/json/login_session"
            else:  # idrac
                url = f"https://{servidor['ip']}/sysmgmt/2015/bmc/session"
            
            # Faz a requisição
            inicio = datetime.now()
            response = requests.get(
                url,
                timeout=servidor.get("timeout", 10),
                verify=False  # TODO: Implementar verificação de certificado adequada
            )
            fim = datetime.now()
            
            tempo_resposta = (fim - inicio).total_seconds()
            resultado["tempo_resposta"] = round(tempo_resposta, 2)
            
            if response.status_code in [200, 401, 403]:
                resultado["status"] = "online"
            else:
                resultado["status"] = "warning"
                resultado["erro"] = f"HTTP {response.status_code}"
                
        except requests.exceptions.Timeout:
            resultado["erro"] = "Timeout"
        except requests.exceptions.ConnectionError:
            resultado["erro"] = "Conexão recusada"
        except Exception as e:
            resultado["erro"] = str(e)
        
        return resultado
    
    def verificar_regional(self, codigo_regional: str) -> List[Dict]:
        """Verifica todos os servidores de uma regional"""
        
        regional = self.gerenciador.obter_regional(codigo_regional)
        if not regional:
            return []
        
        servidores = regional.get("servidores", [])
        resultados_regional = []
        
        print(f"[CHECK] Verificando {regional.get('nome', codigo_regional)} ({len(servidores)} servidores)...")
        
        # Verifica servidores em paralelo
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = {
                executor.submit(self.verificar_servidor, servidor, codigo_regional): servidor
                for servidor in servidores
            }
            
            for future in concurrent.futures.as_completed(futures):
                resultado = future.result()
                resultados_regional.append(resultado)
                
                # Mostra resultado em tempo real
                status_icon = "🟢" if resultado["status"] == "online" else "" if resultado["status"] == "offline" else "🟡"
                tempo = f"({resultado['tempo_resposta']}s)" if resultado["tempo_resposta"] else ""
                erro = f" - {resultado['erro']}" if resultado["erro"] else ""
                
                print(f"  {status_icon} {resultado['servidor']} {tempo}{erro}")
        
        return resultados_regional
    
    def verificar_todas_regionais(self) -> Dict:
        """Verifica todas as regionais"""
        
        print("[START] Iniciando verificação de todas as regionais...")
        print("=" * 60)
        
        regionais = self.gerenciador.listar_regionais()
        todos_resultados = {}
        
        for codigo_regional in regionais:
            resultados_regional = self.verificar_regional(codigo_regional)
            todos_resultados[codigo_regional] = resultados_regional
            print()  # Linha em branco entre regionais
        
        self.resultados = todos_resultados
        return todos_resultados
    
    def gerar_relatorio_detalhado(self) -> str:
        """Gera relatório detalhado dos resultados"""
        
        if not self.resultados:
            return "[ERROR] Nenhum resultado disponível. Execute a verificação primeiro."
        
        relatorio = []
        relatorio.append("[DATA] RELATÓRIO DETALHADO DE VERIFICAÇÃO")
        relatorio.append("=" * 60)
        relatorio.append(f" Gerado em: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
        relatorio.append("")
        
        # Estatísticas gerais
        total_servidores = 0
        online = 0
        offline = 0
        warning = 0
        
        for resultados_regional in self.resultados.values():
            for resultado in resultados_regional:
                total_servidores += 1
                if resultado["status"] == "online":
                    online += 1
                elif resultado["status"] == "offline":
                    offline += 1
                else:
                    warning += 1
        
        relatorio.append("[CHART] ESTATÍSTICAS GERAIS")
        relatorio.append(f"   Total de Servidores: {total_servidores}")
        relatorio.append(f"   🟢 Online: {online} ({online/total_servidores*100:.1f}%)")
        relatorio.append(f"    Offline: {offline} ({offline/total_servidores*100:.1f}%)")
        relatorio.append(f"   🟡 Warning: {warning} ({warning/total_servidores*100:.1f}%)")
        relatorio.append("")
        
        # Detalhes por regional
        for codigo_regional, resultados_regional in self.resultados.items():
            regional = self.gerenciador.obter_regional(codigo_regional)
            nome_regional = regional.get("nome", codigo_regional) if regional else codigo_regional
            
            relatorio.append(f" {nome_regional}")
            relatorio.append(f"   Código: {codigo_regional}")
            relatorio.append(f"   Servidores: {len(resultados_regional)}")
            
            for resultado in resultados_regional:
                status_icon = "🟢" if resultado["status"] == "online" else "" if resultado["status"] == "offline" else "🟡"
                tipo_icon = "[CONFIG]" if resultado["tipo"] == "idrac" else ""
                
                linha = f"     {status_icon} {tipo_icon} {resultado['servidor']} ({resultado['ip']})"
                
                if resultado["tempo_resposta"]:
                    linha += f" - {resultado['tempo_resposta']}s"
                
                if resultado["erro"]:
                    linha += f" - {resultado['erro']}"
                
                relatorio.append(linha)
            
            relatorio.append("")
        
        return "\n".join(relatorio)
    
    def salvar_resultados(self, arquivo="resultados_verificacao.json"):
        """Salva os resultados em arquivo JSON"""
        
        dados_salvamento = {
            "timestamp": datetime.now().isoformat(),
            "total_regionais": len(self.resultados),
            "resultados": self.resultados
        }
        
        with open(arquivo, 'w', encoding='utf-8') as f:
            json.dump(dados_salvamento, f, indent=2, ensure_ascii=False)
        
        print(f" Resultados salvos em: {arquivo}")
    
    def gerar_html_status(self, arquivo="status_servidores.html"):
        """Gera página HTML com status dos servidores"""
        
        if not self.resultados:
            print("[ERROR] Nenhum resultado disponível para gerar HTML")
            return
        
        html = """
<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Status dos Servidores - Regionais</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; background-color: #f5f5f5; }
        .container { max-width: 1200px; margin: 0 auto; }
        .header { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px; border-radius: 10px; margin-bottom: 20px; }
        .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin-bottom: 20px; }
        .stat-card { background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); text-align: center; }
        .regional { background: white; margin-bottom: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); overflow: hidden; }
        .regional-header { background: #f8f9fa; padding: 15px; border-bottom: 1px solid #dee2e6; }
        .servidor { padding: 10px 15px; border-bottom: 1px solid #f0f0f0; display: flex; justify-content: space-between; align-items: center; }
        .servidor:last-child { border-bottom: none; }
        .status-online { color: #28a745; }
        .status-offline { color: #dc3545; }
        .status-warning { color: #ffc107; }
        .tempo-resposta { font-size: 0.9em; color: #6c757d; }
        .refresh-time { text-align: center; color: #6c757d; margin-top: 20px; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>[SERVER] Status dos Servidores - Regionais</h1>
            <p>Monitoramento em tempo real dos servidores iDRAC/ILO</p>
        </div>
"""
        
        # Estatísticas
        total_servidores = 0
        online = 0
        offline = 0
        warning = 0
        
        for resultados_regional in self.resultados.values():
            for resultado in resultados_regional:
                total_servidores += 1
                if resultado["status"] == "online":
                    online += 1
                elif resultado["status"] == "offline":
                    offline += 1
                else:
                    warning += 1
        
        html += f"""
        <div class="stats">
            <div class="stat-card">
                <h3>Total</h3>
                <h2>{total_servidores}</h2>
                <p>Servidores</p>
            </div>
            <div class="stat-card">
                <h3 class="status-online">Online</h3>
                <h2>{online}</h2>
                <p>{online/total_servidores*100:.1f}%</p>
            </div>
            <div class="stat-card">
                <h3 class="status-offline">Offline</h3>
                <h2>{offline}</h2>
                <p>{offline/total_servidores*100:.1f}%</p>
            </div>
            <div class="stat-card">
                <h3 class="status-warning">Warning</h3>
                <h2>{warning}</h2>
                <p>{warning/total_servidores*100:.1f}%</p>
            </div>
        </div>
"""
        
        # Regionais
        for codigo_regional, resultados_regional in self.resultados.items():
            regional = self.gerenciador.obter_regional(codigo_regional)
            nome_regional = regional.get("nome", codigo_regional) if regional else codigo_regional
            
            html += f"""
        <div class="regional">
            <div class="regional-header">
                <h3> {nome_regional}</h3>
                <small>Código: {codigo_regional} | Servidores: {len(resultados_regional)}</small>
            </div>
"""
            
            for resultado in resultados_regional:
                status_class = f"status-{resultado['status']}"
                status_icon = "🟢" if resultado["status"] == "online" else "" if resultado["status"] == "offline" else "🟡"
                tipo_icon = "[CONFIG]" if resultado["tipo"] == "idrac" else ""
                
                tempo_info = ""
                if resultado["tempo_resposta"]:
                    tempo_info = f'<span class="tempo-resposta">({resultado["tempo_resposta"]}s)</span>'
                
                erro_info = ""
                if resultado["erro"]:
                    erro_info = f'<small style="color: #dc3545;"> - {resultado["erro"]}</small>'
                
                html += f"""
            <div class="servidor">
                <div>
                    <span class="{status_class}">{status_icon} {tipo_icon}</span>
                    <strong>{resultado["servidor"]}</strong>
                    <small>({resultado["ip"]})</small>
                    {erro_info}
                </div>
                <div>{tempo_info}</div>
            </div>
"""
            
            html += "        </div>\n"
        
        html += f"""
        <div class="refresh-time">
            <p> Última atualização: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}</p>
        </div>
    </div>
</body>
</html>
"""
        
        with open(arquivo, 'w', encoding='utf-8') as f:
            f.write(html)
        
        print(f"[WEB] Página HTML gerada: {arquivo}")

def main():
    """Função principal"""
    
    verificador = VerificadorServidoresV2()
    
    print("[SERVER] Verificador de Servidores - Versão 2.0")
    print("Estrutura hierárquica: Regional → Servidores")
    print("=" * 50)
    
    # Menu
    while True:
        print("\n MENU:")
        print("1. Verificar todas as regionais")
        print("2. Verificar regional específica")
        print("3. Gerar relatório detalhado")
        print("4. Gerar página HTML")
        print("5. Salvar resultados")
        print("0. Sair")
        
        opcao = input("\nEscolha uma opção: ")
        
        if opcao == "1":
            verificador.verificar_todas_regionais()
            print("\n[OK] Verificação concluída!")
        
        elif opcao == "2":
            regionais = verificador.gerenciador.listar_regionais()
            if not regionais:
                print("[ERROR] Nenhuma regional cadastrada")
                continue
            
            print("Regionais disponíveis:")
            for i, regional in enumerate(regionais, 1):
                info = verificador.gerenciador.obter_regional(regional)
                print(f"  {i}. {info.get('nome', regional)}")
            
            try:
                escolha = int(input("Escolha a regional: ")) - 1
                codigo_regional = regionais[escolha]
                verificador.verificar_regional(codigo_regional)
                print("\n[OK] Verificação concluída!")
            except (ValueError, IndexError):
                print("[ERROR] Opção inválida")
        
        elif opcao == "3":
            if verificador.resultados:
                print("\n" + verificador.gerar_relatorio_detalhado())
            else:
                print("[ERROR] Execute uma verificação primeiro")
        
        elif opcao == "4":
            if verificador.resultados:
                verificador.gerar_html_status()
            else:
                print("[ERROR] Execute uma verificação primeiro")
        
        elif opcao == "5":
            if verificador.resultados:
                verificador.salvar_resultados()
            else:
                print("[ERROR] Execute uma verificação primeiro")
        
        elif opcao == "0":
            break
        
        else:
            print("[ERROR] Opção inválida")

if __name__ == "__main__":
    main()