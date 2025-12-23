# 🧙‍♂️ Guia de Configuração do Sistema

## 🚀 Configuração Inicial (Primeira Vez)

### 🌐 Método 1: Interface Web (RECOMENDADO)
```bash
python iniciar_web.py
```
**A interface web oferece:**
- 🎨 Interface visual moderna e intuitiva
- 📱 Design responsivo (funciona no celular)
- ✅ Validação em tempo real
- 🔍 Teste de conectividade integrado
- 📊 Dashboard com estatísticas
- 💾 Backup e restauração visual

**Acesse:** http://localhost:5000

### 🧙‍♂️ Método 2: Wizard Interativo (Terminal)
```bash
python configure.py
```
O wizard irá guiá-lo através de todas as etapas:
1. ✅ Verificação inicial
2. 🔐 Configuração de credenciais
3. 🖥️ Configuração de servidores
4. 🔍 Teste de conectividade
5. 🎉 Finalização

### 🔧 Método 3: Templates Pré-configurados
**Via Interface Web:** Acesse a seção "Templates" e clique em "Aplicar"

**Via Terminal:**
```bash
# Lista templates disponíveis
python -c "from templates_configuracao import TemplatesConfiguracao; t=TemplatesConfiguracao(); [print(f'• {nome}') for nome in t.listar_templates()]"

# Aplica um template
python -c "from templates_configuracao import TemplatesConfiguracao; TemplatesConfiguracao().aplicar_template('empresa_media')"
```

**Templates Disponíveis:**
- `empresa_pequena` - Para 1-3 servidores
- `empresa_media` - Para 4-10 servidores  
- `empresa_grande` - Para 10+ servidores
- `desenvolvimento` - Ambiente de desenvolvimento
- `producao` - Ambiente de produção

## 🔧 Gerenciamento de Servidores

### 🌐 Via Interface Web (Recomendado)
1. **Acesse:** http://localhost:5000
2. **Navegue:** Seção "Servidores"
3. **Gerencie:** Adicionar, editar, remover, testar

### 💻 Via Terminal (Avançado)
```bash
python manage.py list                    # Lista servidores ativos
python manage.py list --todos            # Lista todos (incluindo inativos)
python manage.py status                  # Status geral do sistema
```

### Adicionar Servidor
```bash
# Modo interativo
python manage.py add

# Modo direto
python manage.py add --nome "Servidor SP" --tipo idrac --ip "10.1.1.100" --usuario root --senha "senha123"

# Com teste de conectividade
python manage.py add --nome "Servidor RJ" --tipo ilo --ip "10.2.1.100" --usuario admin --senha "senha456" --testar
```

### Remover Servidor
```bash
# Modo interativo
python manage.py remove

# Modo direto
python manage.py remove servidor_sp

# Sem confirmação
python manage.py remove servidor_sp --force
```

### Editar Servidor
```bash
# Alterar IP
python manage.py edit servidor_sp --ip "10.1.1.101"

# Alterar credenciais
python manage.py edit servidor_sp --usuario admin --senha "nova_senha"

# Desativar servidor
python manage.py edit servidor_sp --ativo false
```

### Testar Conectividade
```bash
# Testar um servidor específico
python manage.py test servidor_sp

# Testar todos os servidores
python manage.py test-all

# Modo interativo
python manage.py test
```

## 💾 Backup e Restauração

### Exportar Configuração
```bash
# Exporta para arquivo com timestamp
python manage.py export

# Exporta para arquivo específico
python manage.py export backup_producao.json
```

### Importar Configuração
```bash
# Importa com confirmação
python manage.py import backup_producao.json

# Importa sem confirmação
python manage.py import backup_producao.json --force
```

### Sincronizar com Formato Legado
```bash
# Atualiza Conexoes.txt baseado no servidores.json
python manage.py sync
```

## 📋 Estrutura de Arquivos

```
📁 Automação/
├── 📄 servidores.json          # ⭐ Lista de servidores (novo formato)
├── 📄 environment.json         # ⭐ Credenciais dos sistemas
├── 📄 Conexoes.txt            # 📜 Formato legado (compatibilidade)
├── 📂 templates/              # 🔧 Templates de configuração
├── 🔧 configure.py            # 🧙‍♂️ Wizard de configuração
├── 🔧 manage.py               # 🛠️ CLI de gerenciamento
├── 🔧 gerenciar_servidores.py # 📊 Sistema de gerenciamento
└── 🔧 executar_tudo.py        # ▶️ Script principal
```

## 🎯 Fluxo de Trabalho Recomendado

### 1️⃣ Primeira Configuração
```bash
# Execute o wizard
python configure.py

# Valide a configuração
python validate_system.py

# Execute o sistema
python executar_tudo.py
```

### 2️⃣ Adicionando Novos Servidores
```bash
# Adicione o servidor
python manage.py add --nome "Novo Servidor" --tipo idrac --ip "10.3.1.100" --usuario root --senha "senha"

# Teste a conectividade
python manage.py test novo_servidor

# Execute o sistema
python executar_tudo.py
```

### 3️⃣ Manutenção Regular
```bash
# Teste todos os servidores
python manage.py test-all

# Faça backup da configuração
python manage.py export backup_$(date +%Y%m%d).json

# Execute o sistema
python executar_tudo.py
```

## 🔍 Solução de Problemas

### Problema: Servidor não responde
```bash
# Teste conectividade específica
python manage.py test nome_do_servidor

# Verifique se está ativo
python manage.py list --todos

# Reative se necessário
python manage.py edit nome_do_servidor --ativo true
```

### Problema: Credenciais inválidas
```bash
# Atualize as credenciais
python manage.py edit nome_do_servidor --usuario novo_usuario --senha nova_senha

# Teste novamente
python manage.py test nome_do_servidor
```

### Problema: Migração do formato antigo
```bash
# O sistema migra automaticamente, mas se necessário:
python -c "from gerenciar_servidores import GerenciadorServidores; GerenciadorServidores()"
```

## 📊 Exemplos de Configuração

### Empresa Pequena (1-3 servidores)
```json
{
  "servidores": [
    {
      "nome": "Servidor Principal",
      "tipo": "idrac",
      "ip": "192.168.1.100",
      "usuario": "root",
      "senha": "senha_segura"
    }
  ]
}
```

### Empresa Média (4-10 servidores)
```json
{
  "servidores": [
    {
      "nome": "Matriz SP",
      "tipo": "idrac",
      "ip": "10.1.1.100",
      "grupo": "matriz"
    },
    {
      "nome": "Regional RJ",
      "tipo": "ilo",
      "ip": "10.2.1.100",
      "grupo": "regionais"
    }
  ]
}
```

## 🎨 Personalização

### Criar Template Personalizado
```bash
# Baseado na configuração atual
python -c "from templates_configuracao import TemplatesConfiguracao; TemplatesConfiguracao().criar_template_personalizado('minha_empresa', 'Template da minha empresa')"
```

### Configurações Avançadas
Edite diretamente os arquivos:
- `environment.json` - Credenciais e timeouts
- `servidores.json` - Lista detalhada de servidores

## 🆘 Ajuda e Suporte

### Comandos de Ajuda
```bash
python manage.py --help              # Ajuda geral
python manage.py add --help          # Ajuda para adicionar servidor
python configure.py --help           # Ajuda do wizard
```

### Validação do Sistema
```bash
python validate_system.py            # Verifica integridade completa
```

### Logs e Debug
```bash
# Execute com debug (se disponível)
python executar_tudo.py --debug

# Verifique logs
ls -la logs/
```

---

## 🎉 Sistema Configurado!

Após a configuração inicial:
1. ✅ Execute `python executar_tudo.py`
2. 🌐 Acesse `output/dashboard_final.html`
3. 📊 Visualize todos os dados consolidados

**O sistema agora é muito mais fácil de configurar e gerenciar!** 🚀