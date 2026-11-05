# Consulta pública de versões FortiOS

A tela Firewalls compara modelo e firmware do inventário existente com as Release Notes públicas da Fortinet. Não instala firmware nem consulta FortiCloud.

O endereço inicial é `https://docs.fortinet.com/product/fortigate/`. O coletor segue os redirecionamentos e descobre as linhas publicadas, sem fixar uma versão principal. Somente endereços HTTPS de `docs.fortinet.com` são aceitos. Nenhum dado do inventário corporativo é enviado ao fornecedor.

O primeiro acesso à tela inicia a consulta em uma thread e mostra verificação indisponível enquanto não houver catálogo. Recarregue a página após a coleta. Novas consultas são iniciadas no acesso à tela quando o cache tem mais de 24 horas; não existe agendamento independente do uso da página. Após uma falha, a próxima tentativa ocorre depois de pelo menos 15 minutos. As requisições têm timeout e até duas repetições para falhas transitórias.

O catálogo fica em `instance/fortios_releases/catalog.json`, já abrangido pela regra de exclusão de `instance/`. Um lock de arquivo impede duas coletas simultâneas entre processos. A gravação substitui o cache somente ao concluir a coleta; falhas de rede preservam o anterior.

## Indicadores

- Atualização disponível: modelo exato consta na lista suportada de uma versão superior da mesma família principal (por exemplo, `7.x`). Prioriza patch da linha atual e informa outra linha compatível da família quando encontrada; uma `8.x` isolada não alerta um equipamento `7.x`.
- Linha ausente do catálogo: a linha não consta no índice público consultado. Não representa declaração de fim de suporte.
- Sem versão superior no catálogo: não foi encontrada versão superior compatível e não há lacuna de leitura em linhas iguais ou superiores.
- Verificação indisponível: catálogo, modelo, versão ou compatibilidade não puderam ser confirmados.

As mensagens apresentam a data da consulta e sinalizam cache desatualizado. O badge abre a documentação oficial e oferece descrição ao passar o mouse ou receber foco pelo teclado. A disponibilidade não confirma recomendação operacional ou caminho direto de upgrade.

## Limites conhecidos

O coletor extrai modelos das tabelas HTML. Releases antigas disponibilizadas somente como PDF ficam com cobertura parcial; não são interpretadas como linha ausente nem permitem declarar atualização completa. Mudanças na estrutura do site podem exigir ajuste no parser. A consulta inicial percorre releases de diversas linhas e pode levar alguns minutos.

## Testes isolados

```powershell
.\venv\Scripts\python.exe -B -m unittest tests.unit.firewall_releases_test -v
```

Os testes usam dados fictícios e não inicializam o Sentinel nem abrem configurações de credenciais.
