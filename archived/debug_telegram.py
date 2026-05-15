#!/usr/bin/env python3
import os
import sys

# Check what environment provides
print("=== Environment Check ===")
print(f"TELEGRAM_BOT_TOKEN: {os.environ.get('TELEGRAM_BOT_TOKEN', 'NOT SET')[:30]}...")
print(f"TELEGRAM_CHAT_ID: {os.environ.get('TELEGRAM_CHAT_ID', 'NOT SET')}")
print(f"HERMES_HOME: {os.environ.get('HERMES_HOME', 'NOT SET')}")

# Try to load token same way telegram_notify.py does
token = os.environ.get("TELEGRAM_BOT_TOKEN", "8604476969:***")
print(f"\nResolved token: {token[:30]}...")

# Try to call getUpdates to verify token works
import urllib.request
import json

url = f"https://api.telegram.org/bot{token}/getUpdates"
try:
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        print(f"\ngetUpdates result: ok={data.get('ok')}")
        if data.get('ok') and data.get('result'):
            print(f"Latest update: {data['result'][0]}")
        else:
            print(f"Error: {data}")
except Exception as e:
    print(f"\ngetUpdates failed: {e}")
