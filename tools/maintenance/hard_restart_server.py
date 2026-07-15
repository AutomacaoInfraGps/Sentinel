#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import requests
import time
import subprocess
import psutil
import os
import signal

# Step 1: Kill all Python processes related to Flask
print("[1] Killing Flask processes...")
for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
    try:
        if 'python' in proc.name().lower():
            proc.terminate()
            time.sleep(0.5)
            if proc.is_running():
                proc.kill()
            print(f"    Killed PID {proc.pid}")
    except:
        pass

time.sleep(3)

# Step 2: Start new server
print("\n[2] Starting new Flask server...")
os.chdir('c:\\Automacao')
proc = subprocess.Popen(['python', 'iniciar_web.py'], 
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL)
print(f"    Server started with PID {proc.pid}")

# Step 3: Wait for server to start
time.sleep(5)

# Step 4: Verify
print("\n[3] Verifying server...")
try:
    response = requests.get('http://localhost:5000/firewalls', timeout=5)
    print(f"    Server responding with status {response.status_code}")
except Exception as e:
    print(f"    Error: {e}")

print("\nDone!")
