#!/usr/bin/env python3
import sys
sys.path.insert(0, r'G:\xumo')

with open(r'G:\xumo\app.py', 'r', encoding='utf-8') as f:
    for i, line in enumerate(f, 1):
        stripped = line.strip()
        if '@app' in stripped or 'on_event' in stripped or 'lifespan' in stripped.lower() or 'startup' in stripped.lower() or 'shutdown' in stripped.lower():
            print(f'{i}: {line.rstrip()}')