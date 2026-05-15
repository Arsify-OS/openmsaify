#!/usr/bin/env python3
import os
import sys

# Check the token value from environment
token = os.environ.get('TELEGRAM_BOT_TOKEN', 'NOT SET')
print(f"Token from env: {token[:20]}..." if len(token) > 20 else f"Token: {token}")

# Try reading .env file directly 
env_path = '/root/.hermes/.env'
if os.path.exists(env_path):
    with open(env_path, 'r') as f:
        for line in f:
            if line.startswith('TELEGRAM_BOT_TOKEN='):
                stored = line.strip().split('=', 1)[1]
                print(f"Token from {env_path}: {stored[:20]}..." if len(stored) > 20 else f"Token: {stored}")
                break

# Try with gateway Python
print("\nTrying gateway Python directly:")
import subprocess
result = subprocess.run(
    ['/usr/local/lib/hermes-agent/venv/bin/python', '-c',
     "import os; print(os.environ.get('TELEGRAM_BOT_TOKEN', 'NOT SET'))"],
    capture_output=True, text=True
)
print("Gateway venv token:", result.stdout.strip())
