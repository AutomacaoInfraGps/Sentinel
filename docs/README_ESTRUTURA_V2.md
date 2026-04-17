# Sistema de Monitoramento - Estrutura Hierárquica V2.0

## 🏗️ Nova Estrutura

### Conceito Corrigido
- **Regional**: Nome da unidade organizacional (ex: "RG_GLOBAL SEGURANÇA")
- **Servidores**: Múltiplos servidores físicos com iDRAC/ILO por regional

### Hierarquia
```
Regional (RG_GLOBAL SEGURANÇA)
├── Servidor 01 (iDRAC - 10.161.0.10)
├── Servidor 02 (iDRAC - 10.161.0.11)
└── Servidor 03 (ILO - 10.161.0.12)
```

## 📁 Arquivos da Nova Estrutura

### Principais
- `estrutura_regionais.json` - Estrutura hierárquica de regionais e servidores
- `gerenciar_regionais.py` - Gerenciador da estrutura hierárquica
- `verificar_servidores_v2.py` - Verificador com nova estrutura

### Utilitários
- `limpar_estrutura.py` - Remove duplicações e organiza
- `README_ESTRUTURA_V2.md` - Esta documentação

## 🏢 Regionais Configuradas

### RG_GLOBAL SEGURANÇA
- **Descrição**: Regional Global de Segurança
- **Servidores**: 1 (Dell PowerEdge iDRAC)
- **IP**: 10.161.0.10

### RG_REGIONAL BELO HORIZONTE  
- **Descrição**: Regional de Belo Horizonte
- **Servidores**: 1 (Dell PowerEdge iDRAC)
- **IP**: 10.31.0.12

### RG_MOTUS
- **Descrição**: Regional MOTUS
- **Servidores**: 1 (Dell PowerEdge iDRAC)
- **IP**: 10.111.0.11

### RG_GALAXIA
- **Descrição**: Regional GALAXIA - Matriz
- **Servidores**: 1 (HPE ProLiant ILO)
- **IP**: 192.0.2.18

## 🚀 Como Usar

### Gerenciar Regionais
```bash
python gerenciar_regionais.py
```

**Funcionalidades:**
- Listar regionais
- Adicionar nova regional
- Adicionar servidor a regional
- Gerar relatórios
- Migrar estrutura antiga

### Verificar Servidores
```bash
python verificar_servidores_v2.py
```

**Funcionalidades:**
- Verificar todas as regionais
- Verificar regional específica
- Gerar relatório detalhado
- Gerar página HTML de status
- Salvar resultados em JSON

## 📊 Exemplo de Uso

### Adicionar Nova Regional
```python
from gerenciar_regionais import GerenciadorRegionais

gerenciador = GerenciadorRegionais()

# Adiciona regional
gerenciador.adicionar_regional(
    "RG_NOVA_REGIONAL",
    "RG_NOVA REGIONAL",
    "Descrição da nova regional"
)

# Adiciona servidor
servidor = {
    "id": "srv_nova_01",
    "nome": "Servidor Nova 01",
    "tipo": "idrac",
    "ip": "10.100.0.10",
    "usuario": "root",
    "senha": "senha123",
    "modelo": "Dell PowerEdge",
    "funcao": "Aplicação"
}

gerenciador.adicionar_servidor("RG_NOVA_REGIONAL", servidor)
```

### Verificar Status
```python
from verificar_servidores_v2 import VerificadorServidoresV2

verificador = VerificadorServidoresV2()

# Verifica todas as regionais
resultados = verificador.verificar_todas_regionais()

# Gera relatório
relatorio = verificador.gerar_relatorio_detalhado()
print(relatorio)

# Gera HTML
verificador.gerar_html_status("status.html")
```

## 🔧 Estrutura do JSON

```json
{
  "regionais": {
    "RG_CODIGO_REGIONAL": {
      "nome": "Nome da Regional",
      "descricao": "Descrição da regional",
      "servidores": [
        {
          "id": "srv_id_01",
          "nome": "Nome do Servidor",
          "tipo": "idrac|ilo",
          "ip": "10.x.x.x",
          "usuario": "usuario",
          "senha": "senha",
          "porta": 443,
          "timeout": 10,
          "ativo": true,
          "modelo": "Dell PowerEdge|HPE ProLiant",
          "funcao": "Aplicação|Infraestrutura"
        }
      ]
    }
  },
  "configuracao": {
    "versao": "2.0",
    "estrutura": "hierarquica",
    "ultima_atualizacao": "2025-01-23T15:00:00"
  }
}
```

## ✅ Vantagens da Nova Estrutura

1. **Hierárquica**: Organização clara Regional → Servidores
2. **Escalável**: Fácil adicionar novos servidores por regional
3. **Flexível**: Suporte a múltiplos tipos (iDRAC/ILO)
4. **Organizada**: Separação lógica por unidade de negócio
5. **Auditável**: Logs e relatórios detalhados

## 🔄 Migração

A migração da estrutura antiga é automática:
- Executa `gerenciar_regionais.py`
- Escolhe migrar quando solicitado
- Estrutura antiga é convertida automaticamente

## 📈 Próximos Passos

1. **Adicionar mais servidores** por regional conforme necessário
2. **Implementar alertas** para servidores offline
3. **Dashboard web** em tempo real
4. **Integração com sistemas** de monitoramento
5. **Backup automático** da configuração