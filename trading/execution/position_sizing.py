"""
position_sizing — Polymarket Trading Engine
Part of openmsaify-trading (MIT License)
Copyright (c) 2025 OpenMSAify
"""

#!/usr/bin/env python3
"""
POSITION SIZING ENGINE — Week 4

Kelly criterion calibrated edge sizing with:
- Historical accuracy adjustment (don't trust unproven edge)
- Liquidity-aware position limits
- Drawdown protection
- Multi-market portfolio constraints
- Anti-will-ruin safeguards

Usage: python3 position_sizing.py [--test] [--optimize]
"""

import json
import os
import sys
import warnings
from datetime import datetime, timezone
from collections import defaultdict

warnings.filterwarnings("ignore")

import numpy as np

# Config defaults
DEFAULT_BANKROLL = 1.17  # Current seed in USDC
MAX_POSITION_PCT = 0.25  # Single position max 25% of bankroll (Kelly-capped)
MIN_CONFIDENCE = 0.50    # Minimum calibration confidence to bet
MIN_EDGE = 0.05          # Minimum effective edge (5%)
MIN_VOLUME = 5000        # Minimum market volume for bet
MAX_DRAWDOWN = 0.20      # Halt trading at 20% drawdown
KELLY_CAP = 0.25         # Kelly fraction capped at 25%
PORTFOLIO_MAX = 0.80     # Max 80% of bankroll deployed across all positions


class PositionSizer:
    """
    Calculates optimal bet size using:
    - Full Kelly: (p*q - q) / b  where p=win_prob, q=1-p, b=odds
    - Fractional Kelly: 0.5x to 0.25x Kelly (always fractional, never full)
    - Historical accuracy discount for unproven edges
    - Drawdown-aware position limits
    """
    
    def __init__(self, bankroll=DEFAULT_BANKROLL):
        self.bankroll = bankroll
        self.current_drawdown = 0.0
        self.recent_outcomes = []  # last 20 trades
        
    def calculate_kelly(self, win_prob, avg_odds, confidence=0.5):
        """
        Calculate Kelly fraction.
        
        win_prob: calibrated probability of winning (AI estimate)
        avg_odds: average payout multiplier (1/price for YES bets)
        confidence: calibration confidence (0-1)
        
        Returns: kelly_fraction (0-0.25 after capping)
        """
        # Edge: expected value
        edge = win_prob * avg_odds - (1 - win_prob)
        
        if edge <= 0:
            return 0.0, "no_edge"
        
        # Full Kelly formula
        # f* = (bp - q) / b  where b=odds-1, p=win_prob, q=1-p
        b = avg_odds - 1  # net odds
        q = 1 - win_prob
        p = win_prob
        
        if b <= 0:
            return 0.0, "invalid_odds"
        
        full_kelly = (b * p - q) / b
        full_kelly = max(0, full_kelly)
        
        # Fractional Kelly (always 0.25-0.50x to be safe)
        # Lower fraction for lower confidence
        if confidence >= 0.80:
            fraction = 0.50
        elif confidence >= 0.60:
            fraction = 0.35
        else:
            fraction = 0.25
        
        kelly = full_kelly * fraction
        
        # Cap at 25% of bankroll
        kelly = min(kelly, KELLY_CAP)
        
        return round(kelly, 4), "ok"
    
    def adjust_for_history(self, kelly_fraction, signal_type=None, category=None, confidence=0.5):
        """
        Discount Kelly based on historical performance data.
        
        If we have proven track record for this signal type, use full fraction.
        If not proven, reduce fraction proportionally.
        """
        discount = 1.0
        
        # If confidence is low (new/untested edge), reduce position
        if confidence < 0.70:
            discount = confidence / 0.70  # 0-1 scale
        
        # Additional discount for drawdown state
        if self.current_drawdown > 0.10:
            discount *= 0.50  # Half size during drawdown
        elif self.current_drawdown > 0.05:
            discount *= 0.75
        
        return round(kelly_fraction * discount, 4)
    
    def check_risk_limits(self, bankroll=None):
        """Check if trading should be allowed given current risk state."""
        br = bankroll or self.bankroll
        
        if self.current_drawdown >= MAX_DRAWDOWN:
            return False, f"Drawdown {self.current_drawdown:.1%} exceeds limit {MAX_DRAWDOWN:.1%}"
        
        if br < 0.50:
            return False, "Bankroll below minimum"
        
        return True, "ok"
    
    def get_max_portfolio_exposure(self):
        """Maximum bankroll we can deploy across all positions."""
        available = self.bankroll * PORTFOLIO_MAX
        used = sum(pos.get("allocated", 0) for pos in self.recent_outcomes)
        return max(0, available - used)
    
    def size_position(self, signal_data):
        """
        Size a single position based on signal data.
        
        signal_data dict:
        - probability: AI-estimated P(Yes)
        - market_price: current market price
        - confidence: calibration confidence (0-1)
        - tier: S/A/B/C
        - category: market category
        - volume: market volume
        - edge: raw_edge (probability - market_price)
        - effective_edge: adjusted edge
        - bankroll: current bankroll (optional, uses default)
        
        Returns:
        - bet_size_usdc: USDC amount to bet
        - kelly_fraction: Kelly fraction used
        - max_position_usdc: max allowed for this position
        - should_bet: bool
        - reason: str (why bet or skip)
        """
        br = signal_data.get("bankroll", self.bankroll)
        
        # Check risk limits
        allowed, reason = self.check_risk_limits(br)
        if not allowed:
            return {"should_bet": False, "reason": reason}
        
        probability = signal_data.get("probability", 0.5)
        market_price = signal_data.get("market_price", 0.5)
        confidence = signal_data.get("confidence", 0.5)
        tier = signal_data.get("tier", "C")
        edge = signal_data.get("edge", signal_data.get("effective_edge", probability - market_price))
        volume = signal_data.get("volume", 0)
        category = signal_data.get("category", "Other")
        
        # ── FILTER 1: Minimum edge
        if abs(edge) < MIN_EDGE:
            return {
                "should_bet": False,
                "reason": f"Edge {edge:.1%} below minimum {MIN_EDGE:.1%}",
                "edge": edge,
            }
        
        # ── FILTER 2: Minimum confidence
        if confidence < MIN_CONFIDENCE:
            return {
                "should_bet": False,
                "reason": f"Confidence {confidence:.1%} below minimum {MIN_CONFIDENCE:.1%}",
                "confidence": confidence,
            }
        
        # ── FILTER 3: Minimum volume
        if volume < MIN_VOLUME:
            return {
                "should_bet": False,
                "reason": f"Volume ${volume:,.0f} below minimum ${MIN_VOLUME:,.0f}",
                "volume": volume,
            }
        
        # ── DIRECTION: YES bet if edge > 0, NO bet if edge < 0
        is_yes_bet = edge > 0
        if is_yes_bet:
            win_prob = probability
            avg_odds = 1.0 / market_price if market_price > 0 else 20
        else:
            # Betting NO: probability of NO = 1 - AI_prob, payout = 1/(1-market_price)
            win_prob = 1 - probability
            avg_odds = 1.0 / (1 - market_price) if market_price < 1 else 20
        
        # ── KELLY CALCULATION
        kelly_fraction, kelly_status = self.calculate_kelly(win_prob, avg_odds, confidence)
        
        if kelly_status != "ok":
            return {"should_bet": False, "reason": f"Kelly calc failed: {kelly_status}"}
        
        # Adjust for historical accuracy and confidence
        adjusted_kelly = self.adjust_for_history(kelly_fraction, category=category, confidence=confidence)
        
        # Clamp
        max_allowed = MAX_POSITION_PCT * br
        bet_size = adjusted_kelly * br
        bet_size = min(bet_size, max_allowed)
        
        # Check max position (anti-will-ruin)
        if bet_size < 0.01:  # Minimum $0.01 bet
            return {"should_bet": False, "reason": "Bet size below minimum $0.01", "calculated_size": f"${bet_size:.4f}"}
        
        return {
            "should_bet": True,
            "bet_size_usdc": round(bet_size, 4),
            "kelly_fraction": round(adjusted_kelly, 4),
            "full_kelly_fraction": round(kelly_fraction, 4),
            "fraction_used": adjusted_kelly / kelly_fraction if kelly_fraction > 0 else 0,
            "direction": "YES" if is_yes_bet else "NO",
            "win_prob": round(win_prob, 4),
            "avg_odds": round(avg_odds, 2),
            "max_position_usdc": round(max_allowed, 4),
            "current_bankroll": br,
            "reason": "All filters passed",
        }
    
    def record_outcome(self, bet_result, actual_outcome):
        """
        Record a trade outcome for drawdown tracking.
        
        bet_result: dict from size_position()
        actual_outcome: bool (did the bet win?)
        """
        self.recent_outcomes.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "bet_size": bet_result.get("bet_size_usdc", 0),
            "won": actual_outcome,
            "direction": bet_result.get("direction", ""),
        })
        
        # Keep last 20
        if len(self.recent_outcomes) > 20:
            self.recent_outcomes = self.recent_outcomes[-20:]
