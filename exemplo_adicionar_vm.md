# 🖥️ Gerenciamento de VMs - Guia de Uso

## Padrão de Regionais

As VMs devem seguir o mesmo padrão de nomenclatura dos servidores iDRAC/iLO:

- **RG_PARANA** (em vez de "Paraná")
- **RG_SAO_PAULO** (em vez de "São Paulo")
- **RG_BELO_HORIZONTE** (em vez de "Belo Horizonte")
- **RG_RIO_DE_JANEIRO** (em vez de "Rio de Janeiro")

## Comandos Disponíveis

### 1. Listar VMs
```bash
python manage_vms.py list
```

### 2. Adicionar Nova VM
```bash
python manage_vms.py add \
  --name "VM_SAO_PAULO" \
  --ip "192.0.2.50" \
  --username "usuario.exemplo" \
  --password "ALTERE_AQUI" \
  --regional "SAO_PAULO" \
  --description "VM Regional de São Paulo"
```

### 3. Remover VM
```bash
python manage_vms.py remove "VM_SAO_PAULO"
```

### 4. Atualizar Regional
```bash
python manage_vms.py update-regional "Parana" "RG_PARANA_NOVA"
```

### 5. Interface Interativa
```bash
python manage_vms.py cli
```

## Estrutura do Arquivo VMs

```json
[
    {
        "id": "vm-1753466017",
        "name": "Parana",
      "ip": "192.0.2.40",
      "username": "usuario.exemplo",
      "password": "ALTERE_AQUI",
        "regional": "RG_PARANA",
        "description": "Máquina Virtual Regional do Paraná",
        "status": "Unknown",
        "last_check": null,
        "grupo": "regionais",
        "tipo": "vm"
    }
]
```

## Regionais Padrão dos Servidores

Para manter consistência, use as mesmas regionais dos servidores iDRAC/iLO:

- **RG_GLOBAL_SEGURANCA**
- **RG_REGIONAL_BELO_HORIZONTE** 
- **RG_MOTUS**
- **RG_GALAXIA**
- **RG_PARANA**

## Resultado no Dashboard

Com essa configuração, as VMs aparecerão no dashboard com a regional correta:

```
📱 VM: Parana (192.0.2.40)
   Regional: RG_PARANA
   Status: Online
```

Isso mantém a consistência visual com os servidores iDRAC/iLO que também usam o padrão "RG_*".