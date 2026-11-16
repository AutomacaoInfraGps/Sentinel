# Consulta controlada de licencas

## Situacao

Em 16/11/2026, o operador confirmou a sincronizacao automatica: publicacao
`2026-11-16T11:05:13.651677+00:00`, 49 firewalls/licencas presentes e
`conteudo_ja_sincronizado=true`. A consulta SQL tecnica encontrou cinco licencas
entre zero e 50 dias e quatro sem vencimento conhecido. Sao observacoes dessa
coleta, nao constantes do sistema.

## Implementacao em homologacao

`services/operational_license_query.py` recebe uma conexao em transacao nova e
um escopo obrigatorio. O futuro chamador HTTP deve fornecer somente o escopo
derivado da sessao Sentinel ou do token regional validado pelo backend. A lista
de codigos nao autentica o usuario por si so. Nao expor este metodo diretamente
com allowed_regionals controlado pelo navegador ou pelo modelo.

- SQL parametrizado com ANY restringe as linhas ao escopo antes da leitura.
- Regional explicitamente fora do escopo falha antes do SQL.
- Escopo vazio nao consulta o banco; nenhuma permissao global implicita.
- Transacao REPEATABLE READ, READ ONLY para manter marcador e linhas consistentes.
- Confere banco sentinel/porta 5433; timeout de consulta 5s e lock 1s.
- Somente registros presentes de firewall e licenca, com colunas permitidas.
- Le todas as licencas desse escopo para projetar estado, filtrar e contar antes
  de paginar. Nao depende dos primeiros 20 registros. Esta etapa nao introduz
  historico nem uma consulta SQL generica; volumes maiores exigirao medir e
  eventualmente mover agregacoes/paginacao para SQL.
- Filtro de prazo inclusivo 0..N (ate N dias). Para "abaixo de 50", usar 49:
  os dias observados sao inteiros. Negativos nao entram nesse filtro.
- Preserva dias/flags observados do coletor; nao recalcula regras de alerta.
- Vencimento desconhecido ou estado indisponivel mascara dias, nunca vira zero.
- Expiracao instantanea e data civil continuam campos separados.
- Dados anteriores, horario de coleta ausente e firewalls sem detalhes de
  licenca geram lacunas no escopo, mesmo se o filtro de prazo excluir essas linhas.
- Fresh exige publicacao de no maximo 300s, nao futura e sem lacunas; nao muda
  frequencias existentes. A data individual e previous_data tambem sao retornadas.
- Falha da fonte ou marcador ausente gera erro, nao sucesso com contagem zero.

Nao ha troca da leitura das telas/SofIA nem nova rota HTTP nesta entrega.
Antes da integracao: provisionar referencia DPAPI de sentinel_api e usar essa
conta SELECT-only no backend, sem reutilizar o coletor para consultas do agente.
Homologar tambem os escopos AD reais; testes do adaptador nao provam essa cadeia.

## Conferencia tecnica no Rigel

O CLI `scripts/database/check_license_query.py` e exclusivo do operador. Usa a
credencial existente do coletor em transacao somente leitura para homologacao,
nao concede permissoes nem representa uma sessao AD de usuario final. Nao tem
--apply, escopo global implicito ou credenciais por argumento.

Depois de revisar, commitar e implantar via Git:

```powershell
& 'C:\Automacao\.venv31410\Scripts\python.exe' `
    C:\Automacao\scripts\database\check_license_query.py `
    --regional REG_TLSV_POA --within-days 50
```

Para comparar duas regionais e a paginacao, repetir --regional e usar --limit 1
com --offset 0 e depois --offset 1. O summary.records deve ser identico entre
paginas; records deve conter somente as regionais explicitadas.

Nao repetir importacao/migracao, reiniciar servicos ou alterar permissoes SQL.
Os testes locais usam conexoes simuladas. Validacao real deste adaptador no
PostgreSQL do Rigel continua pendente ate o operador executar o CLI.
