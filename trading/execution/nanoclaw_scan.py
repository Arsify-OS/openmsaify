"""
nanoclaw_scan — Polymarket Trading Engine
Part of openmsaify-trading (MIT License)
Copyright (c) 2025 OpenMSAify
"""

#!/usr/bin/env python3
"""
Quick Market Scan — deliver opportunities to Gateway + Telegram.

Scans high-volume Polymarket markets, sends each opportunity to
Gateway /webhook/nanobot for MSABot decision, then executes
via Gateway /execute/trade (uses email wallet via Selenium).

Cronjob: every 2 hours (ID: f6d763660f1b)
"""

import os
import sys
import json
import httpx
import requests
from datetime import datetime, timezone

sys.path.insert(0, "/root/polymarket")

from dotenv import load_dotenv
load_dotenv("/root/polymarket/.env.local")

# ── Gateway Configuration ──
GATEWAY_ENABLED = os.getenv("GATEWAY_SCANNER_ENABLED", "1") == "1"
GATEWAY_URL = os.getenv("GATEWAY_URL", "http://localhost:8083")
GATEWAY_WEBHOOK_SECRET = os.getenv("NANOBOT_SECRET", "change-me")

# Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "5807834405")


def send_telegram(text: str, parse_mode: str = "Markdown"):
    """Send message to Telegram (non-blocking)."""
    if not TELEGRAM_BOT_TOKEN:
        return
    try:
        httpx.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": parse_mode},
            timeout=15,
        )
    except Exception as e:
        print(f"⚠️  Telegram send failed: {e}")


def post_opportunity_to_gateway(opportunity: dict) -> dict:
    """
    Send single opportunity to Gateway webhook.
    Returns decision: {should_trade, direction, size, reason}
    """
    try:
        headers = {
            "Content-Type": "application/json",
            "X-Nanobot-Secret": GATEWAY_WEBHOOK_SECRET,
        }
        payload = {"opportunity": opportunity}
        resp = requests.post(
            f"{GATEWAY_URL}/webhook/nanobot",
            json=payload,
            headers=headers,
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json()
        else:
            print(f"⚠️  Gateway webhook returned {resp.status_code}: {resp.text[:100]}")
            return {"should_trade": False, "reason": f"HTTP {resp.status_code}"}
    except requests.exceptions.ConnectionError:
        print("⚠️  Gateway not reachable — is it running on port 8083?")
        return {"should_trade": False, "reason": "Gateway connection failed"}
    except Exception as e:
        print(f"⚠️  Gateway webhook error: {e}")
        return {"should_trade": False, "reason": str(e)}


def execute_trade_via_gateway(market_id: str, side: str, size_usdc: float, price: float = None):
    """
    Execute trade through Gateway /execute/trade endpoint.
    Gateway will use appropriate executor (Selenium for email wallet).
    """
    try:
        gateway_jwt = os.getenv("GATEWAY_SERVICE_JWT")
        if not gateway_jwt:
            print("⚠️  GATEWAY_SERVICE_JWT not set — skipping execution")
            return {"success": False, "error": "No service JWT configured"}
        
        headers = {
            "Authorization": f"Bearer {gateway_jwt}",
            "Content-Type": "application/json",
        }
        payload = {
            "market_id": market_id,
            "side": side.upper(),
            "size_usdc": round(size_usdc, 4),
        }
        if price is not None:
            payload["price"] = round(price, 6)
        
        resp = requests.post(
            f"{GATEWAY_URL}/execute/trade",
            json=payload,
            headers=headers,
            timeout=15,
        )
        data = resp.json()
        if resp.status_code == 200:
            print(f"✅ Trade executed: {side} ${size_usdc:.2f} on {market_id[:16]}...")
            return {"success": True, "tx_hash": data.get("tx_hash", ""), "order_id": data.get("order_id", "")}
        else:
            error_msg = data.get("error", resp.text[:200])
            print(f"❌ Trade failed: {error_msg}")
            return {"success": False, "error": error_msg}
    except Exception as e:
        print(f"❌ Execution error: {e}")
        return {"success": False, "error": str(e)}


def main():
    """Scan markets, route opportunities through Gateway, execute trades."""
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    msg = f"🔍 **HERMES MARKET SCAN**\n"
    msg += f"🕐 {timestamp}\n\n"
    
    # ── Fetch active markets ──
    try:
        r = httpx.get(
            "https://gamma-api.polymarket.com/markets",
            params={
                "limit": 20,
                "active": "true",
                "closed": "false",
                "order": "volume24hr",
                "ascending": "false",
            },
            timeout=15,
        )
        r.raise_for_status()
        markets = r.json()
    except Exception as e:
        msg += f"❌ Error fetching markets: {e}"
        send_telegram(msg)
        print(msg)
        return
    
    # ── Filter opportunities ──
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
        if 0.10 <= yes_price <= 0.90:
            vol = float(m.get("volume24hr", 0) or 0)
            liq = float(m.get("liquidity", 0) or 0)
            if vol > 5000 and liq > 500:
                opportunities.append({
                    "question": m.get("question", "")[:90],
                    "yes_price": yes_price,
                    "no_price": 1.0 - yes_price,
                    "volume": vol,
                    "liquidity": liq,
                    "conditionId": m.get("conditionId", ""),
                    "category": m.get("category", "Other"),
                    "end_date": m.get("endDate", ""),
                })
    
    opportunities.sort(key=lambda x: x["volume"], reverse=True)
    
    msg += f"📊 {len(markets)} markets scanned\n"
    msg += f"🎯 {len(opportunities)} opportunities (YES 10%-90%, Vol>$5K, Liq>$500)\n\n"
    
    # ── Process via Gateway ──
    executed_trades = []
    skipped_opportunities = []
    
    if GATEWAY_ENABLED:
        print(f"🚀 Processing {len(opportunities)} opportunities via Gateway...")
        
        for i, opp in enumerate(opportunities[:10]):
            cond_id = opp["conditionId"]
            print(f"\n[{i+1}] {opp['question'][:60]}...")
            print(f"    YES: {opp['yes_price']:.1%} | Vol: ${opp['volume']:,.0f}")
            
            gateway_opp = {
                "market": {
                    "id": cond_id,
                    "question": opp["question"],
                    "outcomePrices": [opp["yes_price"], opp["no_price"]],
                },
                "features": {
                    "category": opp["category"],
                    "volume_num": opp["volume"],
                    "liquidity": opp["liquidity"],
                    "duration_hours": (datetime.fromisoformat(opp["end_date"].replace("Z", "+00:00")) - datetime.now(timezone.utc)).total_seconds() / 3600
                    if opp["end_date"] else 720,
                    "spread": 0.02,
                    "neg_risk": False,
                },
                "base_probability": opp["yes_price"],
                "tier": "A" if opp["volume"] > 100000 else "B",
            }
            
            decision = post_opportunity_to_gateway(gateway_opp)
            
            if decision and decision.get("should_trade"):
                direction = decision.get("direction", "YES")
                size = decision.get("size", 0.1)
                reason = decision.get("reason", "")
                print(f"    ✅ MSABot: {direction} ${size:.2f} — {reason}")
                
                exec_result = execute_trade_via_gateway(
                    market_id=cond_id,
                    side=direction,
                    size_usdc=size,
                    price=opp["yes_price"] if direction == "YES" else opp["no_price"],
                )
                
                if exec_result["success"]:
                    executed_trades.append({
                        "market": opp["question"][:40],
                        "side": direction,
                        "size": size,
                        "tx": exec_result.get("tx_hash", "")[:16],
                    })
                    msg += f"*{i+1}.* {opp['question']}\n"
                    msg += f"    🎯 {direction} ${size:.2f} — Executed\n"
                else:
                    skipped_opportunities.append({
                        "market": opp["question"],
                        "reason": f"Execution failed: {exec_result.get('error')}",
                    })
            else:
                reason = decision.get("reason", "Filtered out") if decision else "Gateway error"
                print(f"    ⏭️  Skipped: {reason}")
                skipped_opportunities.append({"market": opp["question"], "reason": reason})
    else:
        print("ℹ️  Gateway disabled — only reporting opportunities")
        for i, opp in enumerate(opportunities[:10], 1):
            cond_short = opp["conditionId"][:16] if opp["conditionId"] else "N/A"
            msg += f"*{i}.* {opp['question']}\n"
            msg += f"    YES: {opp['yes_price']:.0%} | Vol: ${opp['volume']:,.0f}\n"
            msg += f"    ID: `{cond_short}`\n\n"
    
    # ── Build final message ──
    if executed_trades:
        msg += "\n✅ **Executed trades:**\n"
        for t in executed_trades:
            msg += f"  • {t['market']} — {t['side']} ${t['size']:.2f}\n"
    
    if skipped_opportunities:
        msg += "\n⏭️ **Skipped:**\n"
        for s in skipped_opportunities[:5]:
            msg += f"  • {s['market'][:50]} — {s['reason']}\n"
    
    msg += "\n🦾 Nanoclaw scan complete"
    
    # ── Send Telegram ──
    max_len = 4096
    chunks = [msg[i:i+max_len] for i in range(0, len(msg), max_len)]
    
    for i, chunk in enumerate(chunks):
        prefix = f"📊 Scan ({i+1}/{len(chunks)})\n\n" if len(chunks) > 1 else ""
        text = prefix + chunk
        try:
            r = httpx.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"},
                timeout=15,
            )
            if r.status_code != 200:
                print(f"Telegram error: {r.text}")
        except Exception as e:
            print(f"Telegram send failed: {e}")
    
    print(msg)


if __name__ == "__main__":
    main()
