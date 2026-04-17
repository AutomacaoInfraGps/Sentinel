"""
Script para limpar duplicações na estrutura de regionais
"""

import json
from gerenciar_regionais import GerenciadorRegionais

def limpar_estrutura():
    """Remove duplicações e organiza a estrutura"""
    
    gerenciador = GerenciadorRegionais()
    
    # Estrutura limpa
    estrutura_limpa = {
        "regionais": {
            "RG_GLOBAL_SEGURANCA": {
                "nome": "RG_GLOBAL SEGURANÇA",
                "descricao": "Regional Global de Segurança",
                "servidores": [
                    {
                        "id": "srv_seg_01",
                        "nome": "Servidor Segurança 01",
                        "tipo": "idrac",
                        "ip": "10.161.0.10",
                        "usuario": "root",
                        "senha": "ALTERE_AQUI",
                        "porta": 443,
                        "timeout": 10,
                        "ativo": True,
                        "modelo": "Dell PowerEdge",
                        "funcao": "Firewall/Segurança"
                    }
                ]
            },
            "RG_REGIONAL_BH": {
                "nome": "RG_REGIONAL BELO HORIZONTE", 
                "descricao": "Regional de Belo Horizonte",
                "servidores": [
                    {
                        "id": "srv_bh_01",
                        "nome": "Servidor BH 01",
                        "tipo": "idrac",
                        "ip": "10.31.0.12",
                        "usuario": "root",
                        "senha": "ALTERE_AQUI",
                        "porta": 443,
                        "timeout": 10,
                        "ativo": True,
                        "modelo": "Dell PowerEdge",
                        "funcao": "Aplicação"
                    }
                ]
            },
            "RG_MOTUS": {
                "nome": "RG_MOTUS",
                "descricao": "Regional MOTUS",
                "servidores": [
                    {
                        "id": "srv_motus_01",
                        "nome": "Servidor MOTUS 01",
                        "tipo": "idrac",
                        "ip": "10.111.0.11",
                        "usuario": "root",
                        "senha": "ALTERE_AQUI",
                        "porta": 443,
                        "timeout": 10,
                        "ativo": True,
                        "modelo": "Dell PowerEdge",
                        "funcao": "Aplicação"
                    }
                ]
            },
            "RG_GALAXIA": {
                "nome": "RG_GALAXIA",
                "descricao": "Regional GALAXIA - Matriz",
                "servidores": [
                    {
                        "id": "srv_galaxia_01",
                        "nome": "Servidor GALAXIA 01",
                        "tipo": "ilo",
                        "ip": "10.254.12.18",
                        "usuario": "administrator",
                        "senha": "ALTERE_AQUI",
                        "porta": 443,
                        "timeout": 10,
                        "ativo": True,
                        "modelo": "HPE ProLiant",
                        "funcao": "Infraestrutura"
                    }
                ]
            }
        },
        "configuracao": {
            "versao": "2.0",
            "estrutura": "hierarquica",
            "ultima_atualizacao": "2025-01-23T15:00:00",
            "backup_automatico": True,
            "validacao_automatica": True,
            "observacoes": "Estrutura hierárquica: Regional > Servidores (iDRAC/ILO)"
        }
    }
    
    # Salva a estrutura limpa
    with open("estrutura_regionais.json", 'w', encoding='utf-8') as f:
        json.dump(estrutura_limpa, f, indent=2, ensure_ascii=False)
    
    print("✅ Estrutura limpa e organizada!")
    
    # Gera relatório da estrutura limpa
    gerenciador_limpo = GerenciadorRegionais()
    print("\n" + gerenciador_limpo.gerar_relatorio())

if __name__ == "__main__":
    limpar_estrutura()