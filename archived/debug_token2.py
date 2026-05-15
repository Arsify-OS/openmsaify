#!/usr/bin/env python3
import os, sys

# Monkey-patch telegram_notify to see what token it uses
token_before = os.environ.get("TELEGRAM_BOT_TOKEN", "NOT SET")
print(f"TELEGRAM_BOT_TOKEN in env: {token_before[:20]}...")

# Now import telegram_notify - it reads token at import time
sys.path.insert(0, '/root/openmsaify/msai/dashboards')
import telegram_notify

# Check the module-level variable
print(f"telegram_notify.TELEGRAM_BOT_TOKEN: {telegram_notify.TELEGRAM_BOT_TOKEN[:20]}...")

# Check any other token sources
print(f"telegram_notify.TELEGRAM_API_BASE: {telegram_notify.TELEGRAM_API_BASE[:40]}...")
