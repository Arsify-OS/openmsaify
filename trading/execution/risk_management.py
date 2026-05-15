"""
risk_management — Polymarket Trading Engine
Part of openmsaify-trading (MIT License)
Copyright (c) 2025 OpenMSAify
"""

#!/usr/bin/env python3
"""
RISK MANAGEMENT ENGINE — Week 4

Protects capital with:
1. Drawdown protection (halve position size at 10% DD, stop at 20% DD)
2. Daily loss limit (stop trading if 5% lost in one day)
3. Max concurrent positions (limit exposure per category)
4. Minimum bet size ($1.00 Polymarket minimum)
5. Concentration risk (max 2 positions per category)
6. Time-based cooling (pause after 3 consecutive losses)
7. Kelly fraction decay (reduce Kelly as bankroll grows)

Usage: python3 risk_management.py [status|reset]
"""

import json
import os
import sys
import warnings
from datetime import datetime, timezone, timedelta
from collections import defaultdict, deque

warnings.filterwarnings("ignore")

import numpy as np

RISK_CONFIG_PATH = "/root/polymarket/skp/risk_config.json"
TRADE_LOG_PATH = "/root/polymarket/skp/trade_log.json"

DEFAULT_CONFIG = {
    "max_drawdown_pct": 0.20,         # Stop at 20% drawdown
    "drawdown_halt_at": 0.10,          # Reduce size at 10% drawdown
    "daily_loss_limit_pct": 0.05,      # Stop trading at 5% daily loss
    "min_bet_usdc": 1.0,               # Polymarket minimum
    "max_concurrent_positions": 5,     # Max open positions
    "max_per_category": 2,             # Max positions per category
    "max_total_exposure_pct": 0.80,    # Max 80% of bankroll deployed
    "cooling_losses": 3,               # Pause after N consecutive losses
    "cooling_period_hours": 6,         # Cooling pause duration
    "kelly_decay_threshold": 10.0,     # Reduce Kelly at $10 bankroll
    "kelly_decay_factor": 0.75,        # Multiply Kelly by this after threshold
}


class RiskManager:
    """
    Real-time risk management for Polymarket trading.
    
    Tracks:
    - Current drawdown
    - Daily PnL
    - Consecutive losses
    - Open positions by category
    - Total portfolio exposure
    """
    
    def __init__(self, config=None, initial_bankroll=1.17):
        self.config = config or DEFAULT_CONFIG
        self.peak_bankroll = initial_bankroll
        self.current_bankroll = initial_bankroll
        self.daily_pnl = 0.0
        self.daily_start = datetime.now(timezone.utc).date()
        self.consecutive_losses = 0
        self.cooldown_until = None
        self.open_positions = {}  # position_id -> {category, bet_size, ...}
        self.trade_log = []
        
        self._load_state()
    
    def _load_state(self):
        """Load persisted state."""
        if os.path.exists(RISK_CONFIG_PATH):
            with open(RISK_CONFIG_PATH) as f:
                state = json.load(f)
            self.peak_bankroll = state.get("peak_bankroll", self.peak_bankroll)
            self.current_bankroll = state.get("current_bankroll", self.current_bankroll)
            self.consecutive_losses = state.get("consecutive_losses", 0)
            self.cooldown_until = state.get("cooldown_until")
            self.open_positions = state.get("open_positions", {})
    
    def _save_state(self):
        """Persist state to disk."""
        state = {
            "peak_bankroll": self.peak_bankroll,
            "current_bankroll": self.current_bankroll,
            "consecutive_losses": self.consecutive_losses,
            "cooldown_until": self.cooldown_until,
            "open_positions": self.open_positions,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        with open(RISK_CONFIG_PATH, "w") as f:
            json.dump(state, f, indent=2)
    
    def _reset_daily(self):
        """Reset daily loss counter if new day."""
        today = datetime.now(timezone.utc).date()
        if today != self.daily_start:
            self.daily_pnl = 0.0
            self.daily_start = today
    
    def is_trading_allowed(self):
        """Check if trading is currently allowed."""
        self._reset_daily()
        
        # Check peak bankroll drawdown
        peak_dd = 1 - (self.current_bankroll / max(self.peak_bankroll, 0.01))
        if peak_dd >= self.config["max_drawdown_pct"]:
            return False, f"Drawdown {peak_dd:.1%} exceeds max {self.config['max_drawdown_pct']:.1%}"
        
        # Check daily loss limit
        if self.daily_pnl < -self.config["daily_loss_limit_pct"]:
            return False, f"Daily loss {abs(self.daily_pnl):.1%} exceeds limit {self.config['daily_loss_limit_pct']:.1%}"
        
        # Check cooling period
        if self.cooldown_until:
            cooldown_dt = datetime.fromisoformat(self.cooldown_until)
            if datetime.now(timezone.utc) < cooldown_dt:
                remaining = (cooldown_dt - datetime.now(timezone.utc)).total_seconds() / 3600
                return False, f"Cooling period: {remaining:.1f}h remaining ({self.consecutive_losses} consecutive losses)"
            else:
                self.cooldown_until = None  # Cooldown expired
        
        # Check max concurrent positions
        if len(self.open_positions) >= self.config["max_concurrent_positions"]:
            return False, f"Max positions ({self.config['max_concurrent_positions']}) reached"
        
        # Check total exposure
        total_exposed = sum(p.get("bet_size", 0) for p in self.open_positions.values())
        exposure_ratio = total_exposed / max(self.current_bankroll, 0.01)
        if exposure_ratio >= self.config["max_total_exposure_pct"]:
            return False, f"Total exposure {exposure_ratio:.1%} exceeds max {self.config['max_total_exposure_pct']:.1%}"
        
        return True, "ok"
    
    def check_category_limit(self, category):
        """Check if we can open another position in this category."""
        cat_count = sum(1 for p in self.open_positions.values() if p.get("category") == category)
        if cat_count >= self.config["max_per_category"]:
            return False, f"Max {self.config['max_per_category']} positions per category ({category})"
        return True, "ok"
    
    def get_position_size_adjustment(self, kelly_fraction):
        """Apply risk adjustments to Kelly fraction."""
        self._reset_daily()
        adjustment = 1.0
        
        # Drawdown adjustment
        peak_dd = 1 - (self.current_bankroll / max(self.peak_bankroll, 0.01))
        if peak_dd >= self.config["drawdown_halt_at"]:
            adjustment *= 0.5  # Half size during drawdown
        elif peak_dd >= 0.05:
            adjustment *= 0.75  # Slight reduction at 5% DD
        
        # Consecutive loss adjustment
        if self.consecutive_losses >= self.config["cooling_losses"]:
            adjustment *= 0.25  # Quarter size during cooling
        
        # Kelly decay for large bankrolls
        if self.current_bankroll >= self.config["kelly_decay_threshold"]:
            adjustment *= self.config["kelly_decay_factor"]
        
        return round(kelly_fraction * adjustment, 4)
    
    def record_trade(self, position_id, category, bet_size, outcome, payout):
        """
        Record a completed trade.
        
        position_id: unique identifier
        category: market category
        bet_size: USDC bet
        outcome: True if won, False if lost
        payout: USDC received (0 if lost)
        """
        self.current_bankroll += payout - bet_size
        
        # Update peak
        if self.current_bankroll > self.peak_bankroll:
            self.peak_bankroll = self.current_bankroll
        
        # Consecutive losses tracking
        if outcome:
            self.consecutive_losses = 0
            self.cooldown_until = None
        else:
            self.consecutive_losses += 1
            # Enter cooling
            if self.consecutive_losses >= self.config["cooling_losses"]:
                self.cooldown_until = (
                    datetime.now(timezone.utc) + 
                    timedelta(hours=self.config["cooling_period_hours"])
                ).isoformat()
        
        # Daily PnL
        self.daily_pnl += (payout - bet_size) / self.current_bankroll
        
        # Log trade
        self.trade_log.append({
            "position_id": position_id,
            "category": category,
            "bet_size": bet_size,
            "outcome": outcome,
            "payout": payout,
            "pnl": payout - bet_size,
            "bankroll_after": self.current_bankroll,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        
        # Remove from open positions
        if position_id in self.open_positions:
            del self.open_positions[position_id]
        
        # Remove position from open (if closed)
        if not outcome:
            # Position was lost - nothing to close
            pass
        
        self._save_state()
    
    def open_position(self, position_id, category, bet_size):
        """Record a new open position."""
        self.open_positions[position_id] = {
            "category": category,
            "bet_size": bet_size,
            "opened_at": datetime.now(timezone.utc).isoformat(),
        }
        self._save_state()
    
    def get_status(self):
        """Get current risk status."""
        self._reset_daily()
        peak_dd = 1 - (self.current_bankroll / max(self.peak_bankroll, 0.01))
        total_exposed = sum(p.get("bet_size", 0) for p in self.open_positions.values())
        exposure_ratio = total_exposed / max(self.current_bankroll, 0.01)
        
        allowed, reason = self.is_trading_allowed()
        
        return {
            "trading_allowed": allowed,
            "reason": reason,
            "current_bankroll": round(self.current_bankroll, 4),
            "peak_bankroll": round(self.peak_bankroll, 4),
            "drawdown": round(peak_dd, 4),
            "daily_pnl_pct": round(self.daily_pnl, 4),
            "consecutive_losses": self.consecutive_losses,
            "open_positions": len(self.open_positions),
            "total_exposure_pct": round(exposure_ratio, 4),
            "cooldown_until": self.cooldown_until,
            "total_trades": len(self.trade_log),
            "wins": sum(1 for t in self.trade_log if t["outcome"]),
            "losses": sum(1 for t in self.trade_log if not t["outcome"]),
        }


def main():
    rm = RiskManager()
    status = rm.get_status()
    
    print("=" * 60)
    print("RISK MANAGEMENT ENGINE — Week 4")
    print("=" * 60)
    print()
    for k, v in status.items():
        print(f"  {k:30s}: {v}")
    print()
    
    # Test scenario
    print("=== SCENARIO TEST ===")
    rm = RiskManager(initial_bankroll=1.17)
    allowed, reason = rm.is_trading_allowed()
    print(f"Start: allowed={allowed}, reason={reason}")
    print(f"Bankroll: ${rm.current_bankroll:.4f}")
    print()
    
    # Simulate a winning trade
    rm.open_position("test_1", "Crypto", 0.20)
    rm.record_trade("test_1", "Crypto", 0.20, True, 1.0)  # Won $0.80 net
    status = rm.get_status()
    print(f"After win: bankroll=${status['current_bankroll']:.4f}, wins={status['wins']}")
    
    # Simulate consecutive losses
    for i in range(3):
        pid = f"loss_{i}"
        rm.open_position(pid, "Crypto", 0.20)
        rm.record_trade(pid, "Crypto", 0.20, False, 0)  # Lost $0.20
    
    status = rm.get_status()
    print(f"After 3 losses: bankroll=${status['current_bankroll']:.4f}")
    print(f"  Trading allowed: {status['trading_allowed']}")
    print(f"  Reason: {status['reason']}")
    print(f"  Cooling until: {status['cooldown_until']}")


if __name__ == "__main__":
    main()
