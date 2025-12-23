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
python iniciar_web.py
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
python iniciar_web.py
# Acesse: http://localhost:5000 → Seção "Servidores"
```

### 💻 Via Terminal (Avançado)
```bash
# Listar servidores
python manage.py list

# Adicionar servidor
python manage.py add --nome "Servidor SP" --tipo idrac --ip "10.1.1.100" --usuario root --senha "senha123"

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
1. Verificar todas as regionais (iDRAC/iLO)
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
- ✅ Status de servidores (iDRAC/iLO)
- ✅ Replicação do Active Directory
- ✅ Status das antenas UniFi
- ✅ Screenshot do GPS Amigo
- ✅ Análise de melhores práticas (BPA)

## 🔧 Personalização

### Adicionando Novas Regionais

1. Edite o arquivo `Conexoes.txt`
2. Adicione o bloco da nova regional:

```
Nome: NOVA_REGIONAL
Tipo: idrac  # ou 'ilo'
IP: 192.168.1.200
Usuario: root
Senha: calvin
```

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
- **Validação de Entrada**: Verificação de configurações antes da execução

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