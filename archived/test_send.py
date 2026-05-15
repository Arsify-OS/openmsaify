#!/usr/bin/env python3
import sys
import json
import os

sys.path.insert(0, '/root/openmsaify/msai/dashboards')
import telegram_notify

summary = {
    'timestamp': '2026-05-14 07:10 UTC',
    'markets_scanned': 200,
    'total_volume_24h': 0,
    'total_liquidity': 0,
    'anomaly_details': [],
    'portfolio': {'filled': 0, 'pending': 0}
}

markets = [
    {
        "question": "Will XRP reach $2.00 in May?",
        "outcomePrices": json.dumps([0.038]),
        "volume24hr": 98418
    },
    {
        "question": "Will Solana reach $130 in May?",
        "outcomePrices": json.dumps([0.022]),
        "volume24hr": 97733
    },
]

result = telegram_notify.send_scan_report('5807834405', summary, markets)
print(f'Result: {result}')
