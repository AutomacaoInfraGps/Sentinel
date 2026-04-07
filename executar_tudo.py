# --- GPS Amigo: imports e preparação (topo do arquivo) ---
import sys
from pathlib import Path
# garante que importações peguem C:\Automacao primeiro
sys.path.insert(0, str(Path(__file__).parent.resolve()))
from web_config import gerenciador_fortigate
from gps_print import ensure_gps_placeholder, gerar_print_gps_amigo
from config import GPS_HTML

import subprocess
from pathlib import Path
import webbrowser
import os
import re
from datetime import datetime
import sys
sys.path.insert(0, str(Path(__file__).parent.resolve()))
import json, html

AUTO_NO_BROWSER = "--no-browser" in sys.argv or os.environ.get("AUTOMACAO_NO_BROWSER", "").strip().lower() in {"1", "true", "yes", "on"}
from config import REPLICACAO_HTML, REPLICACAO_JSON
try:
    from config import REPLICACAO_HTML_FRAGMENT
except Exception:
    REPLICACAO_HTML_FRAGMENT = None

# --- GPS: helpers de renderização (substitua sua função atual por estas duas) ---
import re, base64
from datetime import datetime

def _montar_gps_html():
    """Retorna o HTML a ser exibido no dashboard (preferindo <body> do print_temp;
    se não houver, embute o PNG em base64; se nada, mostra placeholder com link)."""
    try:
        # 1) Tenta usar o HTML gerado (com a imagem já embedada)
        if GPS_HTML.exists():
            txt = GPS_HTML.read_text(encoding="utf-8", errors="ignore")
            m = re.search(r"<body[^>]*>(.*?)</body>", txt, flags=re.IGNORECASE | re.DOTALL)
            body = (m.group(1) if m else txt).strip()
            # Se já tem imagem embedada ou <img>, usa direto
            if "data:image/png" in body or "<img" in body:
                return body
        # 2) Se não, embute o PNG
        png_path = GPS_HTML.with_name("gps_amigo.png")
        if png_path.exists() and png_path.stat().st_size > 10_000:  # >10KB evita falso-positivo
            b64 = base64.b64encode(png_path.read_bytes()).decode("ascii")
            ts  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            return (
                f'<img alt="GPS Amigo" '
                f'style="max-width:100%;height:auto;border-radius:8px;box-shadow:0 2px 10px rgba(0,0,0,.08)" '
                f'src="data:image/png;base64,{b64}">'
                f'<div class="small" style="color:#666;margin-top:6px">Atualizado: {ts}</div>'
            )
    except Exception as e:
        # não interrompe o fluxo do dashboard
        print("[GPS] Falha montando HTML:", e)

    # 3) Último recurso: placeholder enxuto
    url = GPS_CONFIG.get("url", "https://gpsamigo.com.br/login.php")
    ts  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return (
        f'<div class="note" style="color:#666">Prévia indisponível no momento. ({ts})</div>'
        f'<p><a href="{url}" target="_blank">Abrir GPS Amigo</a></p>'
    )

def render_bloco_gps():
    """Card do GPS para ser usado (se você ainda quiser exibir em algum lugar)."""
    return f"""
    <section class="card">
      <h2>Print GPS Amigo</h2>
      <div class="card-body">
        {_montar_gps_html()}
      </div>
    </section>
    """


def _month_abbr_pt_local(month: int) -> str:
    months = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
    return months[month - 1]


def _montar_print_rede_html():
    """Monta o HTML com os 3 prints do portal de rede gerados no dia atual."""
    try:
        from config import SATURNO_OUTPUT_BASE

        now = datetime.now()
        out_dir = SATURNO_OUTPUT_BASE / f"{now.year}" / _month_abbr_pt_local(now.month) / f"{now.day:02d}"
        images = [
            ("WI-FI", out_dir / "saturno_wifi.png"),
            ("DIRETORIA", out_dir / "saturno_diretoria.png"),
            ("APROVACAO WI-FI", out_dir / "saturno_wifi_aprovacao.png"),
        ]

        cards = []
        for title, path in images:
            if not path.exists() or path.stat().st_size == 0:
                cards.append(
                    f"""
                    <div style="margin-bottom: 24px;">
                        <h3 style="font-size: 1.1rem; font-weight: 700; margin-bottom: 10px;">{title}</h3>
                        <div class='error'>Print não encontrado: {path}</div>
                    </div>
                    """
                )
                continue

            b64 = base64.b64encode(path.read_bytes()).decode("ascii")
            updated = datetime.fromtimestamp(path.stat().st_mtime).strftime("%d/%m/%Y %H:%M:%S")
            cards.append(
                f"""
                <div style="margin-bottom: 28px;">
                    <h3 style="font-size: 1.1rem; font-weight: 700; margin-bottom: 10px;">{title}</h3>
                    <img alt="{title}" style="max-width:100%;height:auto;border-radius:8px;box-shadow:0 2px 10px rgba(0,0,0,.08)" src="data:image/png;base64,{b64}">
                    <div class="small" style="color:#666;margin-top:6px">Atualizado: {updated}</div>
                </div>
                """
            )

        return "".join(cards)
    except Exception as e:
        print("[PRINT-REDE] Falha montando HTML:", e)
        return f"<div class='error'>Falha ao montar Print Rede: {e}</div>"


def render_replicacao_card():
    """
    Exibe a replicação usando 1) fragmento, 2) HTML completo, ou 3) JSON
    (nesta ordem). Assim evita duplicidade.
    """
    # 1) Fragmento (sem <html>), se existir
    if REPLICACAO_HTML_FRAGMENT and Path(REPLICACAO_HTML_FRAGMENT).exists():
        frag = Path(REPLICACAO_HTML_FRAGMENT).read_text(encoding="utf-8")
        return f'<section class="card"><h2>Replicação AD</h2><div class="card-body">{frag}</div></section>'

    # 2) HTML completo (gerado pelo PS1)
    if Path(REPLICACAO_HTML).exists():
        frag = Path(REPLICACAO_HTML).read_text(encoding="utf-8")
        return f'<section class="card"><h2>Replicação AD</h2><div class="card-body">{frag}</div></section>'

    # 3) JSON (monta tabela no padrão do site)
    if Path(REPLICACAO_JSON).exists():
        data = json.loads(Path(REPLICACAO_JSON).read_text(encoding="utf-8"))
        payload = data.get("legacy") or data.get("data") or data
        linhas = []
        for ctrl in payload.get("detalhes", {}).get("controladores", []):
            linhas.append(
                "<tr>"
                f"<td>{html.escape(str(ctrl.get('nome','')))}</td>"
                f"<td>{html.escape(str(ctrl.get('latencia','')))}</td>"
                f"<td>{html.escape(str(ctrl.get('sucesso_total','')))}</td>"
                f"<td>{html.escape(str(ctrl.get('erros','')))}</td>"
                "</tr>"
            )
        tabela = (
            "<table class='tabela'><thead><tr>"
            "<th>Servidor</th><th>Latência</th><th>SucessoTotal</th><th>Erros</th>"
            "</tr></thead><tbody>" + "".join(linhas) + "</tbody></table>"
        )
        return f'<section class="card"><h2>Replicação AD</h2><div class="card-body">{tabela}</div></section>'

    # 4) Fallback
    return (
        '<section class="card"><h2>Replicação AD</h2>'
        '<div class="card-body error">Arquivo não encontrado.</div></section>'
    )


# Configuração para Windows - força UTF-8
if sys.platform == "win32":
    import codecs
    import locale
    
    # Tenta configurar UTF-8
    try:
        sys.stdout = codecs.getwriter("utf-8")(sys.stdout.detach())
        sys.stderr = codecs.getwriter("utf-8")(sys.stderr.detach())
    except:
        # Se falhar, usa print seguro sem emojis
        pass

# Função para print seguro (sem emojis no Windows)
def safe_print(message):
    """Print seguro que funciona no Windows"""
    try:
        print(message)
    except UnicodeEncodeError:
        # Remove emojis e caracteres especiais
        import re
        clean_message = re.sub(r'[^\x00-\x7F]+', '[EMOJI]', message)
        print(clean_message)

# Importa as configurações dinâmicas
from config import (
    CONEXOES_FILE, REGIONAL_HTMLS_DIR, GPS_HTML, REPLICACAO_HTML, 
    UNIFI_HTML, DASHBOARD_FINAL, DASHBOARD_FINAL_ORIGINAL, ensure_directories, get_regional_html_path,
    validate_config, PROJECT_ROOT, RELATORIO_PREVENTIVA_DIR
)

# === VALIDAÇÃO E INICIALIZAÇÃO ===
# Valida as configurações antes de continuar
config_errors = validate_config()
if config_errors:
    print("[ERRO] Erros de configuração encontrados:")
    for error in config_errors:
        print(f"   - {error}")
    sys.exit(1)

# Garante que os diretórios necessários existem
ensure_directories()

safe_print(f"[INFO] Usando diretório do projeto: {PROJECT_ROOT}")
safe_print(f"[INFO] Arquivos serão salvos em: {DASHBOARD_FINAL.parent}")
safe_print(f"[INFO] Arquivo de conexões: {CONEXOES_FILE}")
print()

# === DATA E HORA DA EXECUÇÃO ===
# Obtém a data e hora atual para exibir no dashboard
data_execucao = datetime.now().strftime('%d/%m/%Y %H:%M:%S')

# === 1. EXECUTA CHEKLISTS DAS REGIONAIS ===
# Carrega servidores do novo sistema de gerenciamento
try:
    from gerenciar_servidores import GerenciadorServidores
    gerenciador = GerenciadorServidores()
    servidores_configurados = gerenciador.listar_servidores()
    print(f"[INFO] {len(servidores_configurados)} servidores carregados do sistema de gerenciamento")
except Exception as e:
    print(f"[AVISO] Erro ao carregar gerenciador de servidores: {e}")
    print("[INFO] Usando método legado...")
    # Fallback para método antigo
    conteudo = CONEXOES_FILE.read_text(encoding="utf-8")
    blocos = re.split(r"\n\s*\n", conteudo.strip())
    servidores_configurados = []
    
    for bloco in blocos:
        nome_match = re.search(r"Nome:\s*(.+)", bloco, re.IGNORECASE)
        tipo_match = re.search(r"Tipo:\s*(\w+)", bloco, re.IGNORECASE)
        ip_match = re.search(r"IP:\s*([\d\.]+)", bloco, re.IGNORECASE)
        user_match = re.search(r"Usuario:\s*(\S+)", bloco, re.IGNORECASE)
        pass_match = re.search(r"Senha:\s*(\S+)", bloco, re.IGNORECASE)
        
        if all([nome_match, tipo_match, ip_match, user_match, pass_match]):
            servidores_configurados.append({
                'nome': nome_match.group(1).strip(),
                'tipo': tipo_match.group(1).strip().lower(),
                'ip': ip_match.group(1).strip(),
                'usuario': user_match.group(1).strip(),
                'senha': pass_match.group(1).strip(),
                'ativo': True
            })

blocos_html_regionais_with_status = [] # Armazena (html_bloco_string, tem_erro)

# Processa cada servidor configurado
for servidor in servidores_configurados:
    # Pula servidores inativos
    if not servidor.get('ativo', True):
        continue
    
    nome = servidor['nome']
    tipo = servidor['tipo']
    ip = servidor['ip']
    usuario = servidor['usuario']
    senha = servidor['senha']
    html_path = get_regional_html_path(nome)

    current_regional_html_content = ""
    has_error_for_regional = False

    # Executa o script de checklist apropriado baseado no 'tipo'
    try:
        if tipo == "idrac":
            print(f"[EXEC] Coletando {nome} ({ip}) - iDRAC")
            chelist_path = PROJECT_ROOT / "Chelist.py"
            subprocess.run(["python", str(chelist_path), ip, usuario, senha, str(html_path)], 
                         check=True, cwd=str(PROJECT_ROOT), capture_output=True, text=True)
        elif tipo == "ilo":
            print(f"[EXEC] Coletando {nome} ({ip}) - iLO")
            ilo_path = PROJECT_ROOT / "iLOcheck.py"
            subprocess.run(["python", str(ilo_path), ip, usuario, senha, str(html_path)], 
                         check=True, cwd=str(PROJECT_ROOT), capture_output=True, text=True)
        else:
            # Trata tipos desconhecidos escrevendo uma mensagem de erro no arquivo HTML
            current_regional_html_content = f"""
            <div class="error-container">
                <div class="error-icon">[ERRO]</div>
                <div class="error-title">Tipo desconhecido</div>
                <div class="error-message">Tipo: {tipo}</div>
            </div>
            """
            has_error_for_regional = True
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(current_regional_html_content)
    except subprocess.CalledProcessError as e:
        error_details = f"Código de saída: {e.returncode}"
        if hasattr(e, 'stdout') and e.stdout:
            error_details += f"\nSaída: {e.stdout}"
        if hasattr(e, 'stderr') and e.stderr:
            error_details += f"\nErro: {e.stderr}"
        
        print(f"[ERRO] Erro ao executar script para {nome} ({ip}): {error_details}")
        
        # Se o subprocess falhar, marca como erro e escreve uma mensagem de erro genérica
        current_regional_html_content = f"""
        <div class="error-container">
            <div class="error-icon">[ERROR]</div>
            <div class="error-title">Erro ao executar script</div>
            <div class="error-message">Regional: {nome}<br>IP: {ip}<br>Erro: {error_details}</div>
        </div>
        """
        has_error_for_regional = True
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(current_regional_html_content)
    except Exception as e:
        print(f"[ERRO] Erro inesperado para {nome} ({ip}): {e}")
        current_regional_html_content = f"""
        <div class="error-container">
            <div class="error-icon">[ERROR]</div>
            <div class="error-title">Erro inesperado</div>
            <div class="error-message">Regional: {nome}<br>IP: {ip}<br>Erro: {str(e)}</div>
        </div>
        """
        has_error_for_regional = True
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(current_regional_html_content)

    # Após tentar executar o subprocess ou tratar tipo desconhecido/erro de subprocess,
    # lê o conteúdo do arquivo HTML gerado se ele existir.
    # Este passo é crucial para capturar erros escritos pelos próprios Chelist.py/iLOcheck.py.
    if html_path.exists():
        file_content = html_path.read_text(encoding="utf-8")
        # Verifica indicadores comuns de erro no conteúdo do arquivo, incluindo o erro específico do iDRAC
        if "[ERROR] Erro" in file_content or "Error" in file_content or "timed out" in file_content or "Connection to" in file_content:
            has_error_for_regional = True
        current_regional_html_content = file_content
    else:
        # Se o arquivo não existir, definitivamente é um erro
        current_regional_html_content = """
        <div class="error-container">
            <div class="error-icon">[ERROR]</div>
            <div class="error-title">Erro ao gerar HTML</div>
            <div class="error-message">Arquivo não encontrado</div>
        </div>
        """
        has_error_for_regional = True

    # Constrói o bloco HTML para esta regional
    regional_html_block = f"""
    <details class="regional-item">
      <summary><strong>{nome}</strong></summary>
      <div class="regional-content">
        {current_regional_html_content}
      </div>
    </details>
    """
    blocos_html_regionais_with_status.append((regional_html_block, has_error_for_regional))

# === 3. EXECUTA REPLICAÇÃO AD ===
print("[EXEC] Executando verificação de replicação AD...")
try:
    # Executa o script PowerShell para verificação de replicação AD
    subprocess.run(["powershell", "-ExecutionPolicy", "Bypass", "-File", "Replicacao_Servers.ps1"], check=True)
except subprocess.CalledProcessError:
    print("[ERRO] Erro ao executar Replicacao_Servers.ps1")

# === 4. EXECUTA COLETA DAS APs UNIFI ===
print("[EXEC] Coletando informações das APs UniFi...")
try:
    # Executa o script Python para coletar informações das APs UniFi
    subprocess.run(["python", "Unifi.Py"], check=True)
except subprocess.CalledProcessError:
    print("[ERRO] Erro ao executar Unifi.py")

# === 5. EXECUTA VERIFICAÇÃO DAS VMs ===
print("[EXEC] Verificando status das Máquinas Virtuais...")
vms_data = []
vms_online = 0
vms_offline = 0
relatorio_vms = ""
try:
    # Carrega VMs do arquivo de dados
    vms_file = PROJECT_ROOT / "data" / "vms.json"
    if vms_file.exists():
        import json
        with open(vms_file, 'r', encoding='utf-8') as f:
            vms_configuradas = json.load(f)
    else:
        vms_configuradas = []
    
    from vm_manager import verificar_vm_online
    
    for vm in vms_configuradas:
        try:
            print(f"[EXEC] Verificando VM {vm['name']} ({vm['ip']})")
            
            # Verifica se a VM está online
            vm_online = verificar_vm_online(vm['ip'])
            
            vm_info = {
                'name': vm['name'],
                'ip': vm['ip'],
                'regional': vm.get('regional', 'N/A'),
                'username': vm.get('username', 'N/A'),
                'description': vm.get('description', 'N/A'),
                'last_check': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
            
            if vm_online:
                vms_online += 1
                vm_info['status'] = "online"
                
                # Se a VM está online, gera relatório detalhado
                print(f"[EXEC] Gerando relatório detalhado da VM {vm['name']}...")
                from vm_manager import gerar_relatorio_simples
                
                relatorio = gerar_relatorio_simples(
                    vm['ip'], 
                    vm.get('username', ''), 
                    vm.get('password', '')
                )
                
                if relatorio.get('success', False):
                    print(f"[OK] Relatório detalhado gerado para VM {vm['name']}")
                    vm_info['relatorio_detalhado'] = relatorio
                else:
                    print(f"[WARN] Falha ao gerar relatório detalhado: {relatorio.get('message', 'Erro desconhecido')}")
                    vm_info['relatorio_erro'] = relatorio.get('message', 'Erro desconhecido')
            else:
                vms_offline += 1
                vm_info['status'] = "offline"
                
            vms_data.append(vm_info)
            
        except Exception as e:
            print(f"[ERRO] Erro ao verificar VM {vm['name']}: {e}")
            vms_offline += 1
            vms_data.append({
                'name': vm['name'],
                'ip': vm['ip'],
                'regional': vm.get('regional', 'N/A'),
                'status': 'error',
                'error': str(e),
                'last_check': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            })
    
    # Gera HTML detalhado das VMs
    relatorio_vms = "<div class='vms-container'>"
    
    for vm in vms_data:
        status_class = "success" if vm['status'] == 'online' else "danger"
        
        relatorio_vms += f"""
        <div class="vm-item mb-4">
            <div class="card">
                <div class="card-header bg-{status_class} text-white">
                    <h4 class="mb-0">[SERVER] {vm['name']}</h4>
                    <small>{vm.get('description', 'N/A')}</small>
                </div>
                <div class="card-body">
                    <div class="row">
                        <div class="col-md-6">
                            <h6> Informações Básicas</h6>
                            <p><strong>IP:</strong> {vm['ip']}</p>
                            <p><strong>Regional:</strong> {vm['regional']}</p>
                            <p><strong>Status:</strong> <span class="badge badge-{status_class}">{vm['status'].upper()}</span></p>
                            <p><strong>Usuário:</strong> {vm.get('username', 'N/A')}</p>
                            <p><strong>Última verificação:</strong> {vm['last_check']}</p>
                            {f"<p><strong>[ERROR] Erro:</strong> {vm['error']}</p>" if vm.get('error') else ""}
                            {f"<p><strong>[WARN] Erro no relatório:</strong> {vm['relatorio_erro']}</p>" if vm.get('relatorio_erro') else ""}
        """
        
        # Se tem relatório detalhado, inclui as informações
        if vm.get('relatorio_detalhado') and vm['relatorio_detalhado'].get('success'):
            relatorio = vm['relatorio_detalhado']
            
            # Informações do sistema
            sistema = relatorio.get('sistema', {})
            if sistema and not sistema.get('error'):
                relatorio_vms += f"""
                            <p><strong>Sistema Operacional:</strong> {sistema.get('OperatingSystem', 'N/A')}</p>
                            <p><strong>Versão:</strong> {sistema.get('OSVersion', 'N/A')}</p>
                            <p><strong>Uptime:</strong> {sistema.get('Uptime', 'N/A')}</p>
                            <p><strong>Último Boot:</strong> {sistema.get('LastBoot', 'N/A')}</p>
                        </div>
                        <div class="col-md-6">
                            <h6> Recursos do Sistema</h6>
                            <p><strong>Processadores:</strong> {sistema.get('Processors', 'N/A')}</p>
                            <p><strong>Memória:</strong> {sistema.get('Memory', 'N/A')}</p>
                            <p><strong>Fabricante:</strong> {sistema.get('Manufacturer', 'N/A')}</p>
                            <p><strong>Modelo:</strong> {sistema.get('Model', 'N/A')}</p>
                            <p><strong>Número de Série:</strong> {sistema.get('SerialNumber', 'N/A')}</p>
                        </div>
                    </div>
                """
                
                # Informações de discos
                discos = relatorio.get('discos', [])
                if discos and not (len(discos) == 1 and discos[0].get('error')):
                    relatorio_vms += """
                    <div class="row mt-3">
                        <div class="col-12">
                            <h6> Discos e Armazenamento</h6>
                            <div class="table-responsive">
                                <table class="table table-sm table-striped">
                                    <thead>
                                        <tr>
                                            <th>Drive</th>
                                            <th>Volume</th>
                                            <th>Espaço Total</th>
                                            <th>Espaço Livre</th>
                                            <th>Espaço Usado</th>
                                            <th>% Usado</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                    """
                    for disco in discos:
                        if not disco.get('error'):
                            percent_usado = disco.get('PercentUsed', 0)
                            try:
                                percent_usado = float(percent_usado)
                                cor_uso = 'success' if percent_usado < 70 else 'warning' if percent_usado < 90 else 'danger'
                            except:
                                cor_uso = 'secondary'
                                percent_usado = 'N/A'
                            
                            relatorio_vms += f"""
                                            <tr>
                                                <td><strong>{disco.get('Drive', 'N/A')}</strong></td>
                                                <td>{disco.get('VolumeName', 'N/A')}</td>
                                                <td>{disco.get('TotalSpace', 'N/A')}</td>
                                                <td>{disco.get('FreeSpace', 'N/A')}</td>
                                                <td>{disco.get('UsedSpace', 'N/A')}</td>
                                                <td><span class="badge badge-{cor_uso}">{percent_usado}%</span></td>
                                            </tr>
                            """
                    relatorio_vms += """
                                    </tbody>
                                </table>
                            </div>
                        </div>
                    </div>
                    """
                
                # Serviços
                servicos = relatorio.get('servicos', [])
                if servicos and not (len(servicos) == 1 and servicos[0].get('error')):
                    servicos_rodando = [s for s in servicos if s.get('Status') == 'Running' and not s.get('error')]
                    servicos_parados = [s for s in servicos if s.get('Status') == 'Stopped' and s.get('StartMode') == 'Auto' and not s.get('error')]
                    
                    relatorio_vms += f"""
                    <div class="row mt-3">
                        <div class="col-md-6">
                            <h6>[OK] Serviços Ativos ({len(servicos_rodando)})</h6>
                    """
                    if servicos_rodando:
                        relatorio_vms += "<ul class='list-group list-group-flush' style='max-height: 200px; overflow-y: auto;'>"
                        for servico in servicos_rodando[:15]:  # Mostra apenas os primeiros 15
                            relatorio_vms += f"<li class='list-group-item py-1'><small>[OK] {servico.get('DisplayName', servico.get('Name', 'N/A'))}</small></li>"
                        if len(servicos_rodando) > 15:
                            relatorio_vms += f"<li class='list-group-item py-1'><small><em>... e mais {len(servicos_rodando)-15} serviços</em></small></li>"
                        relatorio_vms += "</ul>"
                    else:
                        relatorio_vms += "<p class='text-muted'><small>Nenhum serviço ativo encontrado</small></p>"
                    
                    relatorio_vms += f"""
                        </div>
                        <div class="col-md-6">
                            <h6>[WARN] Serviços Parados ({len(servicos_parados)})</h6>
                    """
                    if servicos_parados:
                        relatorio_vms += "<ul class='list-group list-group-flush' style='max-height: 200px; overflow-y: auto;'>"
                        for servico in servicos_parados[:15]:  # Mostra apenas os primeiros 15
                            relatorio_vms += f"<li class='list-group-item py-1'><small>[ERROR] {servico.get('DisplayName', servico.get('Name', 'N/A'))}</small></li>"
                        if len(servicos_parados) > 15:
                            relatorio_vms += f"<li class='list-group-item py-1'><small><em>... e mais {len(servicos_parados)-15} serviços</em></small></li>"
                        relatorio_vms += "</ul>"
                    else:
                        relatorio_vms += "<p class='text-success'><small>[OK] Todos os serviços automáticos estão funcionando</small></p>"
                    
                    relatorio_vms += """
                        </div>
                    </div>
                    """
                
                # Rede
                rede = relatorio.get('rede', [])
                if rede and not (len(rede) == 1 and rede[0].get('error')):
                    relatorio_vms += """
                    <div class="row mt-3">
                        <div class="col-12">
                            <h6>[WEB] Interfaces de Rede</h6>
                            <div class="table-responsive">
                                <table class="table table-sm table-striped">
                                    <thead>
                                        <tr>
                                            <th>Adaptador</th>
                                            <th>Status</th>
                                            <th>Endereço IP</th>
                                            <th>MAC Address</th>
                                            <th>Gateway</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                    """
                    for interface in rede:
                        if not interface.get('error'):
                            status_rede = interface.get('Status', 'Unknown')
                            cor_status = 'success' if 'Up' in status_rede else 'danger'
                            relatorio_vms += f"""
                                            <tr>
                                                <td>{interface.get('Name', 'N/A')}</td>
                                                <td><span class="badge badge-{cor_status}">{status_rede}</span></td>
                                                <td>{interface.get('IPAddress', 'N/A')}</td>
                                                <td>{interface.get('MACAddress', 'N/A')}</td>
                                                <td>{interface.get('DefaultGateway', 'N/A')}</td>
                                            </tr>
                            """
                    relatorio_vms += """
                                    </tbody>
                                </table>
                            </div>
                        </div>
                    </div>
                    """
                
                # Processos (Top 10)
                processos = relatorio.get('processos', [])
                if processos and not (len(processos) == 1 and processos[0].get('error')):
                    relatorio_vms += """
                    <div class="row mt-3">
                        <div class="col-12">
                            <h6>[UPDATE] Top 15 Processos por CPU</h6>
                            <div class="table-responsive">
                                <table class="table table-sm table-striped">
                                    <thead>
                                        <tr>
                                            <th>Nome</th>
                                            <th>PID</th>
                                            <th>CPU</th>
                                            <th>Memória (MB)</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                    """
                    for processo in processos[:15]:  # Top 15
                        if not processo.get('error'):
                            cpu_value = processo.get('CPU', 0)
                            memory_value = processo.get('Memory', 0)
                            pid_value = processo.get('Id', 'N/A')
                            
                            # Formata os valores
                            cpu_display = f"{cpu_value}" if cpu_value and cpu_value > 0 else "0"
                            memory_display = f"{memory_value}" if memory_value and memory_value > 0 else "0"
                            
                            relatorio_vms += f"""
                                            <tr>
                                                <td><strong>{processo.get('Name', 'N/A')}</strong></td>
                                                <td>{pid_value}</td>
                                                <td>{cpu_display}</td>
                                                <td>{memory_display} MB</td>
                                            </tr>
                            """
                    relatorio_vms += """
                                    </tbody>
                                </table>
                            </div>
                        </div>
                    </div>
                    """
                
                # Logs do sistema (Últimos 20)
                eventos = relatorio.get('eventos', [])
                if eventos and not (len(eventos) == 1 and eventos[0].get('error')):
                    relatorio_vms += """
                    <div class="row mt-3">
                        <div class="col-12">
                            <h6> Últimos 20 Logs do Sistema</h6>
                            <div class="table-responsive">
                                <table class="table table-sm table-striped">
                                    <thead>
                                        <tr>
                                            <th>Data/Hora</th>
                                            <th>Tipo</th>
                                            <th>Fonte</th>
                                            <th>ID</th>
                                            <th>Mensagem</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                    """
                    for evento in eventos[:20]:  # Últimos 20 logs
                        if not evento.get('error'):
                            entry_type = evento.get('EntryType', 'Information')
                            
                            # Define a cor baseada no tipo do evento
                            if entry_type == 'Error':
                                tipo_badge = 'danger'
                                tipo_icon = '[ERROR]'
                            elif entry_type == 'Warning':
                                tipo_badge = 'warning'
                                tipo_icon = '[WARN]'
                            else:
                                tipo_badge = 'info'
                                tipo_icon = 'ℹ'
                            
                            # Trunca a mensagem se for muito longa
                            mensagem = evento.get('Message', 'N/A')
                            if len(mensagem) > 100:
                                mensagem = mensagem[:100] + "..."
                            
                            relatorio_vms += f"""
                                            <tr>
                                                <td><small>{evento.get('TimeGenerated', 'N/A')}</small></td>
                                                <td><span class="badge badge-{tipo_badge}">{tipo_icon} {entry_type}</span></td>
                                                <td><small>{evento.get('Source', 'N/A')}</small></td>
                                                <td><small>{evento.get('EventID', 'N/A')}</small></td>
                                                <td><small>{mensagem}</small></td>
                                            </tr>
                            """
                    relatorio_vms += """
                                    </tbody>
                                </table>
                            </div>
                        </div>
                    </div>
                    """
            else:
                # Se não tem informações do sistema, fecha a div básica
                relatorio_vms += """
                        </div>
                    </div>
                """
        else:
            # Se a VM está offline ou sem relatório, fecha a div básica
            relatorio_vms += """
                        </div>
                    </div>
            """
        
        relatorio_vms += """
                </div>
            </div>
        </div>
        """
    
    relatorio_vms += "</div>"
    
except Exception as e:
    print(f"[ERRO] Erro no módulo de VMs: {e}")
    vms_data = []
    relatorio_vms = f"""
    <div class="error-container">
        <div class="error-icon">[ERROR]</div>
        <div class="error-title">Erro no módulo de VMs</div>
        <div class="error-message">{str(e)}</div>
    </div>
    """

# Debug das VMs após processamento
print(f"[CHECK] Debug VMs (após processamento):")
print(f"   - VMs configuradas encontradas: {len(vms_configuradas) if 'vms_configuradas' in locals() else 0}")
print(f"   - VMs processadas: {len(vms_data)}")
print(f"   - VMs Online: {vms_online}")
print(f"   - VMs Offline: {vms_offline}")
if vms_data:
    for vm in vms_data:
        print(f"   - VM: {vm['name']} - Status: {vm['status']}")

# === 6. EXECUTA VERIFICAÇÃO DOS SWITCHES ===
print("[EXEC] Verificando status dos Switches...")
switches_data = []
switches_online = 0
switches_offline = 0
switches_html_content = ""
try:
    from gerenciar_switches import GerenciadorSwitches
    
    gerenciador_switches = GerenciadorSwitches()
    
    # Verifica TODOS os switches para relatório completo
    print("[EXEC] Verificando TODOS os switches (relatório completo)...")
    print("⏳ Isso pode demorar alguns minutos, aguarde...")
    switches_resultados = gerenciador_switches.verificar_todos_switches()
    
    if switches_resultados:
        # O método retorna um dicionário {nome_switch: resultado}
        for nome_switch, resultado in switches_resultados.items():
            status = resultado.get('status', 'offline')
            
            # Busca informações do switch na lista original
            switch_info = None
            for switch in gerenciador_switches.switches:
                if switch.get('host') == nome_switch:
                    switch_info = switch
                    break
            
            if switch_info:
                # Conta switches online/offline
                if status in ['online', 'warning']:
                    switches_online += 1
                    final_status = 'online'
                else:
                    switches_offline += 1
                    final_status = 'offline'
                
                switches_data.append({
                    'name': nome_switch,
                    'ip': switch_info.get('ip', 'N/A'),
                    'regional': switch_info.get('regional', 'N/A'),
                    'status': final_status,
                    'zabbix_status': status,
                    'last_check': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'detalhes': resultado.get('detalhes', {})
                })
        
        # Gera HTML dos switches
        total_switches = len(gerenciador_switches.switches)
        switches_html_content = f"""
        <div class='switches-container'>
            <div class='alert alert-success mb-3'>
                <h5>[DATA] Relatório Completo dos Switches</h5>
                <p><strong>Total de switches cadastrados:</strong> {total_switches}</p>
                <p><strong>Switches verificados nesta execução:</strong> {len(switches_data)}</p>
                <p><strong>Switches Online:</strong> {switches_online}</p>
                <p><strong>Switches Offline/Warning:</strong> {switches_offline}</p>
                <p><strong>Taxa de disponibilidade:</strong> {(switches_online/(switches_online+switches_offline)*100):.1f}% ({switches_online}/{switches_online+switches_offline})</p>
            </div>
            
            <div class='alert alert-info mb-3'>
                <h6>[URL] Resumo por Regional:</h6>
                <div class="row">
        """
        
        # Agrupa switches por regional
        regionais_resumo = {}
        for switch in switches_data:
            regional = switch['regional']
            if regional not in regionais_resumo:
                regionais_resumo[regional] = {'online': 0, 'offline': 0, 'total': 0}
            
            regionais_resumo[regional]['total'] += 1
            if switch['status'] == 'online':
                regionais_resumo[regional]['online'] += 1
            else:
                regionais_resumo[regional]['offline'] += 1
        
        # Adiciona resumo por regional
        for regional, dados in regionais_resumo.items():
            taxa = (dados['online']/dados['total']*100) if dados['total'] > 0 else 0
            switches_html_content += f"""
                    <div class="col-md-4 mb-2">
                        <strong>{regional}:</strong> {dados['online']}/{dados['total']} ({taxa:.0f}%)
                    </div>
            """
        
        switches_html_content += """
                </div>
            </div>
        """
        for switch in switches_data:
            status = switch.get('status', 'offline')
            zabbix_status = switch.get('zabbix_status', 'unknown')
            status_class = "success" if status == 'online' else "danger"
            
            # Adiciona classe warning se o status do Zabbix for warning
            if zabbix_status == 'warning':
                status_class = "warning"
            
            # Informações detalhadas dos problemas
            detalhes = switch.get('detalhes', {})
            problemas = detalhes.get('problemas', []) if isinstance(detalhes, dict) else []
            itens = detalhes.get('itens', []) if isinstance(detalhes, dict) else []
            
            problemas_html = ""
            if problemas:
                problemas_html = f"""
                <div class="mt-2">
                    <strong>[WARN] Problemas encontrados ({len(problemas)}):</strong>
                    <ul class="small">
                        {''.join([f"<li>{problema.get('name', 'Problema desconhecido')}</li>" for problema in problemas[:3]])}
                        {f"<li><em>... e mais {len(problemas)-3} problemas</em></li>" if len(problemas) > 3 else ""}
                    </ul>
                </div>
                """
            
            itens_html = ""
            if itens:
                itens_html = f"""
                <div class="mt-2">
                    <strong>[DATA] Itens monitorados:</strong> {len(itens)} itens
                </div>
                """
            
            switches_html_content += f"""
            <div class="switch-item mb-3">
                <div class="card">
                    <div class="card-header bg-{status_class} text-white">
                        <h5 class="mb-0">{switch['name']}</h5>
                        <small>ID Zabbix: {detalhes.get('host_id', 'N/A') if isinstance(detalhes, dict) else 'N/A'}</small>
                    </div>
                    <div class="card-body">
                        <p><strong>IP:</strong> {switch['ip']}</p>
                        <p><strong>Status:</strong> {status.title()}</p>
                        <p><strong>Status Zabbix:</strong> {zabbix_status.title()}</p>
                        <p><strong>Regional:</strong> {switch['regional']}</p>
                        <p><strong>Última verificação:</strong> {switch['last_check']}</p>
                        {problemas_html}
                        {itens_html}
                    </div>
                </div>
            </div>
            """
        switches_html_content += "</div>"
        
        if not switches_data:
            switches_html_content = """
            <div class="alert alert-warning">
                <div class="alert-icon">[WARN]</div>
                <div class="alert-title">Nenhum switch encontrado</div>
                <div class="alert-message">Verifique a configuração do Zabbix</div>
            </div>
            """
    else:
        switches_html_content = f"""
        <div class="error-container">
            <div class="error-icon">[ERROR]</div>
            <div class="error-title">Erro ao verificar switches</div>
            <div class="error-message">Erro na conexão com Zabbix ou falha na verificação dos switches</div>
        </div>
        """
        
except Exception as e:
    print(f"[ERRO] Erro no módulo de Switches: {e}")
    switches_html_content = f"""
    <div class="error-container">
        <div class="error-icon">[ERROR]</div>
        <div class="error-title">Erro no módulo de Switches</div>
        <div class="error-message">{str(e)}</div>
    </div>
    """

# Debug dos Switches após processamento
print(f"[CHECK] Debug Switches (após processamento):")
print(f"   - Switches processados: {len(switches_data)}")
print(f"   - Switches Online: {switches_online}")
print(f"   - Switches Offline: {switches_offline}")
if switches_data:
    print(f"   - Primeiros 5 switches:")
    for i, switch in enumerate(switches_data[:5]):
        print(f"     {i+1}. {switch['name']} - Status: {switch['status']} (Zabbix: {switch.get('zabbix_status', 'N/A')})")

# === 7. EXECUTA VERIFICAÇÃO DOS LINKS DE INTERNET ===
print("[EXEC] Verificando Links de Internet...")

links_data = []
links_online = 0
links_offline = 0
links_html_content = ""

try:
    from gerenciar_fortigate import GerenciadorFortigate
    from config import ENV_CONFIG

    fortigates = ENV_CONFIG.get("fortigate")

    if not isinstance(fortigates, dict):
        raise Exception("ENV_CONFIG['fortigate'] deve conter SP/RJ")

    # percorre SP, RJ, etc
    for regiao, cfg in fortigates.items():
        print(f"[EXEC] Fortigate {regiao} ({cfg.get('host')})")

        gerenciador = GerenciadorFortigate(
            host=cfg.get("host"),
            port=cfg.get("port"),
            username=cfg.get("username"),
            password=cfg.get("password"),
        )

        auth_result = gerenciador.autenticar()
        auth_success = auth_result is True or (
            isinstance(auth_result, dict) and auth_result.get("success")
        )

        if not auth_success:
            links_html_content += f"""
            <div class="error-container">
                <div class="error-title">Erro Fortigate {regiao}</div>
                <div class="error-message">Falha na autenticação</div>
            </div>
            """
            continue

        links_info = gerenciador.obter_estatisticas_links()

        if not links_info.get("success"):
            continue

        for link in links_info.get("links", []):
            status = link.get("status", "offline")
            if status == "online":
                links_online += 1
            else:
                links_offline += 1

            links_data.append({
                "regiao": regiao,
                "nome": link.get("alias") or link.get("nome"),
                "ip": link.get("ip", "N/A"),
                "status": status,
                "velocidade": link.get("velocidade", "N/A"),
                "tipo": link.get("tipo", "N/A"),
                "estatisticas": link.get("estatisticas") or {},
                "ultima_verificacao": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })



    # ===== HTML =====
    links_html_content = "<div class='links-container'>"

    for link in links_data:
        status_class = "success" if link["status"] == "online" else "danger"
        estat = link["estatisticas"]

        links_html_content += f"""
        <div class="link-item mb-3">
            <div class="card">
                <div class="card-header bg-{status_class}">
                    <h5 class="mb-0">{link['nome']}</h5>
                    <small>Região: {link['regiao']}</small>
                </div>
                <div class="card-body">
                    <p><strong>IP:</strong> {link['ip']}</p>
                    <p><strong>Status:</strong> {link['status'].title()}</p>
                    <p><strong>Velocidade:</strong> {link['velocidade']} Mbps</p>
                    <p><strong>Tipo:</strong> {link['tipo']}</p>

                    <hr>

                    <p><strong>Download:</strong> {estat.get('bandwidth_in_readable','N/A')}</p>
                    <p><strong>Upload:</strong> {estat.get('bandwidth_out_readable','N/A')}</p>

                    <p><strong>Última verificação:</strong> {link['ultima_verificacao']}</p>
                </div>
            </div>
        </div>
        """

    links_html_content += "</div>"

except Exception as e:
    print(f"[ERRO] Erro no módulo de Links: {e}")
    links_html_content = f"""
    <div class="error-container">
        <div class="error-title">Erro no módulo de Links</div>
        <div class="error-message">{e}</div>
    </div>
    """

# === 8. CARREGA HTMLs GERADOS ===
# Carrega o conteúdo dos arquivos HTML gerados. Se um arquivo não existir, fornece uma mensagem de erro.
# --- GPS: garante placeholder e tenta gerar o print ANTES de ler o arquivo ---
from gps_print import ensure_gps_placeholder, gerar_print_gps_amigo, gerar_print_saturno_portal
ensure_gps_placeholder()
try:
    gerar_print_gps_amigo()
    print("[GPS] Print gerado com sucesso.")
except Exception as e:
    print("[GPS] Falha ao gerar print:", e)

try:
    gerar_print_saturno_portal()
    print("[PRINT-REDE] Prints gerados com sucesso.")
except Exception as e:
    print("[PRINT-REDE] Falha ao gerar prints:", e)

# (opcional) monta o card para uso em outros lugares, se precisar
gps_section = render_bloco_gps()


# Se você injeta o card no topo, garanta que ele é montado DEPOIS de gerar o print:
gps_section = render_bloco_gps()


# Use sempre o helper que garante imagem inline (HTML ou PNG)
gps_html = _montar_gps_html()
print_rede_html = _montar_print_rede_html()


rep_html = REPLICACAO_HTML.read_text(encoding="utf-8") if REPLICACAO_HTML.exists() else """
<div class="error-container">
    <div class="error-icon">[ERROR]</div>
    <div class="error-title">Arquivo não encontrado</div>
    <div class="error-message">replsummary.html não encontrado</div>
</div>
"""
# Reconstrói regionais_html a partir dos blocos armazenados com seus status
regionais_html = "".join([block_string for block_string, _ in blocos_html_regionais_with_status])
if not blocos_html_regionais_with_status:
    regionais_html = """
    <div class="error-container">
        <div class="error-icon">[ERROR]</div>
        <div class="error-title">Nenhuma regional processada</div>
        <div class="error-message">Verifique o arquivo de conexões</div>
    </div>
    """
unifi_html = UNIFI_HTML.read_text(encoding="utf-8") if UNIFI_HTML.exists() else """
<div class="error-container">
    <div class="error-icon">[ERROR]</div>
    <div class="error-title">Arquivo não encontrado</div>
    <div class="error-message">dados_aps_unifi.html não encontrado</div>
</div>
"""

# === 9. KPIs e dados para os gráficos ===
# Calcula KPIs para verificações regionais baseado no status de erro armazenado
regionais_ok = sum(1 for _, has_error in blocos_html_regionais_with_status if not has_error)
regionais_erro = sum(1 for _, has_error in blocos_html_regionais_with_status if has_error)


# Debug Regionais
print(f"[CHECK] Debug Regionais:")
print(f"   - Regionais OK: {regionais_ok}")
print(f"   - Regionais com erro: {regionais_erro}")
print(f"   - Total de blocos processados: {len(blocos_html_regionais_with_status)}")
for i, (_, has_error) in enumerate(blocos_html_regionais_with_status):
    status = "ERRO" if has_error else "OK"
    print(f"   - Regional {i+1}: {status}")

# Determina o status do GPS: sucesso se o HTML embutiu a imagem OU se o PNG foi gerado
def _gps_ok():
    try:
        # 1) HTML com imagem base64
        if GPS_HTML.exists():
            txt = GPS_HTML.read_text(encoding="utf-8", errors="ignore")
            if "data:image/png;base64" in txt:
                return True
        # 2) PNG físico ao lado do print_temp.html
        png_path = GPS_HTML.with_name("gps_amigo.png")
        if png_path.exists() and png_path.stat().st_size > 10_000:  # >10KB evita falso-positivo
            return True
    except Exception:
        pass
    return False

gps_status_display = (
    "<i class='fas fa-check-circle text-green-500'></i> Sucesso"
    if _gps_ok() else
    "<i class='fas fa-times-circle text-red-500'></i> Erro"
)


# Conta APs online/offline do conteúdo HTML do UniFi
aps_online = unifi_html.count("Online") if "[ERROR]" not in unifi_html else 0
aps_offline = unifi_html.count("Offline") if "[ERROR]" not in unifi_html else 0

# Debug UniFi
print(f"[CHECK] Debug UniFi:")
print(f"   - APs Online: {aps_online}")
print(f"   - APs Offline: {aps_offline}")
print(f"   - HTML UniFi existe: {UNIFI_HTML.exists()}")
if "[ERROR]" in unifi_html:
    print(f"   - Erro detectado no HTML UniFi")

# === LÓGICA CORRETA DE CONTAGEM BASEADA EM LATÊNCIA E ERRO ===
# Lista de servidores com falha de replicação explícita (erros operacionais)
# Busca por padrões como "58 - ALDEBARAN.Galaxia.local" ou "58 - ELTANIN.Galaxia.local"
replication_errors_list = re.findall(r"\d+\s*-\s*([A-Z0-9\.\-]+\.(?:Galaxia\.)?local)", rep_html, re.IGNORECASE)

# Busca por dados na tabela HTML - padrão mais flexível
# Procura por linhas da tabela que contenham dados de servidor
table_rows = re.findall(r"<tr[^>]*>.*?<td[^>]*>([A-Z0-9\-]+)</td>.*?<td[^>]*>([^<]+)</td>.*?<td[^>]*>([^<]+)</td>.*?<td[^>]*>(\d+)</td>.*?</tr>", rep_html, re.IGNORECASE | re.DOTALL)

# Conta servidores com erro na tabela (coluna Erros > 0)
table_errors = 0
rep_ok = 0

# Processa cada linha da tabela
for servidor, latencia, sucesso_total, erros in table_rows:
    servidor_clean = servidor.strip().upper()
    erros_num = int(erros.strip())
    
    if erros_num > 0:
        table_errors += 1
    else:
        # Verifica se não está na lista de erros operacionais
        servidor_base = servidor_clean.split('.')[0]  # Remove domínio se houver
        is_in_error_list = any(servidor_base in erro.upper() or servidor_clean in erro.upper() for erro in replication_errors_list)
        
        # Conta como OK se não tem erros e não está na lista de erros operacionais
        if not is_in_error_list:
            rep_ok += 1

# Total de erros = erros operacionais + erros da tabela
rep_fail = len(replication_errors_list) + table_errors
rep_total = rep_ok + rep_fail

# Debug: adiciona informações para troubleshooting
print(f"[CHECK] Debug Replicação AD:")
print(f"   - Servidores OK: {rep_ok}")
print(f"   - Erros operacionais: {len(replication_errors_list)}")
print(f"   - Erros da tabela: {table_errors}")
print(f"   - Total de erros: {rep_fail}")
print(f"   - Total geral: {rep_total}")
if replication_errors_list:
    print(f"   - Lista de erros operacionais: {replication_errors_list}")
print(f"   - Linhas da tabela encontradas: {len(table_rows)}")

# Ensure rep_ok is not negative
if rep_ok < 0:
    rep_ok = 0

# Determine AD replication status display with icons.
if rep_fail == 0:
    rep_status_display = "<i class='fas fa-check-circle text-green-500'></i> Sucesso"
else:
    rep_status_display = "<i class='fas fa-times-circle text-red-500'></i> Erro"

# Debug das novas métricas
print(f"[CHECK] Debug VMs:")
print(f"   - VMs Online: {vms_online}")
print(f"   - VMs Offline: {vms_offline}")
print(f"   - Total de VMs: {len(vms_data)}")

print(f"[CHECK] Debug Switches:")
print(f"   - Switches Online: {switches_online}")
print(f"   - Switches Offline: {switches_offline}")
print(f"   - Total de Switches: {len(switches_data)}")

print(f"[CHECK] Debug Links de Internet:")
print(f"   - Links Online: {links_online}")
print(f"   - Links Offline: {links_offline}")
print(f"   - Total de Links: {len(links_data)}")

from gps_print import ensure_gps_placeholder, gerar_print_gps_amigo
ensure_gps_placeholder()
try:
    gerar_print_gps_amigo()
except Exception as e:
    print("[GPS] Falha ao gerar print:", e)

from config import GPS_HTML

def render_bloco_gps():
    """Lê o HTML do print e devolve só o conteúdo do <body>."""
    try:
        gps_html_full = GPS_HTML.read_text(encoding="utf-8")
    except FileNotFoundError:
        gps_html = "<div class='error'>Print GPS Amigo não encontrado.</div>"
    else:
        import re
        m = re.search(r"<body[^>]*>(.*?)</body>", gps_html_full, flags=re.IGNORECASE | re.DOTALL)
        gps_html = m.group(1).strip() if m else gps_html_full

    return f"""
    <section class="card">
      <h2>Print GPS Amigo</h2>
      <div class="card-body">
        {gps_html}
      </div>
    </section>
    """




# --- Garante que o print exista no Public (placeholder + tentativa real) ---
# --- GPS: garante arquivo e gera print real ---
from gps_print import ensure_gps_placeholder, gerar_print_gps_amigo
ensure_gps_placeholder()
try:
    gerar_print_gps_amigo()
except Exception as e:
    print("[GPS] Falha ao gerar print:", e)

# Card pronto (usa a função que você já tem na linha 26)
gps_section = render_bloco_gps()

# --- INÍCIO DA LÓGICA DE VPN ---
try:
    # 1. Busca os dados usando seu gerenciador existente
    dados_vpn = gerenciador_fortigate.obter_vpn_ipsec()
    lista_vpns = dados_vpn.get("vpns", []) if dados_vpn and dados_vpn.get("success") else []

    # 2. Calcula os contadores para os KPIs e Gráficos
    vpns_total = len(lista_vpns)
    # Considera 'up' como online, qualquer outra coisa como offline
    vpns_online = sum(1 for v in lista_vpns if v.get('status') == 'up')
    vpns_offline = vpns_total - vpns_online

    # 3. Gera o HTML da lista APENAS para as que estão offline (Status: down)
    # Filtra os nomes das VPNs com problema
    lista_nomes_offline = [v.get('tunel', 'Desconhecido') for v in lista_vpns if v.get('status') != 'up']

    if lista_nomes_offline:
        # Se tiver VPN fora, cria uma lista vermelha
        itens_li = "".join(f"<li style='margin-bottom: 5px;'><strong>{nome}</strong></li>" for nome in lista_nomes_offline)
        
        vpn_html_content = f"""
        <div class="error-container">
            <div class="error-icon"><i class="fas fa-unlink"></i></div>
            <div class="error-title">Atenção: {vpns_offline} Túneis Offline</div>
            <ul style="list-style: none; padding: 0;">
                {itens_li}
            </ul>
        </div>
        """
    else:
        # Se tudo estiver OK
        vpn_html_content = """
        <div style="text-align: center; color: #48bb78; padding: 20px;">
            <i class="fas fa-check-circle" style="font-size: 2rem; margin-bottom: 10px;"></i>
            <h3>Todos os túneis estão operacionais</h3>
        </div>
        """

except Exception as e:
    # Caso falhe a conexão com o Fortigate ao gerar o dash
    vpns_online = 0
    vpns_offline = 0
    vpn_html_content = f"<div class='error-container'>Erro ao consultar Fortigate: {str(e)}</div>"
# --- FIM DA LÓGICA DE VPN ---

# === 10. MONTA DASHBOARD FINAL ===
# Construct the final HTML dashboard using f-strings for dynamic content insertion.
dashboard_html = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Dashboard Consolidado</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <!-- Font Awesome for icons -->
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0-beta3/css/all.min.css">
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');
        
        :root {{
            --primary-gradient: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            --secondary-gradient: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
            --success-gradient: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%);
            --warning-gradient: linear-gradient(135deg, #43e97b 0%, #38f9d7 100%);
            --error-gradient: linear-gradient(135deg, #fa709a 0%, #fee140 100%);
            --neutral-gradient: linear-gradient(135deg, #a8edea 0%, #fed6e3 100%);
            --glass-bg: rgba(255, 255, 255, 0.25);
            --glass-border: rgba(255, 255, 255, 0.18);
            --shadow-soft: 0 8px 32px 0 rgba(31, 38, 135, 0.37);
            --shadow-hover: 0 15px 35px rgba(31, 38, 135, 0.2);
        }}
        
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 50%, #f093fb 100%);
            background-attachment: fixed;
            color: #2d3748;
            line-height: 1.6;
            min-height: 100vh;
        }}
        
        .main-container {{
            backdrop-filter: blur(10px);
            background: var(--glass-bg);
            border: 1px solid var(--glass-border);
            border-radius: 20px;
            margin: 20px;
            padding: 40px;
            box-shadow: var(--shadow-soft);
        }}
        
        .page-title {{
            background: var(--primary-gradient);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
            font-size: 3.5rem;
            font-weight: 800;
            text-align: center;
            margin-bottom: 10px;
            letter-spacing: -0.02em;
        }}
        
        .page-subtitle {{
            text-align: center;
            color: rgba(45, 55, 72, 0.8);
            font-size: 1.1rem;
            font-weight: 500;
            margin-bottom: 40px;
        }}
        
        .kpi-container {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 20px;
            margin-bottom: 40px;
        }}
        
        .kpi {{
            background: rgba(255, 255, 255, 0.9);
            backdrop-filter: blur(10px);
            border: 1px solid rgba(255, 255, 255, 0.2);
            border-radius: 16px;
            padding: 24px;
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            position: relative;
            overflow: hidden;
        }}
        
        .kpi::before {{
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            height: 4px;
            background: var(--primary-gradient);
            border-radius: 16px 16px 0 0;
        }}
        
        .kpi:hover {{
            transform: translateY(-8px);
            box-shadow: var(--shadow-hover);
            background: rgba(255, 255, 255, 0.95);
        }}
        
        .kpi-header {{
            display: flex;
            align-items: center;
            gap: 12px;
            margin-bottom: 16px;
        }}
        
        .kpi-icon {{
            width: 40px;
            height: 40px;
            border-radius: 10px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 18px;
            color: white;
        }}
        
        .kpi-icon.success {{ background: var(--success-gradient); }}
        .kpi-icon.error {{ background: var(--error-gradient); }}
        .kpi-icon.warning {{ background: var(--warning-gradient); }}
        .kpi-icon.info {{ background: var(--primary-gradient); }}
        .kpi-icon.neutral {{ background: var(--neutral-gradient); }}
        
        .kpi-header h3 {{
            font-size: 0.9rem;
            font-weight: 600;
            color: #4a5568;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }}
        
        .kpi-value {{
            font-size: 2.5rem;
            font-weight: 700;
            color: #2d3748;
            margin-bottom: 8px;
        }}
        
        .kpi-status {{
            display: flex;
            align-items: center;
            gap: 8px;
            font-size: 0.9rem;
            font-weight: 500;
        }}
        
        .kpi ul {{
            font-size: 0.85rem;
            margin-top: 12px;
            padding-left: 20px;
            color: #e53e3e;
        }}
        
        .charts-section {{
            margin: 50px 0;
        }}
        
        .section-title {{
            font-size: 2.2rem;
            font-weight: 700;
            text-align: center;
            margin-bottom: 30px;
            background: var(--primary-gradient);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }}
        
        .charts-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(350px, 1fr));
            gap: 30px;
        }}
        
        .chart-wrapper {{
            background: rgba(255, 255, 255, 0.9);
            backdrop-filter: blur(10px);
            border: 1px solid rgba(255, 255, 255, 0.2);
            border-radius: 20px;
            padding: 30px;
            box-shadow: var(--shadow-soft);
            transition: all 0.3s ease;
            min-height: 350px;
            display: flex;
            justify-content: center;
            align-items: center;
        }}
        
        .chart-wrapper:hover {{
            transform: translateY(-5px);
            box-shadow: var(--shadow-hover);
        }}
        
        .divider {{
            height: 2px;
            background: var(--primary-gradient);
            border: none;
            border-radius: 2px;
            margin: 50px 0;
            opacity: 0.3;
        }}
        
        .details-section {{
            background: rgba(255, 255, 255, 0.9);
            backdrop-filter: blur(10px);
            border: 1px solid rgba(255, 255, 255, 0.2);
            border-radius: 16px;
            margin-bottom: 20px;
            overflow: hidden;
            box-shadow: var(--shadow-soft);
            transition: all 0.3s ease;
        }}
        
        .details-section:hover {{
            box-shadow: var(--shadow-hover);
        }}
        
        .details-section summary {{
            background: rgba(255, 255, 255, 0.1);
            padding: 20px 30px;
            cursor: pointer;
            font-size: 1.3rem;
            font-weight: 600;
            color: #2d3748;
            border-bottom: 1px solid rgba(255, 255, 255, 0.1);
            transition: all 0.3s ease;
            position: relative;
        }}
        
        .details-section summary:hover {{
            background: rgba(255, 255, 255, 0.2);
        }}
        
        .details-section summary::marker {{
            display: none;
        }}
        
        .details-section summary::before {{
            content: '';
            position: absolute;
            right: 30px;
            top: 50%;
            transform: translateY(-50%);
            transition: transform 0.3s ease;
            color: #667eea;
            font-size: 1.2rem;
        }}
        
        .details-section[open] summary::before {{
            transform: translateY(-50%) rotate(90deg);
        }}
        
        .details-content {{
            padding: 30px;
            background: rgba(255, 255, 255, 0.05);
        }}
        
        .regional-item {{
            background: rgba(255, 255, 255, 0.8);
            border: 1px solid rgba(255, 255, 255, 0.3);
            border-radius: 12px;
            margin-bottom: 16px;
            overflow: hidden;
            box-shadow: 0 4px 16px rgba(31, 38, 135, 0.15);
        }}
        
        .regional-item summary {{
            background: rgba(255, 255, 255, 0.1);
            padding: 16px 20px;
            font-weight: 600;
            color: #4a5568;
        }}
        
        .regional-content {{
            padding: 20px;
            background: rgba(255, 255, 255, 0.9);
        }}
        
        .error-container {{
            background: linear-gradient(135deg, #fa709a 0%, #fee140 100%);
            color: white;
            padding: 20px;
            border-radius: 12px;
            text-align: center;
            box-shadow: 0 4px 16px rgba(250, 112, 154, 0.3);
            margin: 10px 0;
        }}
        
        .error-icon {{
            font-size: 2rem;
            margin-bottom: 10px;
        }}
        
        .error-title {{
            font-size: 1.2rem;
            font-weight: 600;
            margin-bottom: 8px;
        }}
        
        .error-message {{
            font-size: 0.9rem;
            opacity: 0.9;
        }}
        
        /* Responsive adjustments */
        @media (max-width: 768px) {{
            .main-container {{
                margin: 10px;
                padding: 20px;
            }}
            
            .page-title {{
                font-size: 2.5rem;
            }}
            
            .kpi-container {{
                grid-template-columns: 1fr;
            }}
            
            .charts-grid {{
                grid-template-columns: 1fr;
            }}
        }}

        /* Força texto preto nos cards de links de Internet */
    .links-container,
    .links-container p,
    .links-container span,
    .links-container strong,
    .link-item .card-body,
    .link-item .card-body p {{
        color: #000 !important;
    }}

    /* Mantém o título (WAN1, WAN2) preto */
    .link-item .card-header h5 {{
        color: #000 !important;
    }}
    </style>
</head>
<body>
    <div class="main-container">
        <h1 class="page-title">Dashboard Consolidado</h1>
        <p class="page-subtitle"><strong>Executado em:</strong> {data_execucao}</p>

        <div class="kpi-container">
            <div class="kpi">
                <div class="kpi-header">
                    <div class="kpi-icon success">
                        <i class="fas fa-check-circle"></i>
                    </div>
                    <h3>Regionais OK</h3>
                </div>
                <div class="kpi-value">{regionais_ok}</div>
            </div>
            <div class="kpi">
                <div class="kpi-header">
                    <div class="kpi-icon error">
                        <i class="fas fa-times-circle"></i>
                    </div>
                    <h3>Regionais com Erro</h3>
                </div>
                <div class="kpi-value">{regionais_erro}</div>
            </div>
            <div class="kpi">
                <div class="kpi-header">
                    <div class="kpi-icon info">
                        <i class="fas fa-wifi"></i>
                    </div>
                    <h3>APs Online</h3>
                </div>
                <div class="kpi-value">{aps_online}</div>
            </div>
            <div class="kpi">
                <div class="kpi-header">
                    <div class="kpi-icon neutral">
                        <i class="fas fa-exclamation-triangle"></i>
                    </div>
                    <h3>APs Offline</h3>
                </div>
                <div class="kpi-value">{aps_offline}</div>
            </div>
            <div class="kpi">
                <div class="kpi-header">
                    <div class="kpi-icon warning">
                        <i class="fas fa-map-marker-alt"></i>
                    </div>
                    <h3>Status do GPS</h3>
                </div>
                <div class="kpi-status">
                    {gps_status_display}
                </div>
            </div>
            <div class="kpi">
                <div class="kpi-header">
                    <div class="kpi-icon info">
                        <i class="fas fa-sync-alt"></i>
                    </div>
                    <h3>Replicação AD</h3>
                </div>
                <div class="kpi-status">
                    {rep_status_display}
                </div>
                {"<ul>" + ''.join(f"<li>{srv}</li>" for srv in replication_errors_list) + "</ul>" if replication_errors_list else ""}
            </div>
            <div class="kpi">
                <div class="kpi-header">
                    <div class="kpi-icon success">
                        <i class="fas fa-desktop"></i>
                    </div>
                    <h3>VMs Online</h3>
                </div>
                <div class="kpi-value">{vms_online}</div>
            </div>
            <div class="kpi">
                <div class="kpi-header">
                    <div class="kpi-icon error">
                        <i class="fas fa-desktop"></i>
                    </div>
                    <h3>VMs Offline</h3>
                </div>
                <div class="kpi-value">{vms_offline}</div>
            </div>
            <div class="kpi">
                <div class="kpi-header">
                    <div class="kpi-icon success">
                        <i class="fas fa-network-wired"></i>
                    </div>
                    <h3>Switches Online</h3>
                </div>
                <div class="kpi-value">{switches_online}</div>
            </div>
            <div class="kpi">
                <div class="kpi-header">
                    <div class="kpi-icon error">
                        <i class="fas fa-network-wired"></i>
                    </div>
                    <h3>Switches Offline</h3>
                </div>
                <div class="kpi-value">{switches_offline}</div>
            </div>
            <div class="kpi">
                <div class="kpi-header">
                    <div class="kpi-icon success">
                        <i class="fas fa-globe"></i>
                    </div>
                    <h3>Links Online</h3>
                </div>
                <div class="kpi-value">{links_online}</div>
            </div>
            <div class="kpi">
                <div class="kpi-header">
                    <div class="kpi-icon error">
                        <i class="fas fa-globe"></i>
                    </div>
                    <h3>Links Offline</h3>
                </div>
                <div class="kpi-value">{links_offline}</div>
            </div>
            <div class="kpi">
                <div class="kpi-header">
                    <div class="kpi-icon info">
                        <i class="fas fa-shield-alt"></i>
                    </div>
                    <h3>VPNs IPSEC</h3>
                </div>
                <div class="kpi-status">
                   <span style="color: #48bb78; font-weight: bold;">Online: {vpns_online}</span>
                   <span style="margin: 0 5px;">|</span>
                   <span style="color: #f56565; font-weight: bold;">Offline: {vpns_offline}</span>
                </div>
            </div>
            
        </div>

        <!-- GRÁFICOS -->
        <div class="charts-section">
            <h2 class="section-title">[DATA] Visão Geral em Gráficos</h2>
            <div class="charts-grid">
                <div class="chart-wrapper">
                    <canvas id="chartRegionais"></canvas>
                </div>
                <div class="chart-wrapper">
                    <canvas id="chartUnifi"></canvas>
                </div>
                <div class="chart-wrapper">
                    <canvas id="chartReplicacao"></canvas>
                </div>
                <div class="chart-wrapper">
                    <canvas id="chartVMs"></canvas>
                </div>
                <div class="chart-wrapper">
                    <canvas id="chartSwitches"></canvas>
                </div>
                <div class="chart-wrapper">
                    <canvas id="chartLinks"></canvas>
                </div>
                <div class="chart-wrapper">
                    <canvas id="chartVpn"></canvas>
                </div>
            </div>
        </div>

        <hr class="divider">

        <details open id="regionais" class="details-section">
            <summary>[SERVER] Status das Regionais (iDRAC/iLO)</summary>
            <div class="details-content">
                {regionais_html}
            </div>
        </details>

        <details id="gps" class="details-section">
            <summary>[URL] Print GPS Amigo</summary>
            <div class="details-content">
                {gps_html}
            </div>
        </details>

        <details id="print-rede" class="details-section">
            <summary>[URL] Print Rede</summary>
            <div class="details-content">
                {print_rede_html}
            </div>
        </details>

        <details id="replicacao" class="details-section">
            <summary>[UPDATE] Status de Replicação do Active Directory</summary>
            <div class="details-content">
                {rep_html}
            </div>
        </details>

        <details id="unifi" class="details-section">
            <summary> Status das Antenas UniFi (por site)</summary>
            <div class="details-content">
                {unifi_html}
            </div>
        </details>

        <details id="vms" class="details-section">
            <summary>[PC] Status das Máquinas Virtuais</summary>
            <div class="details-content">
                {relatorio_vms}
            </div>
        </details>

        <details id="switches" class="details-section">
            <summary> Status dos Switches</summary>
            <div class="details-content">
                {switches_html_content}
            </div>
        </details>

        <details id="links" class="details-section">
            <summary>[WEB] Status dos Links de Internet</summary>
            <div class="details-content">
                {links_html_content}
            </div>
        </details>
        <details id="vpn-details" class="details-section">
            <summary>[FORTIGATE] Status VPNs IPSEC</summary>
            <div class="details-content">
                {vpn_html_content}
            </div>
        </details>
    </div>

<script>
// Global configuration to make charts responsive
Chart.defaults.responsive = true;
Chart.defaults.maintainAspectRatio = false; // Important to allow the container to control the aspect ratio

new Chart(document.getElementById('chartRegionais'), {{
    type: 'doughnut',
    data: {{
        labels: ['OK', 'Erro'],
        datasets: [{{
            data: [{regionais_ok}, {regionais_erro}],
            backgroundColor: ['#4CAF50', '#F44336'],
            borderColor: '#ffffff',
            borderWidth: 2
        }}]
    }},
    options: {{
        plugins: {{
            title: {{
                display: true,
                text: 'Status Servidores iDRAC/iLO',
                font: {{
                    size: 16
                }},
                color: '#333'
            }},
            legend: {{
                position: 'bottom',
                labels: {{
                    font: {{
                        size: 14
                    }},
                    color: '#555'
                }}
            }}
        }}
    }}
}});

new Chart(document.getElementById('chartUnifi'), {{
    type: 'doughnut',
    data: {{
        labels: ['Online', 'Offline'],
        datasets: [{{
            data: [{aps_online}, {aps_offline}],
            backgroundColor: ['#2196F3', '#B0BEC5'],
            borderColor: '#ffffff',
            borderWidth: 2
        }}]
    }},
    options: {{
        plugins: {{
            title: {{
                display: true,
                text: 'APs Online vs Offline',
                font: {{
                    size: 16
                }},
                color: '#333'
            }},
            legend: {{
                position: 'bottom',
                labels: {{
                    font: {{
                        size: 14
                    }},
                    color: '#555'
                }}
            }}
        }}
    }}
}});

new Chart(document.getElementById('chartReplicacao'), {{
    type: 'doughnut',
    data: {{
        labels: ['OK', 'Com Falha'],
        datasets: [{{
            data: [{rep_ok}, {rep_fail}],
            backgroundColor: ['#8BC34A', '#FF7043'],
            borderColor: '#ffffff',
            borderWidth: 2
        }}]
    }},
    options: {{
        plugins: {{
            title: {{
                display: true,
                text: 'Replicação AD',
                font: {{
                    size: 16
                }},
                color: '#333'
            }},
            legend: {{
                position: 'bottom',
                labels: {{
                    font: {{
                        size: 14
                    }},
                    color: '#555'
                }}
            }}
        }}
    }}
}});

new Chart(document.getElementById('chartVMs'), {{
    type: 'doughnut',
    data: {{
        labels: ['Online', 'Offline'],
        datasets: [{{
            data: [{vms_online}, {vms_offline}],
            backgroundColor: ['#4CAF50', '#F44336'],
            borderColor: '#ffffff',
            borderWidth: 2
        }}]
    }},
    options: {{
        plugins: {{
            title: {{
                display: true,
                text: 'Status das VMs',
                font: {{
                    size: 16
                }},
                color: '#333'
            }},
            legend: {{
                position: 'bottom',
                labels: {{
                    font: {{
                        size: 14
                    }},
                    color: '#555'
                }}
            }}
        }}
    }}
}});

new Chart(document.getElementById('chartSwitches'), {{
    type: 'doughnut',
    data: {{
        labels: ['Online', 'Offline'],
        datasets: [{{
            data: [{switches_online}, {switches_offline}],
            backgroundColor: ['#2196F3', '#FF9800'],
            borderColor: '#ffffff',
            borderWidth: 2
        }}]
    }},
    options: {{
        plugins: {{
            title: {{
                display: true,
                text: 'Status dos Switches',
                font: {{
                    size: 16
                }},
                color: '#333'
            }},
            legend: {{
                position: 'bottom',
                labels: {{
                    font: {{
                        size: 14
                    }},
                    color: '#555'
                }}
            }}
        }}
    }}
}});

new Chart(document.getElementById('chartLinks'), {{
    type: 'doughnut',
    data: {{
        labels: ['Online', 'Offline'],
        datasets: [{{
            data: [{links_online}, {links_offline}],
            backgroundColor: ['#9C27B0', '#E91E63'],
            borderColor: '#ffffff',
            borderWidth: 2
        }}]
    }},
    options: {{
        plugins: {{
            title: {{
                display: true,
                text: 'Links de Internet',
                font: {{
                    size: 16
                }},
                color: '#333'
            }},
            legend: {{
                position: 'bottom',
                labels: {{
                    font: {{
                        size: 14
                    }},
                    color: '#555'
                }}
            }}
        }}
    }}
}});

new Chart(document.getElementById('chartVpn'), {{
    type: 'doughnut',
    data: {{
        labels: ['Online', 'Offline'],
        datasets: [{{
            data: [{vpns_online}, {vpns_offline}],
            backgroundColor: ['#4facfe', '#fa709a'],
            borderColor: '#ffffff',
            borderWidth: 2
        }}]
    }},
    options: {{
        plugins: {{
            title: {{
                display: true,
                text: 'Status Túneis VPN',
                font: {{ size: 16 }},
                color: '#333'
            }},
            legend: {{
                position: 'bottom',
                labels: {{ font: {{ size: 14 }}, color: '#555' }}
            }}
        }}
    }}
}});

</script>

</body>
</html>
"""




# === 10. SALVA O RELATÓRIO ===
# Salva o relatório no novo local (área de trabalho com estrutura de pastas)
DASHBOARD_FINAL.write_text(dashboard_html, encoding="utf-8")
print(f"[OK] Relatório salvo em: {DASHBOARD_FINAL}")

# Também salva no local original para compatibilidade
DASHBOARD_FINAL_ORIGINAL.write_text(dashboard_html, encoding="utf-8")
print(f"[OK] Cópia de compatibilidade salva em: {DASHBOARD_FINAL_ORIGINAL}")



# Exibe informações sobre a estrutura criada
print(f"\n[DIR] Estrutura de Relatório Preventiva:")
print(f"   - Pasta base: {RELATORIO_PREVENTIVA_DIR.parent.parent}")
print(f"   - Ano: {RELATORIO_PREVENTIVA_DIR.parent.parent.name}")
print(f"   - Mês: {RELATORIO_PREVENTIVA_DIR.parent.name}")
print(f"   - Dia: {RELATORIO_PREVENTIVA_DIR.name}")
print(f"   - Arquivo: {DASHBOARD_FINAL.name}")
print(f"\n[TARGET] Acesse o relatório em: {DASHBOARD_FINAL}")

# === 11. REMOVE ARQUIVOS TEMPORÁRIOS ===
# Limpa arquivos HTML temporários gerados durante o processo
for file in REGIONAL_HTMLS_DIR.glob("*.html"):
    file.unlink() # Remove cada arquivo HTML regional
if GPS_HTML.exists():
    GPS_HTML.unlink() # Remove o arquivo HTML do GPS
if REPLICACAO_HTML.exists():
    REPLICACAO_HTML.unlink() # Remove o arquivo HTML do resumo de replicação
if UNIFI_HTML.exists():
    UNIFI_HTML.unlink() # Remove o arquivo HTML dos dados das APs UniFi

# Remove arquivos temporários das novas funcionalidades
vms_temp_file = PROJECT_ROOT / "output" / "relatorio_vms.html"
if vms_temp_file.exists():
    vms_temp_file.unlink() # Remove o arquivo HTML temporário das VMs

# === 12. ABRE NO NAVEGADOR ===
# Abre o arquivo HTML do dashboard gerado no navegador padrão, exceto em modo automático
if AUTO_NO_BROWSER:
    print(f"\n[AUTO] Execução automática concluída. Navegador não será aberto.")
    print(f"[URL] Relatório gerado em: {DASHBOARD_FINAL}")
else:
    print(f"\n[WEB] Abrindo relatório no navegador...")
    print(f"[URL] Local: {DASHBOARD_FINAL}")
    webbrowser.open(DASHBOARD_FINAL.resolve().as_uri())

print(f"\n[SUCCESS] Relatório Preventiva gerado com sucesso!")
print(f" Localização: {DASHBOARD_FINAL}")
print(f" Data/Hora: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
print(f"[DIR] Estrutura: Desktop/Relatório Preventiva/{RELATORIO_PREVENTIVA_DIR.parent.parent.name}/{RELATORIO_PREVENTIVA_DIR.parent.name}/{RELATORIO_PREVENTIVA_DIR.name}/")
