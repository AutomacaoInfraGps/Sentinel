# 🔄 Atualização dos Dashboards - Estrutura Hierárquica

## 🎯 Resumo da Atualização

Os dashboards foram completamente reestruturados para refletir a hierarquia correta:
**Regional → Servidores (iDRAC/ILO)**

### ❌ Estrutura Antiga (Incorreta)
- Nomes como "RG_GLOBAL SEGURANÇA" eram tratados como servidores únicos
- Estrutura plana sem organização hierárquica
- Dashboards simples sem agrupamento

### ✅ Nova Estrutura (Correta)
- **Regionais**: Unidades organizacionais (ex: "RG_GLOBAL SEGURANÇA")
- **Servidores**: Múltiplos servidores físicos por regional
- **Dashboards hierárquicos**: Organizados por regional com drill-down

## 📁 Novos Arquivos

### Principais
- `dashboard_hierarquico.py` - Dashboard principal com estrutura hierárquica
- `executar_tudo_v2.py` - Executor completo integrado
- `atualizar_dashboards.py` - Script de migração e atualização

### Estrutura
- `estrutura_regionais.json` - Dados hierárquicos das regionais
- `gerenciar_regionais.py` - Gerenciador da estrutura
- `verificar_servidores_v2.py` - Verificador hierárquico

### Outputs
- `output/dashboard_hierarquico.html` - Dashboard principal
- `output/dashboard_[regional].html` - Dashboards por regional
- `output/dashboard_final_integrado.html` - Dashboard integrado completo

## 🚀 Como Usar

### 1. Dashboard Hierárquico
```bash
python dashboard_hierarquico.py
```

**Funcionalidades:**
- ✅ Visão geral de todas as regionais
- ✅ Drill-down por regional
- ✅ Status em tempo real dos servidores
- ✅ Dashboards individuais por regional
- ✅ Auto-refresh automático

### 2. Executor Completo V2
```bash
python executar_tudo_v2.py
```

**Funcionalidades:**
- ✅ Verificação completa de todas as regionais
- ✅ Integração com scripts legados
- ✅ Dashboard final integrado
- ✅ Relatórios detalhados

### 3. Atualização/Migração
```bash
python atualizar_dashboards.py
```

**Funcionalidades:**
- ✅ Backup dos dashboards antigos
- ✅ Migração automática
- ✅ Testes do novo sistema
- ✅ Demonstração da estrutura

## 🏗️ Estrutura dos Dashboards

### Dashboard Principal
```
📊 Dashboard Hierárquico
├── 📈 Estatísticas Gerais
│   ├── Total de Regionais
│   ├── Total de Servidores
│   ├── Servidores Online
│   └── Servidores Offline
├── 🏢 Cards das Regionais
│   ├── RG_GLOBAL SEGURANÇA
│   ├── RG_REGIONAL BELO HORIZONTE
│   ├── RG_MOTUS
│   └── RG_GALAXIA
└── 🔄 Auto-refresh (5 min)
```

### Dashboard por Regional
```
🏢 Dashboard Regional
├── 📋 Informações da Regional
├── 🖥️ Lista Detalhada de Servidores
│   ├── Status (Online/Offline/Warning)
│   ├── Tempo de Resposta
│   ├── Tipo (iDRAC/ILO)
│   ├── Modelo do Servidor
│   └── Função
└── 🔗 Link para Dashboard Principal
```

### Dashboard Integrado
```
🎯 Dashboard Final Integrado
├── 📊 Visão Geral do Sistema
├── 🏢 Dashboard Hierárquico
├── 📈 Relatórios Complementares
│   ├── GPS Status
│   ├── Replicação
│   └── UniFi
└── 📍 Resumo das Regionais
```

## 🎨 Características Visuais

### Design Moderno
- ✅ **Gradientes**: Fundo com gradiente azul/roxo
- ✅ **Glass Effect**: Cards com efeito de vidro (backdrop-filter)
- ✅ **Responsivo**: Adaptável a diferentes tamanhos de tela
- ✅ **Animações**: Transições suaves e hover effects
- ✅ **Ícones**: Emojis para identificação visual

### Cores por Status
- 🟢 **Verde**: Servidores online
- 🔴 **Vermelho**: Servidores offline  
- 🟡 **Amarelo**: Servidores com warning
- 🔵 **Azul**: Informações gerais

### Tipografia
- **Fonte**: Segoe UI (padrão Windows)
- **Hierarquia**: Tamanhos variados para importância
- **Legibilidade**: Alto contraste e espaçamento adequado

## 📊 Dados Exibidos

### Por Regional
- Nome e descrição da regional
- Quantidade de servidores
- Status geral (online/offline)
- Lista detalhada dos servidores

### Por Servidor
- Nome e IP do servidor
- Tipo (iDRAC/ILO) com ícone
- Modelo do hardware
- Função/propósito
- Status de conectividade
- Tempo de resposta
- Mensagens de erro (se houver)

### Estatísticas Gerais
- Total de regionais cadastradas
- Total de servidores monitorados
- Quantidade online/offline/warning
- Percentuais de disponibilidade

## 🔧 Configuração

### Estrutura JSON
```json
{
  "regionais": {
    "RG_CODIGO": {
      "nome": "Nome da Regional",
      "descricao": "Descrição",
      "servidores": [
        {
          "id": "srv_01",
          "nome": "Servidor 01",
          "tipo": "idrac|ilo",
          "ip": "10.x.x.x",
          "usuario": "usuario",
          "senha": "senha",
          "modelo": "Dell PowerEdge|HPE ProLiant",
          "funcao": "Aplicação|Infraestrutura"
        }
      ]
    }
  }
}
```

### Verificação de Status
- **Timeout**: 10 segundos por servidor
- **Paralelo**: Até 5 servidores simultâneos
- **Protocolo**: HTTPS (porta 443)
- **Validação**: Status codes 200, 401, 403 = Online

## 🔄 Auto-Refresh

### Dashboard Principal
- **Intervalo**: 5 minutos
- **Método**: JavaScript `location.reload()`
- **Indicador**: Timestamp na página

### Dashboard Integrado
- **Intervalo**: 10 minutos
- **Dados**: Recoleta automaticamente
- **Persistência**: Salva em JSON para referência

## 📱 Responsividade

### Desktop (>1200px)
- Grid de 3-4 colunas para regionais
- Estatísticas em linha horizontal
- Sidebar com navegação

### Tablet (768px-1200px)
- Grid de 2 colunas
- Estatísticas em 2x2
- Menu adaptado

### Mobile (<768px)
- Coluna única
- Estatísticas empilhadas
- Menu hamburger

## 🔍 Monitoramento

### Logs
- Tentativas de conexão
- Tempos de resposta
- Erros de conectividade
- Mudanças de status

### Alertas
- Servidores que ficam offline
- Timeouts frequentes
- Mudanças na estrutura

### Relatórios
- Histórico de disponibilidade
- Tendências de performance
- Análise por regional

## 🚀 Próximos Passos

### Melhorias Planejadas
1. **Notificações**: Alertas em tempo real
2. **Histórico**: Gráficos de disponibilidade
3. **API**: Endpoints REST para integração
4. **Mobile App**: Aplicativo dedicado
5. **Automação**: Ações automáticas baseadas em status

### Integrações
1. **SNMP**: Monitoramento avançado
2. **Zabbix**: Integração com sistema de monitoramento
3. **Slack/Teams**: Notificações em chat
4. **Email**: Relatórios automáticos
5. **Grafana**: Dashboards avançados

## ✅ Checklist de Migração

- [x] Estrutura hierárquica implementada
- [x] Dashboard principal criado
- [x] Dashboards por regional
- [x] Dashboard integrado
- [x] Sistema de verificação atualizado
- [x] Scripts de migração
- [x] Documentação completa
- [x] Testes realizados
- [x] Backup dos arquivos antigos
- [x] Compatibilidade mantida

## 📞 Suporte

Para dúvidas ou problemas:
1. Verifique os logs em `output/`
2. Execute `python atualizar_dashboards.py` para diagnóstico
3. Consulte `README_ESTRUTURA_V2.md` para detalhes técnicos
4. Use `python dashboard_hierarquico.py` para teste direto

---

**🎯 Sistema atualizado com sucesso para estrutura hierárquica Regional → Servidores!**