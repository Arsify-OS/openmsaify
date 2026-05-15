"""
regime_engine — Polymarket Trading Engine
Part of openmsaify-trading (MIT License)
Copyright (c) 2025 OpenMSAify
"""

#!/usr/bin/env python3
"""
REGIME INTELLIGENCE ENGINE — Time-Aware Market Regime Detection

Detects the current market regime and adjusts calibration accordingly.

Regimes:
- calm: Low volatility, tight spreads, normal volume → HIGH reliability
- macro: Macro events driving prices, elevated volume/spread → MODERATE reliability
- hype: Narrative-driven, FOMO-like volume expansion → LOW reliability
- chaos: Extreme volatility, wide spreads → VERY LOW reliability
- narrative_war: Competing narratives, high discussion volume → MODERATE-LOW reliability
- thin_liquidity: Low volume, stale orderbooks → VERY LOW reliability
- whale_dominated: Concentrated whale activity, high volume → MODERATE reliability
- news_cascade: Rapid event-driven price movements → LOW reliability

Built from temporal patterns in 95K historical markets.

Usage: python3 regime_engine.py [current_regime]
       python3 regime_engine.py  # auto-detects current regime
"""

import json
import os
import sys
import warnings
from datetime import datetime, timezone, timedelta

warnings.filterwarnings("ignore")

import numpy as np
import httpx

GAMMA_URL = "https://gamma-api.polymarket.com"
CLOB_URL = "https://clob.polymarket.com"

# ============================================================
# REGIME DEFINITIONS
# ============================================================

REGIME_CONFIG = {
    "calm": {
        "description": "Low volatility, tight spreads, normal volume",
        "volume_range": (5000, 500000),
        "max_spread": 0.03,
        "price_volatility": (0.01, 0.10),
        "narrative_saturation": "low",
        "whale_density": "moderate",
        "reliability": 0.90,
        "multiplier": 1.00,
    },
    "macro": {
        "description": "Macro events driving prices, elevated volume/spread",
        "volume_range": (50000, 2000000),
        "max_spread": 0.05,
        "price_volatility": (0.10, 0.30),
        "narrative_saturation": "medium",
        "whale_density": "high",
        "reliability": 0.75,
        "multiplier": 0.85,
    },
    "hype": {
        "description": "Narrative-driven, FOMO-like volume expansion",
        "volume_range": (10000, 1000000),
        "max_spread": 0.06,
        "price_volatility": (0.05, 0.25),
        "narrative_saturation": "high",
        "whale_density": "moderate",
        "reliability": 0.60,
        "multiplier": 0.75,
    },
    "chaos": {
        "description": "Extreme volatility, wide spreads, unpredictable",
        "volume_range": (0, 5000000),
        "max_spread": 0.15,
        "price_volatility": (0.20, 1.00),
        "narrative_saturation": "very_high",
        "whale_density": "chaotic",
        "reliability": 0.40,
        "multiplier": 0.60,
    },
    "narrative_war": {
        "description": "Competing narratives, high discussion activity",
        "volume_range": (5000, 1000000),
        "max_spread": 0.05,
        "price_volatility": (0.08, 0.20),
        "narrative_saturation": "very_high",
        "whale_density": "moderate",
        "reliability": 0.55,
        "multiplier": 0.70,
    },
    "thin_liquidity": {
        "description": "Low volume, stale orderbooks, unreliable price",
        "volume_range": (0, 2000),
        "max_spread": 0.20,
        "price_volatility": (0.00, 0.50),
        "narrative_saturation": "low",
        "whale_density": "low",
        "reliability": 0.30,
        "multiplier": 0.50,
    },
    "whale_dominated": {
        "description": "Concentrated whale activity, high single-volume trades",
        "volume_range": (100000, 10000000),
        "max_spread": 0.04,
        "price_volatility": (0.02, 0.15),
        "narrative_saturation": "medium",
        "whale_density": "very_high",
        "reliability": 0.65,
        "multiplier": 0.80,
    },
    "news_cascade": {
        "description": "Rapid event-driven price cascades, temporal clustering",
        "volume_range": (20000, 5000000),
        "max_spread": 0.08,
        "price_volatility": (0.15, 0.50),
        "narrative_saturation": "very_high",
        "whale_density": "high",
        "reliability": 0.50,
        "multiplier": 0.65,
    },
}

# Historical seasonal regime patterns (from 95K temporal analysis)
SEASONAL_REGIME_BIAS = {
    1: "calm",       # January: post-holiday, settling
    2: "calm",
    3: "macro",      # March: Q1 close, spring volatility
    4: "hype",       # April: earnings season
    5: "hype",
    6: "calm",       # Summer calm
    7: "calm",
    8: "narrative_war",  # August: pre-election buildup
    9: "narrative_war",
    10: "macro",     # October: Q3 close
    11: "narrative_war",  # November: election season
    12: "hype",      # December: year-end positioning
}


class RegimeEngine:
    """
    Time-aware regime detection and calibration adjustment.
    
    Combines:
    1. Current market microstate (volume, spread, volatility)
    2. Historical seasonal patterns
    3. Temporal proximity to major events
    """
    
    def __init__(self):
        self.current_regime = None
        self.regime_history = []
        self._load_historical_regime_patterns()
    
    def _load_historical_regime_patterns(self):
        """Load regime patterns from SKP five-layer index."""
        self.historical_pattern = None
        try:
            with open("/root/polymarket/skp/skp_five_layer_rules.json") as f:
                rules = json.load(f)
            self.historical_pattern = rules.get("association", {}).get("seasonal_patterns", {})
        except:
            pass
    
    def detect_regime(self, market_data=None):
        """
        Detect current market regime from live data.
        
        market_data: list of recent markets from Gamma API
        Returns: regime_name, confidence
        """
        if market_data is None:
            market_data = self._fetch_recent_markets()
        
        if not market_data:
            return self._default_regime(), 0.5
        
        # Compute market-wide metrics
        volumes = []
        spreads = []
        price_changes = []
        neg_risk_count = 0
        total_count = len(market_data)
        
        for m in market_data:
            vol = float(m.get("volume", 0) or 0)
            sp = float(m.get("spread", 0) or 0) / 100 if m.get("spread") else None
            prices = json.loads(m.get("outcomePrices", "[]"))
            
            volumes.append(vol)
            if sp:
                spreads.append(sp)
            if prices and len(prices) >= 2:
                try:
                    price_changes.append(abs(float(prices[0]) - float(prices[1])))
                except:
                    pass
            if m.get("negRisk") or m.get("neg_risk"):
                neg_risk_count += 1
        
        avg_volume = np.mean(volumes) if volumes else 0
        median_volume = np.median(volumes) if volumes else 0
        max_volume = max(volumes) if volumes else 0
        avg_spread = np.mean(spreads) if spreads else 0.1
        avg_volatility = np.mean(price_changes) if price_changes else 0
        
        # Detect regime
        regime = self._classify_regime(avg_volume, median_volume, max_volume, 
                                        avg_spread, avg_volatility, neg_risk_count, total_count)
        
        confidence = self._compute_regime_confidence(regime, avg_volume, avg_spread)
        
        self.current_regime = regime
        self.regime_history.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "regime": regime,
            "confidence": round(confidence, 3),
            "metrics": {
                "avg_volume": round(avg_volume, 0),
                "avg_spread": round(avg_spread, 4),
                "neg_risk_ratio": round(neg_risk_count / max(total_count, 1), 3),
            }
        })
        
        # Keep last 24 hours
        if len(self.regime_history) > 288:  # every 5 min for 24h
            self.regime_history = self.regime_history[-288:]
        
        return regime, confidence
    
    def _classify_regime(self, avg_vol, med_vol, max_vol, avg_spread, avg_volatility, 
                         neg_risk_count, total):
        """Classify regime based on market-wide metrics."""
        neg_risk_ratio = neg_risk_count / max(total, 1)
        
        # Thin liquidity: most markets have very low volume
        if med_vol < 2000 and avg_vol < 5000:
            return "thin_liquidity"
        
        # Chaos: very high spread + high volatility
        if avg_spread > 0.10 and avg_volatility > 0.30:
            return "chaos"
        
        # Whale dominated: extreme max volume relative to median
        if max_vol > med_vol * 50 and avg_vol > 50000:
            return "whale_dominated"
        
        # Macro: elevated everything
        if avg_vol > 50000 and avg_spread > 0.03 and avg_volatility > 0.15:
            return "macro"
        
        # Hype: high volume but moderate spreads
        if avg_vol > 10000 and avg_spread <= 0.06 and avg_volatility <= 0.25:
            return "hype"
        
        # News cascade: moderate-high vol, moderate spread, high activity
        if avg_vol > 20000 and avg_spread > 0.04 and avg_spread <= 0.08:
            return "news_cascade"
        
        # Narrative war: high neg_risk ratio (complex markets)
        if neg_risk_ratio > 0.40:
            return "narrative_war"
        
        # Calm: default for normal conditions
        return "calm"
    
    def _compute_regime_confidence(self, regime, avg_volume, avg_spread):
        """Compute confidence in regime classification."""
        confidence = 0.70  # base
        
        if avg_volume > REGIME_CONFIG[regime]["volume_range"][0]:
            confidence += 0.10
        if avg_spread < REGIME_CONFIG[regime]["max_spread"]:
            confidence += 0.10
        if len(self.regime_history) > 5:
            # Check regime stability
            recent_regimes = [r["regime"] for r in self.regime_history[-12:]]
            if len(set(recent_regimes)) <= 2:
                confidence += 0.10
        
        return min(confidence, 0.95)
    
    def _fetch_recent_markets(self, limit=100):
        """Fetch recent markets for regime detection."""
        try:
            resp = httpx.get(
                f"{GAMMA_URL}/markets",
                params={"limit": limit, "active": "true", "closed": "false", "order": "volume", "ascending": "false"},
                timeout=15,
            )
            if resp.status_code == 200:
                return resp.json()
        except:
            pass
        return []
    
    def _default_regime(self):
        """Default regime based on seasonality."""
        month = datetime.now(timezone.utc).month
        return SEASONAL_REGIME_BIAS.get(month, "calm")
    
    def get_regime_multiplier(self, regime=None):
        """Get confidence multiplier for current regime."""
        if regime is None:
            regime = self.current_regime or self._default_regime()
        return REGIME_CONFIG.get(regime, {}).get("multiplier", 0.75)
    
    def get_regime_reliability(self, regime=None):
        """Get reliability score for current regime."""
        if regime is None:
            regime = self.current_regime or self._default_regime()
        return REGIME_CONFIG.get(regime, {}).get("reliability", 0.50)
    
    def get_regime_info(self, regime=None):
        """Get full regime information."""
        if regime is None:
            regime = self.current_regime or self._default_regime()
        config = REGIME_CONFIG.get(regime, {})
        return {
            "regime": regime,
            "description": config.get("description", ""),
            "multiplier": config.get("multiplier", 0.75),
            "reliability": config.get("reliability", 0.50),
            "narrative_saturation": config.get("narrative_saturation", ""),
        }
    
    def get_historical_regime_context(self):
        """Get historical regime patterns for the current month."""
        month = datetime.now(timezone.utc).month
        seasonal_regime = SEASONAL_REGIME_BIAS.get(month, "unknown")
        
        return {
            "current_month": month,
            "seasonal_regime": seasonal_regime,
            "historical_seasonal": SEASONAL_REGIME_BIAS,
        }


# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 60)
    print("REGIME INTELLIGENCE ENGINE")
    print("=" * 60)
    
    engine = RegimeEngine()
    
    # Auto-detect current regime
    regime, confidence = engine.detect_regime()
    info = engine.get_regime_info(regime)
    
    print(f"\nCurrent regime: {regime.upper()}")
    print(f"Description: {info['description']}")
    print(f"Multiplier: {info['multiplier']}")
    print(f"Reliability: {info['reliability']:.0%}")
    print(f"Confidence: {confidence:.0%}")
    print(f"Narrative saturation: {info['narrative_saturation']}")
    
    hist = engine.get_historical_regime_context()
    print(f"\nSeasonal context: Month {hist['current_month']} → {hist['seasonal_regime']}")
    
    # Show all regimes
    print(f"\n{'='*60}")
    print(f"ALL REGIMES")
    print(f"{'='*60}")
    for name, config in REGIME_CONFIG.items():
        active = " ← CURRENT" if name == regime else ""
        print(f"  {name:20s}: mult={config['multiplier']:.2f} rel={config['reliability']:.0%} | {config['description']}{active}")
    
    print(f"\n{engine.current_regime} detected at {datetime.now(timezone.utc).strftime('%H:%M UTC')}")


if __name__ == "__main__":
    main()
