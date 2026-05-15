#!/usr/bin/env python3
import requests
import sys

BOT_TOKEN = '8604476969:AAFIc7T0SRv'
CHAT_ID = '5807834405'

# Read message from file
report_path = '/root/openmsaify/dashboard_report_plain.txt'
if len(sys.argv) > 1:
    report_path = sys.argv[1]

with open(report_path, 'r') as f:
    message = f.read()

print(f"Sending Telegram message to chat {CHAT_ID}...")
print(f"Message length: {len(message)} characters")

response = requests.post(
    f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage',
    json={
        'chat_id': CHAT_ID,
        'text': message,
        'parse_mode': 'text'
    },
    timeout=30
)

print(f'Status Code: {response.status_code}')
print(f'Response: {response.text}')

if response.status_code == 200:
    print('\n✅ SUCCESS: Report delivered to Telegram chat 5807834405')
else:
    print(f'\n❌ FAILED: {response.text}')
