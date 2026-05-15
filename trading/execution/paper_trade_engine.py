"""
paper_trade_engine — Polymarket Trading Engine
Part of openmsaify-trading (MIT License)
Copyright (c) 2025 OpenMSAify
"""

#!/usr/bin/env python3
"""
PAPER TRADE ENGINE v2 — Week 6A Integration

Full paper trading pipeline:
1. Resolve any previously open trades
2. Scan active markets with full ensemble calibrator
3. Apply risk management + regime awareness
4. Size positions with Kelly criterion
5. Track PnL and portfolio performance
6. Deliver Telegram-ready report

Usage: python3 paper_trade_engine.py [--status] [--trade-min-tier A] [--max-new 3]
"""

import json
import os
import sys
import warnings
from datetime import datetime, timezone, timedelta
from collections import defaultdict

warnings.filterwarnings("ignore")

import numpy as np
import httpx

sys.path.insert(0, "/root/polymarket")
from ensemble_calibrator import EnsembleCalibrator, mispricing_tier
from position_sizing import PositionSizer
from risk_management import RiskManager, DEFAULT_CONFIG
import historical_prior as hp

# Paths
PAPER_TRADE_PATH = "/root/polymarket/skp/paper_trades.json"
RISK_STATE_PATH = "/root/polymarket/skp/risk_state.json"
GAMMA_URL = "https://gamma-api.polymarket.com"

BANKROLL_START = 1.17  # Current Polymarket seed


class PaperTradeEngine:
    """
    End-to-end paper trading engine.
    
    For each 6-hour cycle:
    1. Check resolved markets → update PnL
    2. Scan for Tier S/A mispricings
    3. Risk check (drawdown, cooling, exposure)
    4. Kelly-size new positions
    5. Deliver report
    """
    
    def __init__(self, bankroll=BANKROLL_START):
        self.bankroll = bankroll
        self.calibrator = EnsembleCalibrator()
        
        # Load existing trades
        self.trades = self._load_trades()
        
        # Calculate bankroll from resolved trades
        self._recalculate_bankroll()
        
        # Initialize position sizer with current bankroll
        self.sizer = PositionSizer(bankroll=self.bankroll)
        
        # Initialize risk manager
        self.risk = RiskManager(initial_bankroll=self.bankroll)
        # Load persisted risk state
        self._load_risk_state()
    
    def _load_trades(self):
        if os.path.exists(PAPER_TRADE_PATH):
            with open(PAPER_TRADE_PATH) as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
        return []
    
    def _load_risk_state(self):
        """Load risk manager state from paper trade history."""
        if not os.path.exists(RISK_STATE_PATH):
            return
        
        with open(RISK_STATE_PATH) as f:
            state = json.load(f)
        
        # Apply state to risk manager
        self.risk.current_bankroll = state.get("current_bankroll", self.bankroll)
        self.risk.peak_bankroll = state.get("peak_bankroll", self.bankroll)
        self.risk.consecutive_losses = state.get("consecutive_losses", 0)
        self.risk.cooldown_until = state.get("cooldown_until")
        
        # Rebuild open positions from unresolved trades
        for t in self.trades:
            if not t.get("resolved"):
                self.risk.open_positions[t["position_id"]] = {
                    "category": t.get("category", "Other"),
                    "bet_size": t.get("bet_size", 0),
                    "opened_at": t.get("opened_at", ""),
                }
    
    def _save_risk_state(self):
        state = {
            "current_bankroll": round(self.risk.current_bankroll, 4),
            "peak_bankroll": round(self.risk.peak_bankroll, 4),
            "consecutive_losses": self.risk.consecutive_losses,
            "cooldown_until": self.risk.cooldown_until,
            "saved_at": datetime.now(timezone.utc).isoformat(),
        }
        with open(RISK_STATE_PATH, "w") as f:
            json.dump(state, f, indent=2)
    
    def _save_trades(self):
        with open(PAPER_TRADE_PATH, "w") as f:
            json.dump(self.trades, f, indent=2, default=str)
    
    def _recalculate_bankroll(self):
        """Recalculate bankroll from trade history."""
        starting = BANKROLL_START
        realized_pnl = 0
        for t in self.trades:
            if t.get("resolved") and t.get("pnl") is not None:
                realized_pnl += t["pnl"]
        self.bankroll = round(starting + realized_pnl, 4)
    
    def resolve_pending_trades(self):
        """Check all unresolved trades for market resolution."""
        resolved_list = []
        
        open_trades = [t for t in self.trades if not t.get("resolved")]
        if not open_trades:
            return resolved_list
        
        print(f"Checking {len(open_trades)} open trades for resolution...")
        
        for trade in open_trades:
            market_id = trade.get("market_id", "")
            if not market_id:
                continue
            
            try:
                resp = httpx.get(
                    f"{GAMMA_URL}/markets/{market_id}",
                    headers={"Accept": "application/json"},
                    timeout=10,
                )
                if resp.status_code != 200 or not resp.json():
                    continue
                
                m = resp.json()
                prices = json.loads(m.get("outcomePrices", "[]"))
                if not prices or len(prices) < 2:
                    continue
                
                yes_price = float(prices[0])
                no_price = float(prices[1])
                
                # Check if resolved
                if yes_price == 1.0 or no_price == 1.0:
                    trade["resolved"] = True
                    trade["resolved_at"] = datetime.now(timezone.utc).isoformat()
                    trade["outcome"] = "Yes" if yes_price == 1.0 else "No"
                    
                    # Determine if bet won
                    if trade.get("direction") == "YES":
                        won = (yes_price == 1.0)
                    else:
                        won = (no_price == 1.0)
                    
                    trade["won"] = won
                    
                    # Payout calculation
                    if won:
                        entry = trade.get("yes_price", 0.5)
                        if trade.get("direction") == "YES":
                            payout = trade["bet_size"] / max(entry, 0.001)
                        else:
                            payout = trade["bet_size"] / max(1 - entry, 0.001)
                        trade["payout"] = round(payout, 4)
                        trade["pnl"] = round(payout - trade["bet_size"], 4)
                    else:
                        trade["payout"] = 0
                        trade["pnl"] = round(-trade["bet_size"], 4)
                    
                    resolved_list.append(trade)
                    print(f"  ✅ Resolved: [{trade.get('direction','?')}] {trade['question'][:45]}... "
                          f"{'WIN' if won else 'LOSS'} | PnL: ${trade['pnl']:+.4f}")
                
            except Exception:
                continue
        
        if resolved_list:
            # Update bankroll
            self._recalculate_bankroll()
            self.risk.current_bankroll = self.bankroll
            self.risk.peak_bankroll = max(self.risk.peak_bankroll, self.bankroll)
            
            # Update risk manager with outcomes
            for t in resolved_list:
                self.risk.record_trade(
                    t["position_id"],
                    t.get("category", "Other"),
                    t["bet_size"],
                    t["won"],
                    t.get("payout", 0),
                )
            
            self._save_risk_state()
            self._save_trades()
        
        return resolved_list
    
    def scan_and_trade(self, min_tier="A", max_new_trades=3):
        """Scan for standard mispricings and correlation signals, then open trades."""
        # Check risk first
        allowed, reason = self.risk.is_trading_allowed()
        if not allowed:
            return {"status": "risk_blocked", "reason": reason, "trades_opened": 0}
        
        # TRY CORRELATION SIGNALS FIRST (higher confidence type of edge)
        corr_opened = 0
        corr_signals = self._get_correlation_signals()
        for corr in corr_signals:
            if corr_opened >= max_new_trades:
                break
            result = self._trade_correlation_signal(corr)
            if result.get("traded"):
                corr_opened += 1
        
        remaining = max_new_trades - corr_opened
        if remaining <= 0:
            return {"status": "ok", "trades_opened": corr_opened, "new_trades": [], "bankroll": self.bankroll}
        
        # FALLBACK TO STANDARD MISPRICING SCAN
        return self._scan_and_trade_markets(min_tier=min_tier, max_new_trades=remaining)
    
    def _get_correlation_signals(self):
        """Load correlation signals from latest scan."""
        if os.path.exists("/root/polymarket/skp/correlation_signals.json"):
            with open("/root/polymarket/skp/correlation_signals.json") as f:
                data = json.load(f)
            return data.get("signals", [])
        return []
    
    def _trade_correlation_signal(self, signal):
        """Open a paper trade based on a correlation signal."""
        try:
            signal_type = signal.get("type", "")
            score = signal.get("score", 0)
            
            # Extract which market to bet on from the signal
            # For price_range/keyword signals: bet on the UNDERPRICED market (the cheaper one)
            # For mutual exclusion: bet on underpriced vs peers
            market_1_text = signal.get("market_1", "")
            market_2_text = signal.get("market_2", "")
            
            # Parse entry price from text like "(76.0%)"
            import re
            price1_match = re.search(r"\((\d+\.?\d*)%\)", market_1_text)
            price2_match = re.search(r"\((\d+\.?\d*)%\)", market_2_text)
            
            if not price1_match or not price2_match:
                return {"traded": False, "reason": "Cannot parse prices"}
            
            price1 = float(price1_match.group(1)) / 100
            price2 = float(price2_match.group(1)) / 100
            
            question = market_1_text if price1 < price2 else market_2_text
            yes_price = min(price1, price2)
            other_price = max(price1, price2)
            
            # Bet YES on the underpriced one
            direction = "YES"
            
            # Category extraction
            category = hp.derive_category(question)
            
            # Check category limit
            ok, _ = self.risk.check_category_limit(category)
            if not ok:
                return {"traded": False, "reason": "Category limit reached"}
            
            # CORRELATION SIGNAL: use calibrated probability from cheaper price
            # Our edge = yes_price vs expected (simplified: assume 0.40 for underpriced)
            cal_prob = 0.40  # conservative estimate
            
            # Size position
            signal_data = {
                "probability": cal_prob,
                "market_price": yes_price,
                "confidence": 0.80 if score >= 4 else 0.60,
                "tier": "S" if score >= 5 else "A",
                "category": category,
                "volume": 10000,  # estimated minimum
                "edge": cal_prob - yes_price,
                "bankroll": self.bankroll,
            }
            
            sizing = self.sizer.size_position(signal_data)
            if not sizing.get("should_bet"):
                return {"traded": False, "reason": "Sizing filter"}
            
            position_id = f"corr_{signal_type[:6]}_{int(datetime.now().timestamp())}"
            
            self.risk.open_position(position_id, category, sizing["bet_size_usdc"])
            
            trade = {
                "position_id": position_id,
                "market_id": "",  # Not available from correlation
                "question": question[:200],
                "category": category,
                "direction": direction,
                "bet_size": round(sizing["bet_size_usdc"], 4),
                "yes_price": yes_price,
                "ai_probability": cal_prob,
                "tier": sizing.get("tier") or signal.get("tier", "A"),
                "confidence": sizing.get("confidence") or signal.get("confidence", 0.5),
                "regime": self.regime_engine.current_regime or "unknown",
                "kelly_fraction": sizing.get("kelly_fraction", 0),
                "effective_edge": cal_prob - yes_price,
                "opened_at": datetime.now(timezone.utc).isoformat(),
                "resolved": False,
                "pnl": None,
                "won": None,
                "signal_type": "CORRELATION",
                "correlation_type": signal_type,
            }
            
            self.trades.append(trade)
            self._save_trades()
            self._save_risk_state()
            
            return {"traded": True, "trade": trade}
            
        except Exception:
            return {"traded": False, "reason": "Error processing correlation"}
    
    def _scan_and_trade_markets(self, min_tier="A", max_new_trades=3):
        """Scan for standard mispricings and open new paper trades."""
        # Fetch markets
        try:
            resp = httpx.get(
                f"{GAMMA_URL}/markets",
                params={"limit": 200, "active": "true", "closed": "false",
                        "order": "volume", "ascending": "false"},
                timeout=15,
            )
            markets = resp.json() if resp.status_code == 200 else []
        except Exception:
            markets = []
        
        if not markets:
            return {"status": "no_markets", "trades_opened": 0}
        
        results = []
        trades_opened = 0
        
        for m in markets:
            if trades_opened >= max_new_trades:
                break
            
            try:
                prices = json.loads(m.get("outcomePrices", "[0.5, 0.5]"))
                yes_price = float(prices[0]) if prices else 0.5
                volume = float(m.get("volume", 0) or 0)
                spread = float(m.get("spread", 0) or 0) / 100 if m.get("spread") else None
                question = m.get("question", "")
                category = hp.derive_category(question)
                neg_risk = m.get("negRisk", False)
                
                # Skip neg_risk
                if neg_risk:
                    continue
                
                # Skip low volume
                if volume < 5000:
                    continue
                
                # Calibrate with full ensemble
                cal = self.calibrator.calibrate(
                    market_price_yes=yes_price,
                    question=question,
                    category=category,
                    volume=volume,
                    spread=spread,
                    signal_type="LOW_PRICE",
                )
                
                # FIX D: Apply narrative distortion filter
                narrative = cal.get("narrative_distortion", {})
                narrative_score = narrative.get("distortion_score", 0) if isinstance(narrative, dict) else 0
                if narrative_score >= 0.5:
                    # High narrative distortion — market may be driven by hype, skip
                    continue
                
                tier, score = mispricing_tier({**cal, "volume": volume})
                
                # Only trade Tier S/A
                if tier not in ["S", "A"]:
                    continue
                
                # Check category limit
                ok, _ = self.risk.check_category_limit(category)
                if not ok:
                    continue
                
                # FIX D: Regime-based Kelly adjustment
                regime = cal.get("regime", "unknown")
                regime_reliability = self.calibrator.regime_engine.get_regime_reliability(regime)
                
                # Size position with regime multiplier
                signal = {
                    "probability": cal["final_probability"],
                    "market_price": yes_price,
                    "confidence": cal["calibration_confidence"] * regime_reliability,  # Regime adjustment
                    "tier": tier,
                    "category": category,
                    "volume": volume,
                    "edge": cal["raw_edge"],
                    "bankroll": self.bankroll,
                }
                
                sizing = self.sizer.size_position(signal)
                if not sizing.get("should_bet"):
                    continue
                
                # Create position ID
                position_id = f"pt_{m.get('id', '')[:12]}_{int(datetime.now().timestamp())}"
                
                # Open position in risk manager
                self.risk.open_position(position_id, category, sizing["bet_size_usdc"])
                
                # Create trade record
                trade = {
                    "position_id": position_id,
                    "market_id": m.get("id"),
                    "question": question[:200],
                    "category": category,
                    "direction": sizing["direction"],
                    "bet_size": round(sizing["bet_size_usdc"], 4),
                    "yes_price": yes_price,
                    "ai_probability": cal["final_probability"],
                    "tier": tier,
                    "confidence": cal["calibration_confidence"],
                    "regime": regime,
                    "regime_reliability": round(regime_reliability, 3),
                    "narrative_distortion": narrative_score,
                    "kelly_fraction": sizing.get("kelly_fraction", 0),
                    "effective_edge": cal.get("effective_edge", 0),
                    "opened_at": datetime.now(timezone.utc).isoformat(),
                    "resolved": False,
                    "pnl": None,
                    "won": None,
                }
                
                self.trades.append(trade)
                results.append(trade)
                trades_opened += 1
                
            except Exception:
                continue
        
        self._save_trades()
        self._save_risk_state()
        
        return {
            "status": "ok",
            "trades_opened": trades_opened,
            "new_trades": results,
            "bankroll": self.bankroll,
        }
    
    def get_status(self):
        """Get comprehensive portfolio status for Telegram."""
        open_trades = [t for t in self.trades if not t.get("resolved")]
        resolved = [t for t in self.trades if t.get("resolved")]
        
        total_pnl = sum(t.get("pnl", 0) for t in resolved) if resolved else 0
        wins = sum(1 for t in resolved if t.get("won"))
        losses = sum(1 for t in resolved if not t.get("won"))
        win_rate = wins / max(wins + losses, 1)
        
        risk = self.risk.get_status()
        
        return {
            "bankroll": round(self.bankroll, 4),
            "growth_pct": round((self.bankroll / BANKROLL_START - 1) * 100, 2),
            "risk_status": {k: v for k, v in risk.items() if k != "reason"},
            "total_trades": len(self.trades),
            "open_positions": len(open_trades),
            "resolved_trades": len(resolved),
            "wins": wins,
            "losses": losses,
            "win_rate": round(win_rate, 3),
            "total_pnl": round(total_pnl, 4),
        }
    
    def format_telegram_report(self, resolved_list=None, new_trades=None, scan_result=None):
        """Format a complete report for Telegram delivery."""
        status = self.get_status()
        
        lines = [
            "📊 PAPER TRADE ENGINE v2",
            f"📅 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
            "",
            f"💰 Bankroll: ${status['bankroll']:.4f} ({status['growth_pct']:+.2f}%)",
            f"📈 Win Rate: {status['win_rate']:.1%} ({status['wins']}W/{status['losses']}L)",
            f"📊 PnL: ${status['total_pnl']:+.4f}",
            f"🔄 Open: {status['open_positions']} | Resolved: {status['resolved_trades']}",
            "",
        ]
        
        # Risk status
        trading_ok = status['risk_status'].get('trading_allowed', True)
        if trading_ok:
            lines.append("🟢 Trading: ALLOWED")
        else:
            lines.append(f"🔴 Trading: BLOCKED ({status['risk_status'].get('reason', 'limit')})")
        
        lines.append(f"   Drawdown: {status['risk_status'].get('drawdown', 0):.1%}")
        lines.append(f"   Exposure: {status['risk_status'].get('total_exposure_pct', 0):.1%}")
        lines.append("")
        
        # Resolved trades
        if resolved_list:
            lines.append("─────── RESOLVED ───────")
            for t in resolved_list:
                icon = "🟢" if t.get("won") else "🔴"
                pnl_sign = "+" if t.get("pnl", 0) >= 0 else ""
                lines.append(f"{icon} [{t.get('direction','?')}] {t['question'][:45]}...")
                lines.append(f"   {t.get('outcome','?')} | PnL: ${pnl_sign}{t.get('pnl',0):.4f} | Tier: {t.get('tier','?')}")
            lines.append("")
        
        # New trades opened
        if new_trades:
            lines.append("─────── NEW ENTRIES ───────")
            for t in new_trades:
                edge_sign = "+" if t.get("effective_edge", 0) > 0 else ""
                lines.append(f"🟡 [{t.get('tier','?')}] [{t.get('direction','?')}] {t['question'][:45]}...")
                lines.append(f"   Bet: ${t.get('bet_size',0):.4f} | Edge: {edge_sign}{t.get('effective_edge',0):.3f} | AI: {t.get('ai_probability',0):.1%}")
                lines.append(f"   Category: {t.get('category','')} | Regime: {t.get('regime','')}")
            lines.append("")
        
        # Open positions
        open_trades = [t for t in self.trades if not t.get("resolved")]
        if open_trades:
            lines.append("─────── OPEN POSITIONS ───────")
            for t in open_trades:
                lines.append(f"⏳ [{t.get('direction','?')}] {t['question'][:45]}...")
                lines.append(f"   Bet: ${t.get('bet_size',0):.4f} | Entry: {t.get('yes_price',0):.1%}")
            lines.append("")
        
        lines.append("🤖 Paper Trade Engine v2 | Kelly-sized + Risk-managed")
        
        return "\n".join(lines)


def main():
    engine = PaperTradeEngine()
    
    if "--status" in sys.argv:
        report = engine.format_telegram_report()
        print(report)
        print(f"\n___ALERT___\n{report}")
        return
    
    # Parse args
    min_tier = "A"
    if "--trade-min-tier" in sys.argv:
        idx = sys.argv.index("--trade-min-tier") + 1
        if idx < len(sys.argv):
            min_tier = sys.argv[idx].upper()
    
    max_new = 3
    if "--max-new" in sys.argv:
        idx = sys.argv.index("--max-new") + 1
        if idx < len(sys.argv):
            max_new = int(sys.argv[idx])
    
    # Step 1: Resolve pending trades
    resolved_list = engine.resolve_pending_trades()
    
    # Step 2: Scan and open new trades
    new_result = engine.scan_and_trade(min_tier=min_tier, max_new_trades=max_new)
    new_trades = new_result.get("new_trades", [])
    
    # Step 3: Generate report
    report = engine.format_telegram_report(
        resolved_list=resolved_list,
        new_trades=new_trades,
        scan_result=new_result,
    )
    
    print(report)
    print(f"\n___ALERT___\n{report}")


if __name__ == "__main__":
    main()
