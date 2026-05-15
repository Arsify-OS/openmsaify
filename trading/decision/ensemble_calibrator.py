"""
ensemble_calibrator — Polymarket Trading Engine
Part of openmsaify-trading (MIT License)
Copyright (c) 2025 OpenMSAify
"""

#!/usr/bin/env python3
"""
ENSEMBLE INTELLIGENCE ENGINE — Probability Calibration Layer v2.0

SKP ALGORITHM INTEGRATED: Uses five-layer SKP knowledge base:
1. Historical priors (95K resolved markets)
2. ML model probability (Gradient Boosting)
3. Category baselines with volume adjustment
4. Seasonal bias patterns
5. Cluster profiling + anti-delusion filters

Data → Information → Knowledge → Algorithm

Output: final_probability, effective_edge, calibration_confidence
"""

import json
import os
import pickle
import re
import math
import sys
import warnings
from datetime import datetime, timezone

warnings.filterwarnings("ignore")

import numpy as np

# Load dependencies
sys.path.insert(0, "/root/polymarket")
import historical_prior as hp
import regime_engine as re_engine
import narrative_engine as ne_engine
import calibration_memory as cm
import anti_delusion_filter as adf_engine

# Lazy-loaded engines
_regime_engine = None
_narrative_engine = None
_anti_delusion_filter = None

# SKP knowledge paths
SKP_KNOWLEDGE_PATH = "/root/polymarket/skp/skp_knowledge.json"
SKP_RULES_PATH = "/root/polymarket/skp/skp_five_layer_rules.json"

MODEL_PATH = "/root/polymarket/historical_data/models/gradient_boosting_model.pkl"
DB_PATH = "/root/polymarket/historical_data/polymarket_index.db"

# ============================================================
# CONFIGURATION
# ============================================================
ENSEMBLE_WEIGHTS = {
    "historical_prior": 0.25,      # 95K historical base
    "ml_probability": 0.35,        # Gradient Boosting
    "category_baseline": 0.15,     # Category win rate (volume-adjusted)
    "seasonal_adjustment": 0.05,   # Seasonal patterns
    "spread_adjustment": 0.10,     # Spread quality
    "cluster_adjustment": 0.10,    # Cluster profiling
}

# Liquidity thresholds
MIN_EFFECTIVE_VOLUME = 500        # Below this = fake edge territory
HIGH_VOLUME_THRESHOLD = 50000     # Above this = efficient market
SPREAD_QUALITY_GOOD = 0.02        # < 2% = good liquidity

# Regime weights
REGIME_MULTIPLIERS = {
    "calm": 1.0,
    "macro": 0.85,
    "hype": 0.75,
    "chaos": 0.60,
    "narrative_war": 0.70,
    "thin_liquidity": 0.50,
    "whale_dominated": 0.80,
    "news_cascade": 0.65,
}


class EnsembleCalibrator:
    """
    Ensemble Intelligence Engine.
    
    NOT a prediction model.
    A calibration layer that detects when market probability is likely wrong.
    """

    def __init__(self):
        self.ml_model = None
        self.feature_names = None
        self.historical_priors = hp.load_priors()
        self._load_ml_model()
        self._load_skp_knowledge()
        self._init_week2_engines()
    
    def _init_week2_engines(self):
        """Initialize Week 2+3 engines: regime, narrative, calibration memory, anti-delusion."""
        global _regime_engine, _narrative_engine, _anti_delusion_filter
        if _regime_engine is None:
            _regime_engine = re_engine.RegimeEngine()
            _regime_engine.current_regime = _regime_engine._default_regime()
        if _narrative_engine is None:
            _narrative_engine = ne_engine.NarrativeEngine()
        if _anti_delusion_filter is None:
            _anti_delusion_filter = adf_engine.AntiDelusionFilter()
        self.regime_engine = _regime_engine
        self.narrative_engine = _narrative_engine
        self.calibration_memory = cm.load_memory
        self.anti_delusion_filter = _anti_delusion_filter

    def _load_skp_knowledge(self):
        """Load five-layer SKP knowledge base."""
        self.skp_knowledge = None
        try:
            if os.path.exists(SKP_KNOWLEDGE_PATH):
                with open(SKP_KNOWLEDGE_PATH) as f:
                    data = json.load(f)
                self.skp_knowledge = data.get("knowledge", {})
        except:
            pass
    
    def _get_category_baseline_kb(self, category):
        """Get category baseline from SKP knowledge (volume-adjusted)."""
        if not self.skp_knowledge:
            return None
        cat_data = self.skp_knowledge.get("category_baselines", {}).get(category, {})
        if not cat_data:
            return None
        return cat_data.get("base_win_rate", 0.328), cat_data.get("low_volume_win_rate", 0.328), cat_data.get("high_volume_win_rate", 0.328)
    
    def _get_seasonal_bias(self, month):
        """Get seasonal bias from SKP knowledge."""
        if not self.skp_knowledge:
            return 0.0
        seasonal = self.skp_knowledge.get("seasonal_bias", {}).get(str(month), {})
        return seasonal.get("bias", 0.0)
    
    def _get_cluster_profile(self, category, volume, is_neg_risk):
        """Approximate cluster profile from features."""
        if not self.skp_knowledge:
            return 0.328
        clusters = self.skp_knowledge.get("cluster_profiles", {})
        # Approximate best matching cluster
        if is_neg_risk:
            return clusters.get("1", {}).get("win_rate", 0.15)
        if category == "Crypto" and volume > 50000:
            return clusters.get("6", {}).get("win_rate", 0.49)
        if category == "Sports":
            return clusters.get("4", {}).get("win_rate", 0.51)
        return 0.328
    
    def _apply_anti_delusion_v2(self, probability, volume, spread, is_neg_risk):
        """Apply anti-delusion filters from SKP knowledge."""
        if not self.skp_knowledge:
            return probability, []
        
        anti = self.skp_knowledge.get("anti_delusion", {})
        min_vol = anti.get("min_volume_for_real_edge", 500)
        max_spread = anti.get("max_spread_for_reliable_price", 0.10)
        
        warnings = []
        penalties = []
        
        if volume < min_vol:
            penalty = 0.5
            warnings.append("low_volume")
            penalties.append(("low_volume", penalty))
        
        if spread is not None and spread > max_spread:
            penalty = 0.3
            warnings.append("high_spread")
            penalties.append(("high_spread", penalty))
        
        if is_neg_risk:
            penalty = 0.7
            warnings.append("neg_risk")
            penalties.append(("neg_risk", penalty))
        
        for reason, penalty in penalties:
            probability *= (1 - penalty)
        
        return probability, warnings

    def _load_ml_model(self):
        """Load trained ML model."""
        if os.path.exists(MODEL_PATH):
            with open(MODEL_PATH, "rb") as f:
                model_data = pickle.load(f)
            self.ml_model = model_data["model"]
            self.feature_names = model_data["feature_names"]
        else:
            self.ml_model = None
            self.feature_names = None

    def _get_historical_prior_prob(self, signal_type, category):
        """Get historical base probability from 95K data."""
        priors = self.historical_priors

        # Signal type prior
        signal_prior = priors.get(signal_type, {})
        signal_wr = signal_prior.get("win_rate", 0.328)  # overall baseline
        signal_weight = min(signal_prior.get("sample_size", 0) / 50000, 1.0)

        # Category prior
        cat_key = f"CATEGORY_{category.upper()}"
        cat_prior = priors.get(cat_key, {})
        cat_wr = cat_prior.get("win_rate", 0.328)
        cat_weight = min(cat_prior.get("sample_size", 0) / 10000, 1.0)

        # Weighted combination
        if signal_weight > 0.2 and cat_weight > 0.2:
            historical_prob = signal_wr * 0.6 + cat_wr * 0.4
        elif signal_weight > 0.2:
            historical_prob = signal_wr
        elif cat_weight > 0.2:
            historical_prob = cat_wr
        else:
            historical_prob = 0.328  # overall baseline

        return historical_prob

    def _get_ml_probability(self, features):
        """Get ML model probability for a market."""
        if self.ml_model is None or self.feature_names is None:
            return None

        try:
            # Build feature vector in correct order
            feature_vec = []
            for col in self.feature_names:
                val = features.get(col, 0)
                if val is None or (isinstance(val, float) and math.isnan(val)):
                    val = 0
                feature_vec.append(val)

            X = np.array([feature_vec], dtype=np.float32)
            proba = self.ml_model.predict_proba(X)[0][1]  # P(Yes)

            return float(proba)
        except Exception as e:
            return None

    def _compute_liquidity_modifier(self, volume, spread, market_age_days=None):
        """
        Compute liquidity multiplier.
        
        Low liquidity = fake edge risk = heavy penalty.
        High liquidity = efficient market = edge harder to find.
        
        Returns multiplier (0.0 to 1.5).
        """
        if volume < MIN_EFFECTIVE_VOLUME:
            # Micro-market: severe penalty
            return 0.25
        elif volume < 2000:
            # Small market: moderate penalty
            return 0.5 + 0.25 * (volume / 2000)
        elif volume < HIGH_VOLUME_THRESHOLD:
            # Medium: normal range
            return 1.0
        else:
            # Very high volume: efficient market, slight penalty
            # Edge still possible but harder
            return 0.9 - 0.05 * min((volume - HIGH_VOLUME_THRESHOLD) / 500000, 1)

    def _compute_spread_quality(self, spread):
        """
        Spread tightness indicator.
        
        Tight spread = good liquidity quality = reliable price
        Wide spread = poor liquidity = unreliable price
        """
        if spread is None or spread <= 0:
            return 0.7  # unknown, assume moderate
        elif spread <= SPREAD_QUALITY_GOOD:
            return 1.0  # tight = good
        elif spread <= 0.05:
            return 0.85
        elif spread <= 0.10:
            return 0.70
        else:
            return 0.50  # very wide = unreliable

    def _compute_market_freshness(self, market_age_days=None, last_trade_age_hours=None):
        """
        Market freshness indicator.
        
        Active recently = reliable price
        Stale/dead = unreliable price
        """
        if market_age_days is None and last_trade_age_hours is None:
            return 0.8  # unknown, assume moderate

        if last_trade_age_hours is not None:
            if last_trade_age_hours < 1:
                return 1.0  # very fresh
            elif last_trade_age_hours < 24:
                return 0.85
            elif last_trade_age_hours < 168:  # 1 week
                return 0.70
            else:
                return 0.50  # stale

        if market_age_days is not None:
            if market_age_days < 1:
                return 0.95  # brand new, uncertain
            elif market_age_days < 7:
                return 0.90
            elif market_age_days < 30:
                return 0.80
            else:
                return 0.65  # old market, settled expectations

        return 0.8

    def _detect_regime(self, market_features=None):
        """
        Detect current market regime based on volume/spread patterns.
        
        Regimes affect how reliable edges are.
        """
        # Simple regime detection based on market characteristics
        # In production, this would use broader market data
        volume = market_features.get("volume", 0) if market_features else 0
        spread = market_features.get("spread", 0) if market_features else 0

        if volume > 100000 and spread <= 0.02:
            return "calm"
        elif volume > 50000 and spread > 0.03:
            return "macro"
        elif volume < 1000:
            return "thin_liquidity"
        elif spread > 0.10:
            return "chaos"
        elif volume > 200000:
            return "whale_dominated"
        else:
            return "hype"

    def get_regime_multiplier(self, regime):
        return REGIME_MULTIPLIERS.get(regime, 0.75)

    def compute_market_efficiency(self, volume, spread, num_outcomes):
        """
        Market efficiency score (0.0 to 1.0).
        
        High efficiency = market is hard to beat
        Low efficiency = possible opportunity OR fake edge
        
        Based on:
        - Spread tightness
        - Volume
        - Number of outcomes (binary vs multi-outcome)
        """
        efficiency = 0.0

        # Volume component (0-0.4)
        vol_score = min(volume / 100000, 1.0) * 0.4
        efficiency += vol_score

        # Spread component (0-0.3)
        if spread <= 0.02:
            efficiency += 0.3
        elif spread <= 0.05:
            efficiency += 0.2
        elif spread <= 0.10:
            efficiency += 0.1

        # Simplicity component (0-0.3)
        if num_outcomes == 2:
            efficiency += 0.3  # Binary = more efficient
        elif num_outcomes <= 5:
            efficiency += 0.2
        else:
            efficiency += 0.1  # Multi-outcome = less efficient

        return min(efficiency, 1.0)

    def calibrate(
        self,
        market_price_yes,
        question="",
        category="",
        volume=0,
        spread=None,
        market_age_days=None,
        last_trade_age_hours=None,
        text_features=None,
        signal_type="LOW_PRICE",
    ):
        """
        Main calibration method — SKP Algorithm v2.0 unified ensemble.

        Six-layer weighted ensemble:
        1. Historical prior (25%)
        2. ML prediction (35%)
        3. Category baseline (15%)
        4. Seasonal adjustment (5%)
        5. Spread adjustment (10%)
        6. Cluster adjustment (10%)
        
        Plus: Anti-delusion filter (multiplicative penalty)

        Returns: final_probability, raw_edge, effective_edge, calibration_confidence, etc.
        """
        # Default category
        if not category:
            category = hp.derive_category(question) if question else "Other"

        # Extract month from question if available
        month = 0
        month_names = {
            "january":1,"february":2,"march":3,"april":4,"may":5,"june":6,
            "july":7,"august":8,"september":9,"october":10,"november":11,"december":12,
            "jan":1,"feb":2,"mar":3,"apr":4,"jun":6,"jul":7,"aug":8,"sep":9,"oct":10,"nov":11,"dec":12,
        }
        q_lower = question.lower()
        for name, num in month_names.items():
            if f" {name} " in q_lower or f" {name}," in q_lower or q_lower.endswith(f" {name}"):
                month = num
                break
        if month == 0:
            month = datetime.now(timezone.utc).month

        is_neg_risk = False  # Would need market data to know

        # ── WEEK 2: Regime Detection
        if self.regime_engine:
            regime = self.regime_engine.current_regime or self.regime_engine._default_regime()
            regime_mult = self.regime_engine.get_regime_multiplier(regime)
        else:
            regime = "unknown"
            regime_mult = 0.75  # default fallback

        # ── WEEK 2: Narrative Distortion
        narrative_distortion = None
        if self.narrative_engine:
            narrative_distortion = self.narrative_engine.detect_narrative_distortion(
                {"question": question, "market_probability": market_price_yes, "volume": volume, "category": category},
                0.50  # placeholder, will update after ensemble
            )

        # ── Component 1: Historical Prior (0.25)
        historical_prob = self._get_historical_prior_prob(signal_type, category)

        # ── Component 2: ML Model Probability (0.35)
        ml_prob = None
        if text_features and self.ml_model:
            ml_prob = self._get_ml_probability(text_features)
        if ml_prob is None:
            ml_prob = historical_prob

        # ── Component 3: Category Baseline (0.15) — SKP knowledge
        kb_baselines = self._get_category_baseline_kb(category)
        if kb_baselines:
            cat_vol_wr, cat_base_wr, cat_high_wr = kb_baselines
            # Volume-adjusted interpolation
            if volume <= 1000:
                cat_prob = cat_vol_wr
            elif volume >= 100000:
                cat_prob = cat_high_wr
            else:
                t = min((volume - 1000) / (100000 - 1000), 1.0)
                cat_prob = cat_vol_wr + t * (cat_high_wr - cat_vol_wr)
        else:
            # Fallback to old method
            cat_key = f"CATEGORY_{category.upper()}"
            cat_prior = self.historical_priors.get(cat_key, {})
            cat_prob = cat_prior.get("win_rate", 0.328)

        # ── Component 4: Seasonal Adjustment (0.05)
        seasonal_bias = self._get_seasonal_bias(month)
        seasonal_prob = 0.328 + seasonal_bias

        # ── Component 5: Spread Adjustment (0.10)
        if spread is not None and spread > 0:
            spread_mult = self._compute_spread_quality(spread)
            spread_prob = 0.328 * spread_mult
        else:
            spread_prob = 0.328

        # ── Component 6: Cluster Adjustment (0.10)
        cluster_prob = self._get_cluster_profile(category, volume, is_neg_risk)

        # ── Ensemble — SKP v2.0 weights
        final_probability = (
            ENSEMBLE_WEIGHTS.get("historical_prior", 0.25) * historical_prob
            + ENSEMBLE_WEIGHTS.get("ml_probability", 0.35) * ml_prob
            + ENSEMBLE_WEIGHTS.get("category_baseline", 0.15) * cat_prob
            + ENSEMBLE_WEIGHTS.get("seasonal_adjustment", 0.05) * seasonal_prob
            + ENSEMBLE_WEIGHTS.get("spread_adjustment", 0.10) * spread_prob
            + ENSEMBLE_WEIGHTS.get("cluster_adjustment", 0.10) * cluster_prob
        )

        # ── ANTI-DELUSION FILTER (multiplicative)
        final_probability, warnings = self._apply_anti_delusion_v2(
            final_probability, volume, spread, is_neg_risk
        )

        # Clamp
        final_probability = max(0.01, min(0.99, final_probability))

        # ── WEEK 3: Anti-Delusion Filter
        adf_result = None
        if self.anti_delusion_filter:
            adf_result = self.anti_delusion_filter.apply({
                "probability": final_probability,
                "market_price": market_price_yes,
                "volume": volume,
                "spread": spread or 0,
                "is_neg_risk": is_neg_risk,
                "narrative_sensitivity": narrative_distortion.get("narrative_sensitive", "low") if narrative_distortion else "low",
                "hours_to_close": None,  # Would need end_date to compute
                "edge": final_probability - market_price_yes,
            })
            if adf_result and adf_result["penalties_applied"]:
                final_probability = adf_result["filtered_probability"]
                warnings.extend([f"{p['pattern']}: {', '.join(p['reasons'])}" for p in adf_result["penalties_applied"]])

        # ── Edge Calculations
        raw_edge = final_probability - market_price_yes

        # ── Quality Modifiers
        liquidity_mod = self._compute_liquidity_modifier(volume, spread, market_age_days)
        spread_quality = self._compute_spread_quality(spread)
        freshness = self._compute_market_freshness(market_age_days, last_trade_age_hours)

        # ── Regime Detection (from Week 2 engine)
        # regime already detected above

        # ── Effective Edge
        effective_edge = raw_edge * liquidity_mod * spread_quality * freshness * regime_mult

        # ── Calibration Confidence
        confidence_score = 0.0
        if self.ml_model:
            confidence_score += 0.30
        if self.skp_knowledge:
            confidence_score += 0.10
        hist_prior = self.historical_priors.get(signal_type, {})
        if hist_prior.get("sample_size", 0) > 1000:
            confidence_score += 0.25
        if volume > MIN_EFFECTIVE_VOLUME:
            confidence_score += 0.20
        if spread and spread <= SPREAD_QUALITY_GOOD:
            confidence_score += 0.10
        if freshness >= 0.8:
            confidence_score += 0.05
        if len(warnings) == 0:
            confidence_score += 0.05
        calibration_confidence = min(confidence_score, 1.0)

        # ── Market Efficiency
        num_outcomes = 2
        market_efficiency = self.compute_market_efficiency(volume, spread, num_outcomes)

        return {
            "final_probability": round(float(final_probability), 4),
            "historical_prob": round(float(historical_prob), 4),
            "ml_prob": round(float(ml_prob), 4) if ml_prob else None,
            "category_prob": round(float(cat_prob), 4),
            "seasonal_prob": round(float(seasonal_prob), 4),
            "spread_prob": round(float(spread_prob), 4),
            "cluster_prob": round(float(cluster_prob), 4),
            "market_probability": round(float(market_price_yes), 4),
            "raw_edge": round(float(raw_edge), 4),
            "effective_edge": round(float(effective_edge), 4),
            "liquidity_modifier": round(float(liquidity_mod), 3),
            "spread_quality": round(float(spread_quality), 3),
            "market_freshness": round(float(freshness), 3),
            "regime": regime,
            "regime_multiplier": round(float(regime_mult), 3),
            "calibration_confidence": round(float(calibration_confidence), 3),
            "market_efficiency": round(float(market_efficiency), 3),
            "warnings": warnings,
            "version": "skp_v2_week3",
            "narrative_distortion": narrative_distortion,
            "anti_delusion": adf_result,
        }


def mispricing_tier(result):
    """
    Classify mispricing into tiers.
    
    Tier S - Highest confidence executable edge
    Tier A - Good edge, moderate confidence  
    Tier B - Speculative, low confidence
    Tier C - Likely noise
    """
    edge = abs(result.get("raw_edge", 0))
    eff_edge = abs(result.get("effective_edge", 0))
    confidence = result.get("calibration_confidence", 0)
    volume = result.get("volume", 0)
    efficiency = result.get("market_efficiency", 0)

    score = 0

    # Edge strength (0-40 points)
    if eff_edge >= 0.20:
        score += 40
    elif eff_edge >= 0.10:
        score += 30
    elif eff_edge >= 0.05:
        score += 15
    elif eff_edge >= 0.02:
        score += 5

    # Confidence (0-30 points)
    score += int(confidence * 30)

    # Liquidity (0-20 points)
    if volume >= 50000:
        score += 20
    elif volume >= 5000:
        score += 15
    elif volume >= 1000:
        score += 10
    elif volume >= 500:
        score += 5

    # Efficiency bonus (0-10 points)
    # Medium efficiency is sweet spot: not too efficient, not too noisy
    if 0.3 <= efficiency <= 0.7:
        score += 10
    elif 0.2 <= efficiency <= 0.8:
        score += 5

    if score >= 75:
        return "S", score
    elif score >= 55:
        return "A", score
    elif score >= 35:
        return "B", score
    else:
        return "C", score


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    # Test with a sample market
    calibrator = EnsembleCalibrator()
    print("EnsembleCalibrator loaded successfully")
    print(f"ML Model: {'loaded' if calibrator.ml_model else 'not loaded'}")
    print(f"Features: {len(calibrator.feature_names) if calibrator.feature_names else 0}")
    print(f"Historical priors: {len(calibrator.historical_priors)} categories")
