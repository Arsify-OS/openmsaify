#!/usr/bin/env python3
import os
import requests
import json

# Get bot token from environment
bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
chat_id = "5807834405"

if not bot_token:
    print("ERROR: TELEGRAM_BOT_TOKEN not found in environment")
    exit(1)

# Performance dashboard report
message = """HERMES PERFORMANCE DASHBOARD - 2026-05-14 19:16 UTC

PORTFOLIO SUMMARY
Bankroll: $1,109.80 (-5.15%)
Realized PnL: -$60.20
Total Trades: 8 (Open: 6, Resolved: 2)

TRADING METRICS
Win Rate: 0.0% (0W / 2L)
Profit Factor: 0.00
Avg Win: $0.00 | Avg Loss: -$30.10
Expectancy/Trade: -$30.10
Max Drawdown: 5.1%

OPEN POSITIONS (6 active)
1. NO - Bitcoin above $72,000 | Bet: $37.30 | AI: 25.1%
2. NO - Abstract FDV above $200M | Bet: $46.20 | AI: 31.0%
3. NO - Al Shabab vs Al Ittihad | Bet: $40.70 | AI: 31.0%
4. NO - Trump UFO declassification | Bet: $61.70 | AI: 32.0%
5. NO - Messi 2026 World Cup | Bet: $42.00 | AI: 36.1%

CATEGORY BREAKDOWN
Crypto: 1 trade | 0.0% WR | PnL: -$32.80
Sports: 1 trade | 0.0% WR | PnL: -$27.40

TIER PERFORMANCE
Tier S: 2 trades | 0.0% WR | PnL: -$60.20

SCAN SUMMARY
Markets Scanned: 200
Tier S: 7 | Tier A: 21 | Tier B: 13
Regime: hype (41 signals)

SYSTEM HEALTH
Active Cron Jobs: 7
Last Mispricing Scan: 2.2h ago

Hermes v3.0 | Market Calibration Intelligence Engine"""

url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
payload = {
    "chat_id": chat_id,
    "text": message,
    "parse_mode": "HTML"
}

response = requests.post(url, json=payload, timeout=30)
print(f"Status: {response.status_code}")
print(f"Response: {response.text}")
