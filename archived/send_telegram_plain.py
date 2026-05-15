#!/usr/bin/env python3
import os
import requests

# Use environment variable for bot token
BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '7617538927:AAGX4ASf88G4K4VpayndvuE monotonicallyIncre642')
CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', '5807834405')

# Read plain text report
with open('/root/openmsaify/dashboard_report_plain.txt', 'r') as f:
    message = f.read()

response = requests.post(
    f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage',
    json={'chat_id': CHAT_ID, 'text': message},
    timeout=30
)

print(f'Status: {response.status_code}')
if response.status_code == 200:
    print('Dashboard report sent successfully to Telegram')
else:
    print(f'Error: {response.text}')
