#!/usr/bin/env python3
import requests

BOT_TOKEN = '7617538927:AAGX4ASf88G4K4VpayndvuE monotonicallyIncre642'
CHAT_ID = '5807834405'

# Read message from file
with open('/root/openmsaify/dashboard_report.txt', 'r') as f:
    message = f.read()

response = requests.post(
    f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage',
    json={
        'chat_id': CHAT_ID,
        'text': message
    },
    timeout=30
)

print(f'Status Code: {response.status_code}')
print(f'Response: {response.text}')
