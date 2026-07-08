#!/usr/bin/env python3
import psutil
import subprocess
import time

# Kill all Python processes
killed = 0
for proc in psutil.process_iter(['pid', 'name']):
    try:
        if 'python' in proc.name().lower():
            proc.kill()
            killed += 1
    except:
        pass

print(f"Killed {killed} Python processes")
time.sleep(3)

# Start new server
print("Starting new server...")
subprocess.Popen(['python', 'executar_sistema.py'], cwd='c:\\Automacao')
print("Server started")
