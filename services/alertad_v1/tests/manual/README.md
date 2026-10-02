# Validação manual de XMLs privados

Esta pasta contém somente o validador versionável. Amostras corporativas devem
permanecer exclusivamente em `../fixtures/XMLEXAMPLE_test/`, que é ignorada pelo
Git na raiz do Sentinel e também pelo `.gitignore` do AlertAD.

O validador não imprime campos do evento nem mensagens de exceção que possam
conter dados internos. Ele informa somente nome do arquivo, resultado e código
de erro sanitizado.

A partir da raiz do Sentinel:

```powershell
.\venv\Scripts\python.exe `
  .\services\alertad_v1\tests\manual\validate_private_xml_samples.py `
  .\services\alertad_v1\tests\fixtures\XMLEXAMPLE_test
```

A importação opcional exige um banco já existente e permanentemente marcado
como `dry_run`:

```powershell
.\venv\Scripts\python.exe `
  .\services\alertad_v1\tests\manual\validate_private_xml_samples.py `
  .\services\alertad_v1\tests\fixtures\XMLEXAMPLE_test `
  --import-dry-run C:\CAMINHO_LOCAL_PROTEGIDO\alertad-hml.db
```

Nunca copie XML privado, banco SQLite, `.env`, cache de autenticação, logs ou
configuração preenchida para esta pasta versionável.
