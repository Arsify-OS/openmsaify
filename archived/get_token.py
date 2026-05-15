#!/usr/bin/env python3
with open('/root/.hermes/.env', 'r') as f:
    for line in f:
        line = line.strip()
        if line.startswith('TELEGRAM_BOT_TOKEN=') and not line.startswith('#'):
            token = line.split('=', 1)[1]
            print(f"Token: {token}")
            print(f"Token length: {len(token)}")
            # Print each character's code point to see if there are special chars
            print("Character codes:", [ord(c) for c in token])
            break
