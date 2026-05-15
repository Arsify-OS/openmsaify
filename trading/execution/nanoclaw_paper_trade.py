"""
nanoclaw_paper_trade — Polymarket Trading Engine
Part of openmsaify-trading (MIT License)
Copyright (c) 2025 OpenMSAify
"""

#!/usr/bin/env python3
"""
Nanoclaw Paper Trade Runner — for cron jobs
Scans markets, finds opportunities, executes paper trades via Nanoclaw, delivers to Telegram.
"""

import os
import sys
import json
import httpx
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, "/root/polymarket")
sys.path.insert(0, "/root/openswarm/deep_research/tools")

from dotenv import load_dotenv
load_dotenv("/root/polymarket/.env.local")

from nanoclaw import Nanoclaw


def scan_opportunities(claw, limit=30):
    """Scan live markets for paper trading opportunities."""
    markets = claw.gamma.get_active_markets(limit=limit, min_volume=5000)
    opportunities = []
    
    for m in markets:
        prices = m.get("outcomePrices", [])
        if isinstance(prices, str):
            try:
                prices = json.loads(prices)
            except json.JSONDecodeError:
                continue
        if not prices:
            continue
        
        yes_price = float(prices[0])
        # Look for markets with price between 10%-90% (not near-resolved)
        if 0.10 <= yes_price <= 0.90:
            vol = float(m.get("volume24hr", 0) or 0)
            liq = float(m.get("liquidity", 0) or 0)
            if vol > 10000 and liq > 1000:
                opportunities.append(m)
    
    # Sort by volume
    opportunities.sort(key=lambda x: float(x.get("volume24hr", 0) or 0), reverse=True)
    return opportunities[:5]


def build_report(claw, opportunities):
    """Build trading report for Telegram."""
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    report = f"🦾 **HERMES NANICLAW — Paper Trade**\n"
    report += f"🕐 {timestamp}\n"
    report += f"📊 Mode: PAPER TRADING\n"
    report += f"💼 Signer: {claw.clob.api_key[:8] if claw.clob.api_key else 'N/A'}...\n\n"
    
    if not opportunities:
        report += "⛔ No suitable opportunities found.\n"
    else:
        report += f"🔍 {len(opportunities)} opportunities found:\n\n"
        
        for opp in opportunities:
            prices = opp.get("outcomePrices", [])
            if isinstance(prices, str):
                prices = json.loads(prices)
            yes_price = float(prices[0]) if prices else 0.5
            
            vol = float(opp.get("volume24hr", 0) or 0)
            liq = float(opp.get("liquidity", 0) or 0)
            question = opp.get("question", "")[:80]
            cond_id = opp.get("conditionId", "")[:20]
            
            report += f"▫️ {question}\n"
            report += f"  YES: {yes_price:.0%} | Vol: ${vol:,.0f} | Liq: ${liq:,.0f}\n"
            report += f"  ID: {cond_id}...\n\n"
    
    # Summary
    summary = claw.summary()
    report += f"---\n"
    report += f"📈 Orders this session: {summary['total_orders']}\n"
    report += f"✅ Filled: {summary['filled']}\n"
    report += f"💰 Daily PnL: ${summary['daily_pnl']:.2f}\n"
    report += f"🔒 Kill Switch: {'ACTIVE' if summary['kill_switch'] else 'OFF'}\n"
    
    return report


def send_telegram(report, chat_id=None):
    """Send report to Telegram."""
    chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID", "5807834405")
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not bot_token:
        print("No TELEGRAM_BOT_TOKEN, skipping")
        return False
    
    max_len = 4096
    chunks = [report[i:i+max_len] for i in range(0, len(report), max_len)]
    
    for i, chunk in enumerate(chunks):
        prefix = f"📊 Paper Trade ({i+1}/{len(chunks)})\n\n" if len(chunks) > 1 else ""
        try:
            r = httpx.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json={"chat_id": chat_id, "text": prefix + chunk, "parse_mode": "Markdown"},
                timeout=15,
            )
            if r.status_code != 200:
                print(f"Telegram error: {r.text}")
                return False
        except Exception as e:
            print(f"Telegram send error: {e}")
            return False
    return True


def main():
    claw = Nanoclaw(paper=True)
    
    try:
        print("Scanning markets...")
        opps = scan_opportunities(claw, limit=30)
        
        print(f"Found {len(opps)} opportunities")
        for opp in opps:
            q = opp.get("question", "")[:60]
            prices = opp.get("outcomePrices", [])
            if isinstance(prices, str):
                prices = json.loads(prices)
            yes = float(prices[0]) if prices else 0.5
            vol = float(opp.get("volume24hr", 0) or 0)
            print(f"  • {q} | YES:{yes:.0%} | Vol:${vol:,.0f}")
        
        # Build and send report
        report = build_report(claw, opps)
        print("\n" + report)
        
        sent = send_telegram(report)
        if sent:
            print("✅ Telegram delivery successful")
        else:
            print("❌ Telegram delivery failed")
            
    finally:
        claw.close()


if __name__ == "__main__":
    main()
