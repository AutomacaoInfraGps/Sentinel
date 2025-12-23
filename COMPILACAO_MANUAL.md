# 🔧 GUIA DE COMPILAÇÃO MANUAL PARA .EXE

## 🚨 **PROBLEMA IDENTIFICADO**
Há restrições de rede que impedem a instalação automática do PyInstaller. Vou te dar alternativas para resolver isso.

## 🛠️ **SOLUÇÕES ALTERNATIVAS**

### **OPÇÃO 1: Instalação Manual do PyInstaller**

#### 1.1 Baixar PyInstaller Manualmente
1. Acesse: https://pypi.org/project/pyinstaller/#files
2. Baixe o arquivo: `pyinstaller-6.14.2-py3-none-win_amd64.whl`
3. Salve na pasta do projeto: `c:\Users\m.vbatista\Desktop\Automação\`

#### 1.2 Instalar do Arquivo Local
```bash
# Navegue até a pasta do projeto
cd "c:\Users\m.vbatista\Desktop\Automação"

# Instale do arquivo baixado
pip install pyinstaller-6.14.2-py3-none-win_amd64.whl
```

### **OPÇÃO 2: Usar Proxy Corporativo**

Se sua empresa usa proxy, configure:
```bash
# Configure o proxy (substitua pelos dados da sua empresa)
pip install --proxy http://usuario:senha@proxy.empresa.com:8080 pyinstaller

# Ou usando variáveis de ambiente
set HTTP_PROXY=http://proxy.empresa.com:8080
set HTTPS_PROXY=http://proxy.empresa.com:8080
pip install pyinstaller
```

### **OPÇÃO 3: Usar Conda (se disponível)**
```bash
# Se você tem Anaconda/Miniconda instalado
conda install pyinstaller
```

### **OPÇÃO 4: Compilação Básica sem PyInstaller**

Se não conseguir instalar o PyInstaller, você pode usar o **auto-py-to-exe** que tem interface gráfica:

#### 4.1 Instalar auto-py-to-exe
```bash
pip install auto-py-to-exe
```

#### 4.2 Executar interface gráfica
```bash
auto-py-to-exe
```

## 🚀 **APÓS INSTALAR O PYINSTALLER**

### **Passo 1: Execute o Script Automático**
```bash
python compile_to_exe.py
```

### **Passo 2: OU Compilação Manual**
```bash
# Comando básico
pyinstaller --onefile executar_tudo.py

# Comando completo (recomendado)
pyinstaller ^
    --onefile ^
    --name "SistemaAutomacaoInfraestrutura" ^
    --add-data "*.ps1;." ^
    --add-data "*.json;." ^
    --add-data "templates;templates" ^
    --add-data "output;output" ^
    --add-data "data;data" ^
    --hidden-import requests ^
    --hidden-import urllib3 ^
    --hidden-import config ^
    --hidden-import credentials ^
    --hidden-import data_store ^
    --hidden-import vm_manager ^
    --console ^
    executar_tudo.py
```

## 📋 **CHECKLIST DE COMPILAÇÃO**

Antes de compilar, verifique:

- [ ] ✅ PyInstaller instalado
- [ ] ✅ Todas as dependências OK (execute: `python verificar_dependencias.py`)
- [ ] ✅ Arquivo `executar_tudo.py` existe
- [ ] ✅ Pasta `templates` existe
- [ ] ✅ Scripts `.ps1` existem
- [ ] ✅ Arquivos `.json` de configuração existem

## 🎯 **COMANDOS PRONTOS PARA USAR**

### **Compilação Simples (Teste)**
```bash
pyinstaller --onefile executar_tudo.py
```

### **Compilação Completa (Produção)**
```bash
pyinstaller --onefile --name "SistemaAutomacao" --add-data "*.ps1;." --add-data "*.json;." --add-data "templates;templates" --add-data "output;output" --add-data "data;data" --hidden-import requests --hidden-import urllib3 --hidden-import config --console executar_tudo.py
```

### **Compilação com Arquivo .spec (Avançado)**
```bash
# 1. Gerar arquivo .spec
pyi-makespec --onefile executar_tudo.py

# 2. Editar o arquivo executar_tudo.spec (adicionar datas e hiddenimports)

# 3. Compilar usando .spec
pyinstaller executar_tudo.spec
```

## 📁 **ESTRUTURA APÓS COMPILAÇÃO**

```
c:\Users\m.vbatista\Desktop\Automação\
├── dist\
│   └── SistemaAutomacaoInfraestrutura.exe  ← EXECUTÁVEL FINAL
├── build\                                   ← Arquivos temporários
├── executar_tudo.spec                      ← Configuração (se usado)
└── ... (outros arquivos do projeto)
```

## 🧪 **TESTE DO EXECUTÁVEL**

Após a compilação:

1. **Navegue até a pasta dist:**
   ```bash
   cd dist
   ```

2. **Execute o .exe:**
   ```bash
   SistemaAutomacaoInfraestrutura.exe
   ```

3. **Verifique se:**
   - [ ] O programa inicia sem erros
   - [ ] Consegue acessar os scripts PowerShell
   - [ ] Gera os relatórios corretamente
   - [ ] Salva na pasta "Relatório Preventiva"

## ⚠️ **PROBLEMAS COMUNS**

### **Erro: "Módulo não encontrado"**
```bash
# Adicione o módulo específico
pyinstaller --hidden-import nome_do_modulo executar_tudo.py
```

### **Erro: "Arquivo .ps1 não encontrado"**
```bash
# Verifique se os scripts estão sendo incluídos
pyinstaller --add-data "*.ps1;." executar_tudo.py
```

### **Executável muito grande**
```bash
# Exclua módulos desnecessários
pyinstaller --exclude-module matplotlib --exclude-module pandas executar_tudo.py
```

### **Antivírus bloqueia o executável**
- Adicione exceção no Windows Defender
- Use certificado digital (para distribuição corporativa)

## 🎨 **MELHORIAS OPCIONAIS**

### **Adicionar Ícone**
1. Baixe um ícone .ico
2. Use: `pyinstaller --icon=icone.ico executar_tudo.py`

### **Ocultar Console**
```bash
# Para versão final sem console
pyinstaller --windowed executar_tudo.py
```

### **Compressão**
```bash
# Reduz tamanho do executável
pyinstaller --upx-dir=C:\upx executar_tudo.py
```

## 📞 **SUPORTE**

Se ainda tiver problemas:

1. **Verifique dependências:**
   ```bash
   python verificar_dependencias.py
   ```

2. **Teste compilação simples:**
   ```bash
   pyinstaller --onefile --console executar_tudo.py
   ```

3. **Use modo debug:**
   ```bash
   pyinstaller --debug=all executar_tudo.py
   ```

---

## 🎯 **RESUMO DOS PRÓXIMOS PASSOS**

1. **Instale o PyInstaller** (usando uma das opções acima)
2. **Execute:** `python compile_to_exe.py` (automático)
3. **OU execute:** comando manual de compilação
4. **Teste** o executável gerado
5. **Distribua** para os usuários

**Seu projeto está pronto para ser compilado! 🚀**