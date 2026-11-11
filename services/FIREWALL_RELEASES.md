# Consulta de versões FortiOS

A tela Firewalls compara modelo e firmware do inventário com o catálogo que o FortiManager sincroniza com o FortiGuard. A consulta JSON-RPC é somente leitura e não baixa nem instala firmware.

O Sentinel consulta `/um/image/version/list` uma vez durante a coleta dos firewalls, considera apenas releases GA e armazena a avaliação no mesmo snapshot horário do inventário. Não há scraping de `docs.fortinet.com` nem catálogo separado em disco.

## Indicadores

- `!` vermelho: existe versão GA superior compatível dentro da mesma família principal, como `7.x`.
- `✔` verde: o modelo está na última versão GA conhecida da família instalada. Uma `8.x` isolada não alerta um equipamento `7.x`.
- `X` cinza: FortiManager, modelo, firmware ou compatibilidade não puderam ser confirmados.

A confirmação exige versões GA válidas para o modelo na família principal instalada. Catálogos vazios ou contendo somente outra família deixam a verificação indisponível. Se a atualização do inventário falhar, as avaliações recuperadas do snapshot ficam desatualizadas e exibem `X`, preservando a data da última consulta.

O balão aponta para as Release Notes diretas da versão encontrada. A disponibilidade não confirma recomendação operacional nem caminho direto de upgrade.

## Testes isolados

```powershell
.\venv\Scripts\python.exe -B -m unittest tests.unit.firewall_releases_test tests.unit.firewall_refresh_fallback_test -v
```

Os testes usam respostas fictícias do FortiManager e não acessam credenciais ou rede.
