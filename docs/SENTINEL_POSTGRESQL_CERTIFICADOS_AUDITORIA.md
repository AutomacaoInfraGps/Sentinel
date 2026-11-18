# Auditoria da fonte de Validade de Certificados

## Escopo

Somente leitura de certificate_disk_report_acrab.json na raiz do projeto,
que e a fonte usada pela rota /validade-certificados. Sem SQL, WinRM,
execucao de PowerShell, consulta remota, DPAPI, edicao do coletor ou da tela.
Nao abre arquivos de certificados/chaves, nao exporta PEM/PFX, assuntos,
emissores, thumbprints, identidades, caminhos ou valores de campos extras.

```powershell
& 'C:\Automacao\.venv31410\Scripts\python.exe' `
    'C:\Automacao\scripts\database\audit_certificate_sources.py'
```

Enviar somente o JSON resumido. Nao publicar o arquivo de origem no chat/Git.

## Contrato observado no codigo

coleta_dados_acraby.py busca credenciais no cadastro/cofre, executa
Invoke-Command no servidor alvo do coletor e consulta Cert:\LocalMachine\My
com filtro de Subject contendo galaxia. Portanto a tela nao representa todos
os certificados do ambiente ou todos os repositorios/servidores. A auditoria
nao executa/importa esse coletor nem verifica remotamente a cobertura.

A saida normalizada tem somente thumbprint, subject, issuer e notAfter.
O coletor nao grava host, repositorio, horario da coleta ou recibo de sucesso
no JSON. O nome do arquivo nao prova sozinho a identidade atual do host;
nao associar automaticamente a uma regional por assunto do certificado.
mtime e horario da auditoria nao substituem evidencia de coleta.

A pagina aceita objeto unico ou lista e os aliases TitleCase dos quatro
campos, preferindo o valor minusculo quando verdadeiro. A auditoria segue
essa prioridade, mas contabiliza aliases conflitantes, linhas nao objeto e
campos nao textuais. Chaves JSON duplicadas ou JSON invalido sao rejeitados.
Leitura com BOM e diagnosticada: a auditoria aceita utf-8-sig, enquanto o
leitor web usa utf-8 e pode rejeitar BOM. Isso nao altera a fonte ou a tela.

## Identidade e datas

Thumbprints sao classificados apenas por formato hexadecimal 40 ou 64,
ignorando espacos e caixa para diagnostico. Isso nao e validacao criptografica.
Mesmo assunto pode representar renovacoes distintas; nao fundir por assunto,
nome ou emissor. Duplicidades e metadados divergentes para o mesmo thumbprint
sao diagnosticados, nunca corrigidos. Mesmo thumbprint em hosts/repositorios
diferentes nao identifica uma unica instalacao global.

Vencimentos ISO com fuso sao comparados em UTC com auditado_em_utc. Usa a
fronteira da pagina: expirado antes de agora; a vencer em menos de 30 dias;
valido temporalmente com 30 dias ou mais. No instante do vencimento ainda
entra em a vencer, como o codigo atual da tela. Nao comprova cadeia de
confianca, revogacao, chave privada, uso real ou correspondencia com endpoint.

Datas sem fuso, ausentes, invalidas ou legadas /Date(...)/ nao recebem
conversao inventada. A tela compara vencimento sem fuso com datetime.utcnow
sem conversao. Esse comportamento nao comprova que a origem quis dizer UTC:
confirmar a semantica do coletor antes de importar datas sem fuso. Nao usar
automaticamente o fuso do Rigel para datas de outro servidor.

O coletor trata /Date(milliseconds)/, mas representacoes com offset embutido
podem permanecer texto se a conversao falhar. A auditoria deve revelar essa
lacuna em vez de descartar datas ou interpretar texto localizado por palpite.

## Seguranca e proxima etapa

Campos potencialmente sensiveis conhecidos sao contados por presenca da
chave, nao exibidos. HasPrivateKey e um indicador de metadado separado, nao
uma chave privada. Essa contagem nao e um detector completo de segredos:
apenas uma projecao explicitamente permitida podera entrar em uma carga.

O hash vincula os bytes lidos; segunda leitura confirma estabilidade. Como
o coletor atual escreve diretamente no arquivo, uma escrita concorrente pode
causar fonte invalida/alterada: nao substituir banco por lista vazia em falha.
Fonte vazia legitima permanece distinta de arquivo ausente/ilegivel.

Antes de esquema SQL: revisar auditoria do Rigel, decidir identidade da fonte,
host/repositorio e tratamento de datas desconhecidas. Depois backup, copias
restritas, simulacao tipada com digest, migracao e conferencia. Nenhuma
migracao de certificados ou sincronizacao automatica esta preparada nesta etapa.
