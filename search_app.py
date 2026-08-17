import re
with open('G:\\xumo\\app.py', 'r', encoding='utf-8') as f:
    content = f.read()
    lines = content.split('\n')
    for i, line in enumerate(lines, 1):
        if any(kw in line for kw in ['on_event', 'lifespan', 'startup', 'shutdown']):
            print(f'{i}: {line}')