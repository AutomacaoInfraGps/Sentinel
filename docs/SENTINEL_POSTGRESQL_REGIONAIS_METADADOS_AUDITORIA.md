# Auditoria de metadados das regionais

## Lacuna identificada no codigo

operational_server_postgres.py publica e grava codigo/nome/presenca da regional,
mas nao descricao, estado ou uf. O formulario regional_form.html oferece
Estado/UF e descricao (maxlength 500). O gerenciador grava estado e uf juntos,
mas na leitura usa setdefault: valores conflitantes ja existentes nao sao
necessariamente reconciliados. Nao assumir que os aliases sao equivalentes.

O codigo/nome da regional participa dos vinculos existentes. Esta etapa nao
renomeia regionais, altera aliases UniFi/SLA ou permissoes AD, nem modifica o
escritor de servidores. Nao forcar uma atualizacao para validar a etapa 022.

## Execucao no Rigel

```powershell
& 'C:\Automacao\.venv31410\Scripts\python.exe' `
    'C:\Automacao\scripts\database\audit_regional_metadata_sources.py'
```

--source permite apontar uma copia explicita do cadastro. Abre o JSON com
detector de chaves duplicadas e rele os bytes para detectar alteracao durante
a leitura. Fonte ausente/invalida nao e tratada como inventario vazio. O formato
esperado e um objeto regionais; registros invalidos sao contados separadamente.

Saida somente com contagens/categorias: cobertura de nome/descricao/estado/uf,
ausente/nulo/vazio/espacos/nao textual, limites da tela/projecao, codigos fora
do padrao SQL atual, duplicidades normalizadas, nomes repetidos e conflitos de
estado/uf. Nao exporta codigos, nomes, descricoes, enderecos, chaves arbitrarias,
valores de UF inesperados ou campos de acesso de dispositivos.

Siglas sao classificadas contra a lista fixa das 27 UFs. Uma sigla reconhecida
apos trim/uppercase e apenas candidata a normalizacao, nao alteracao aplicada.
Nome de estado por extenso ou texto inesperado exige revisao posterior.
Nao inferir UF por descricao, nome de regional, endereco ou equipamento.
Descricao pode conter informacao interna/endereco: nao pedir o JSON bruto.

Referencia SQL e leitura do codigo, nao conferencia do banco do Rigel. O hash
do arquivo cobre o cadastro inteiro; pode mudar por atualizacao de servidores
sem alteracao desses metadados. Publicacao e classificada pelo formato temporal,
nao convertida nem usada como evidencia de coleta de equipamento.

## Proxima etapa

Receber a auditoria do Rigel, revisar cobertura e conflitos, entao definir
projecao segura e esquema. Ainda nao ha migracao/carga desses campos.
Nenhum gerenciador/config de runtime, cofre, banco, API ou coletor e importado
pela auditoria. Arquivo e telas permanecem inalterados.
