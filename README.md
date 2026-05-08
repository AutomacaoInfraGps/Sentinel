# Sistema de Automação - Dashboard Consolidado

Sistema escalável para monitoramento de infraestrutura com dashboard tecnológico moderno.

## 🚀 Características

- **Caminhos Dinâmicos**: Sistema totalmente portável entre ambientes
- **Configuração Centralizada**: Todas as configurações em arquivos JSON
- **Design Moderno**: Interface minimalista com gradientes e efeitos glassmorphism
- **Escalável**: Fácil adição de novas regionais e serviços
- **Multiplataforma**: Funciona em Windows, Linux e macOS

## 📁 Estrutura do Projeto

```
Automação/
├── config.py              # Configurações centralizadas
├── environment.json       # Credenciais e configurações do ambiente
├── Conexoes.txt           # Lista de regionais para monitoramento
├── setup.py               # Script de configuração inicial
├── executar_tudo.py       # Script principal
├── output/                # Diretório de saída (criado automaticamente)
│   ├── dashboard_final.html
│   ├── htmls_regionais/
│   └── ...
└── logs/                  # Logs do sistema (criado automaticamente)
```

## 🛠️ Instalação

### 1. Configuração Inicial

Execute o script de configuração:

```bash
python setup.py
```

Este script irá:
- Criar os diretórios necessários
- Gerar templates de configuração
- Verificar dependências
- Validar o ambiente

## 🧙‍♂️ Configuração Inicial (Primeira Vez)

### 🌐 Método 1: Interface Web (RECOMENDADO)
```bash
powershell -ExecutionPolicy Bypass -File .\restart_web_service.ps1
```
**Interface moderna e intuitiva!** Acesse: http://localhost:5000
- 🎨 Design responsivo e moderno
- ✅ Validação em tempo real
- 🔍 Teste de conectividade integrado
- 📊 Dashboard com estatísticas

### 🧙‍♂️ Método 2: Wizard Terminal
```bash
python configure.py
```
O wizard irá guiá-lo através de todas as configurações necessárias!

### 🔧 Método 3: Template Rápido
```bash
# Para empresa média (recomendado)
python -c "from templates_configuracao import TemplatesConfiguracao; TemplatesConfiguracao().aplicar_template('empresa_media')"

# Depois configure seus servidores
python manage.py add
```

## 🛠️ Gerenciamento de Servidores

### 🌐 Via Interface Web (Recomendado)
```bash
powershell -ExecutionPolicy Bypass -File .\restart_web_service.ps1
# Acesse: http://localhost:5000 → Seção "Servidores"
```

### 💻 Via Terminal (Avançado)
```bash
# Listar servidores
python manage.py list

# Testar conectividade
python manage.py test-all

# Ver status geral
python manage.py status
```

## 🚀 Execução

Execute o sistema completo:

```bash
python executar_tudo.py
```

O sistema irá:
1. Verificar todas as regionais e servidores configurados
2. Capturar screenshot do GPS Amigo
3. Verificar replicação do Active Directory
4. Coletar dados das antenas UniFi
5. Gerar dashboard consolidado
6. Abrir automaticamente no navegador

## 📚 Documentação Completa
- 📖 **[Guia de Configuração](GUIA_CONFIGURACAO.md)** - Tutorial completo
- 🔧 **[Gerenciamento de Servidores](GUIA_CONFIGURACAO.md#-gerenciamento-de-servidores)** - Como adicionar/remover servidores
- 💾 **[Backup e Restauração](GUIA_CONFIGURACAO.md#-backup-e-restauração)** - Como fazer backup das configurações

## 📊 Funcionalidades

### Dashboard Principal
- **KPIs Visuais**: Métricas importantes em cards modernos
- **Gráficos Interativos**: Visualização dos dados em tempo real
- **Seções Expansíveis**: Detalhes organizados por categoria
- **Design Responsivo**: Funciona em desktop e mobile

### Monitoramento Incluído
- ✅ Status de servidores por regional com função operacional
- ✅ Cadastro e monitoramento de switches via Zabbix
- ✅ Replicação do Active Directory
- ✅ Status das antenas UniFi
- ✅ Cadastro de E-mails SLA com edição por regional
- ✅ Status das VPNS(IPSEC) com tuneis 
- ✅ Screenshot do GPS Amigo
- ✅ Análise de melhores práticas (BPA)

## 🔧 Personalização

### Adicionando Novas Regionais

Use preferencialmente a interface web em `http://localhost:5000`:

1. Abra `Regionais` para cadastrar ou editar a estrutura.
2. Em cada regional, use `Adicionar Servidor` e preencha a função do servidor, como `RODC`, `DC`, `WSUS`, `API` ou outra função operacional.
3. Use `Switches` para cadastrar e manter os equipamentos monitorados via Zabbix.
4. Use `Cadastro de E-mails SLA` para manter os contatos por regional na planilha externa configurada no sistema.

### Modificando Configurações

Edite o arquivo `environment.json` para:
- Alterar timeouts de conexão
- Configurar limpeza de arquivos temporários
- Adicionar novos serviços

### Personalizando o Design

O design pode ser personalizado editando as variáveis CSS em `executar_tudo.py`:

```css
:root {
    --primary-gradient: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    --success-gradient: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%);
    /* ... outras variáveis ... */
}
```

## 🔒 Segurança

- **Credenciais Separadas**: Senhas ficam no `environment.json` (não no código)
- **Arquivo .gitignore**: Evita commit acidental de credenciais
- **Planilhas Sensíveis Fora do Git**: Bases como `Lideres.xlsx`, `switches_zabbix.xlsx` e backups `.xlsx` devem permanecer apenas no ambiente local
- **Validação de Entrada**: Verificação de configurações antes da execução

### Arquivos Que Não Devem Ser Versionados

Antes de publicar o projeto em Git, mantenha fora do repositório:

- `environment.json`
- `Conexoes.txt`
- planilhas operacionais e backups (`*.xlsx`, `*.xls`, `*.xlsm`, `*.csv`)
- arquivos de autenticação e sessão (`auth_state.json`, perfis locais do navegador)
- saídas geradas automaticamente (`output/`, `logs/`, relatórios e auditorias locais)

Se em algum momento for necessário versionar a estrutura de uma planilha, use apenas um arquivo de exemplo sanitizado, sem nomes reais, e-mails reais, senhas, IPs, tokens ou qualquer dado operacional.

### Antes de Subir Para Git

1. Revise se não existem credenciais, e-mails reais, IPs internos ou planilhas operacionais na área de commit.
2. Confirme que o `.gitignore` está cobrindo os arquivos locais do ambiente.
3. Se algum arquivo sensível já tiver sido adicionado anteriormente ao Git, remova-o do índice antes do push com `git rm --cached <arquivo>`.

## 📝 Logs

Os logs são salvos automaticamente em:
- `logs/`: Logs de execução por script
- `output/`: Arquivos HTML gerados

## 🆘 Solução de Problemas

### Erro: "Arquivo environment.json não encontrado"
Execute: `python setup.py`

### Erro: "Dependências faltando"
Instale as dependências:
```bash
pip install requests playwright
```

### Erro de conexão com regionais
Verifique:
1. IPs corretos no `Conexoes.txt`
2. Credenciais no `environment.json`
3. Conectividade de rede

## 🔄 Atualizações

Para atualizar o sistema:
1. Faça backup do `environment.json` e `Conexoes.txt`
2. Substitua os arquivos do sistema
3. Execute `python setup.py` para validar

## 📞 Suporte

Para suporte técnico:
1. Verifique os logs em `logs/`
2. Execute `python config.py` para validar configurações
3. Consulte a documentação dos erros específicos

---

**Desenvolvido para ser escalável e fácil de manter** 🚀