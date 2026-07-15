import os
import getpass

print("Usuário:", getpass.getuser())
print("CWD:", os.getcwd())

path = r"C:\Automacao\output\teste_permissao.txt"

try:
    with open(path, "w", encoding="utf-8") as f:
        f.write("teste ok")
    print("✅ Escrita OK")
except Exception as e:
    print("❌ ERRO:", e)
