#!/usr/bin/env python3
import os, sys

# Add path and import but intercept reading
sys.path.insert(0, '/root/openmsaify/msai/dashboards')

# Before import, check if there's a config loading
print("=== Checking for config files ===")
config_paths = [
    '/root/.hermes/config.yaml',
    '/root/.hermes/gateway.json',
    '/root/.hermes/.env',
    '/root/openmsaify/config/.env.local',
]

for p in config_paths:
    exists = os.path.exists(p)
    print(f"{p}: {'EXISTS' if exists else 'not found'}")

# Now import the module
import telegram_notify

# Check if telegram_notify reads from a specific source
print(f"\ntelegram_notify.TELEGRAM_BOT_TOKEN: {telegram_notify.TELEGRAM_BOT_TOKEN}")

# Let's look at the source again - does it read from hermes config?
with open('/root/openmsaify/msai/dashboards/telegram_notify.py', 'r') as f:
    src = f.read()

# Find where else TELEGRAM_BOT_TOKEN might be assigned
print("\nOther token assignments in telegram_notify.py:")
for i, line in enumerate(src.split('\n'), 1):
    if 'TELEGRAM_BOT_TOKEN' in line and '=' in line:
        print(f"  {i}: {line}")

# Check if it uses hermes config
print("\nSearching for config/load imports in telegram_notify.py:")
for i, line in enumerate(src.split('\n'), 1):
    if any(kw in line.lower() for kw in ['import.*config', 'from.*config', 'load', 'read_config']):
        print(f"  {i}: {line}")
