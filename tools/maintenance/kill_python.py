#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import psutil
import time

# Procura todos os processos python
for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
    try:
        if 'python' in proc.name().lower():
            print(f"PID: {proc.pid}, CMD: {' '.join(proc.cmdline()[:3])}")
            # Tenta terminar
            try:
                proc.kill()
                print(f"  ✓ Terminado")
            except Exception as e:
                print(f"  ✗ Erro: {e}")
    except:
        pass

time.sleep(2)
print("\nProcessos após kill:")
for proc in psutil.process_iter(['pid', 'name']):
    try:
        if 'python' in proc.name().lower():
            print(f"  PID: {proc.pid}")
    except:
        pass
