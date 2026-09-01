# Informações do Projeto

## 📁 Estrutura Organizada

Este projeto foi organizado automaticamente para manter apenas os arquivos essenciais.

### Scripts Principais
- `executar_tudo.py` - Script principal que executa todo o sistema
- `config.py` - Configurações centralizadas
- `setup.py` - Configuração inicial do projeto
- `validate_system.py` - Validação do sistema

### Scripts de Coleta
- `Chelist.py` - Coleta dados iDRAC
- `iLOcheck.py` - Coleta dados iLO  
- `Unifi.Py` - Coleta dados UniFi
- `utilizarSession.py` - Captura GPS Amigo
- `gerar_status_html.py` - Status do servidor NAOS
- `Replicacao_Servers.ps1` - Replicação AD

### Configurações
- `environment.json` - Credenciais e configurações
- `Conexoes.txt` - Lista de regionais
- `auth_state.json` - Sessão do navegador

### Saída
- `output/` - Todos os arquivos gerados
  - `dashboard_final.html` - Dashboard principal
  - `htmls_regionais/` - HTMLs das regionais
  - Outros arquivos temporários

### Documentação
- `README.md` - Documentação completa
- `CHANGELOG.md` - Histórico de mudanças

## 🚀 Como Usar

1. Execute: `python setup.py` (primeira vez)
2. Configure: `environment.json` e `Conexoes.txt`
3. Execute: `python executar_tudo.py`
4. Acesse: `output/dashboard_final.html`

## 🧹 Limpeza

Para reorganizar novamente: `python cleanup_project.py`
