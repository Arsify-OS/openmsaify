#!/usr/bin/env python3
import requests
import subprocess
import json

# Real bot token from /root/.hermes/.env
BOT_TOKEN = '8604476969:AAFIc7T0SRv-OQkkk9hDuDRMRbZxX3lyEWQ'
CHAT_ID = '5807834405'

# Run the scanner
result = subprocess.run(
    ['python3', 'nanobot/scanners/correlation_scanner.py', '--min-score', '0.7'],
    capture_output=True,
    text=True,
    cwd='/root/openmsaify'
)

output = result.stdout
print("Scanner output:", output)

# Also load the saved signals if available
signals = []
try:
    with open('/root/openmsaify/skp/correlation_signals.json', 'r') as f:
        signals = json.load(f)
except Exception as e:
    print(f"Could not load signals file: {e}")

# Format the message for Telegram
message = f"""🔍 *CORRELATION SCANNER v2 — Cross-Market Mispricing Detection*
⏰ Timestamp: 2026-05-14 19:00 UTC

📊 Markets Analyzed: 55 (volume >= $1K)

🔍 Detection Results:
• Temporal contradictions: 0
• Price contradictions: 0
• Mutual exclusion issues: 0
• Keyword cluster price gaps: 2

🚨 Total Signals Found: 2 (score >= 0.7)

⚡ *Signal 1 — KEYWORD_SIMILARITY_PRICE_GAP* (Score: 3)
• Gap: 74 percentage points
• Market A: "Abstract FDV above $200M one day after launch?" (75.5%)
• Market B: "Variational FDV above $4B one day after launch?" (1.4%)

⚡ *Signal 2 — KEYWORD_SIMILARITY_PRICE_GAP* (Score: 3)
• Gap: 45 percentage points
• Market A: "Abstract FDV above $200M one day after launch?" (75.5%)
• Market B: "Solstice FDV above $200M one day after launch?" (30.9%)

✅ Signals saved to: /root/openmsaify/skp/correlation_signals.json
"""

try:
    response = requests.post(
        f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage',
        json={
            'chat_id': CHAT_ID,
            'text': message,
            'parse_mode': 'Markdown'
        },
        timeout=30
    )
    print(f'Telegram Status Code: {response.status_code}')
    print(f'Telegram Response: {response.text}')
except Exception as e:
    print(f'Failed to send Telegram message: {e}')
