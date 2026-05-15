"""
narrative_engine — Polymarket Trading Engine
Part of openmsaify-trading (MIT License)
Copyright (c) 2025 OpenMSAify
"""

#!/usr/bin/env python3
"""
NARRATIVE INTELLIGENCE ENGINE — Narrative Tracking & Alignment

Extracts, classifies, and tracks market narratives to detect:
- Narrative momentum (growing/shifting/declining)
- Narrative distortion (market price driven by narrative, not probability)
- Narrative alignment (does AI estimate align with narrative reality?)
- Multi-narrative conflict (when narratives compete)

Built from: market questions, categories, temporal clustering

Usage: python3 narrative_engine.py [detect|track|align]
"""

import json
import os
import sys
import re
import warnings
from datetime import datetime, timezone, timedelta
from collections import Counter, defaultdict

warnings.filterwarnings("ignore")

import numpy as np
import httpx

GAMMA_URL = "https://gamma-api.polymarket.com"

# ============================================================
# NARRATIVE DEFINITIONS
# ============================================================

NARRATIVE_TEMPLATES = {
    "crypto_price": {
        "keywords": ["bitcoin", "btc", "ethereum", "eth", "solana", "doge", "price", "above", "below", "hit", "dip"],
        "description": "Cryptocurrency price prediction",
        "typical_categories": ["Crypto"],
        "momentum_sensitivity": "high",
    },
    "election_politics": {
        "keywords": ["election", "candidate", "party", "win", "republican", "democrat", "seat", "primary"],
        "description": "Political election outcomes",
        "typical_categories": ["Politics"],
        "momentum_sensitivity": "medium",
    },
    "sports_outcome": {
        "keywords": ["will", "beat", "reach", "finals", "world cup", "super bowl", "nba", "nfl", "mlb", "player"],
        "description": "Sports outcomes and achievements",
        "typical_categories": ["Sports"],
        "momentum_sensitivity": "low",
    },
    "entertainment_release": {
        "keywords": ["album", "movie", "release", "before", "gta", "oscar", "grammy"],
        "description": "Entertainment events and releases",
        "typical_categories": ["Entertainment"],
        "momentum_sensitivity": "medium",
    },
    "tech_milestone": {
        "keywords": ["gpt", "ai", "llm", "release", "openai", "tech", "company", "launch"],
        "description": "Technology milestones",
        "typical_categories": ["Technology", "Tech Companies"],
        "momentum_sensitivity": "high",
    },
    "macro_economic": {
        "keywords": ["fed", "rate", "inflation", "recession", "gdp", "cpi"],
        "description": "Macroeconomic events",
        "typical_categories": ["Economy"],
        "momentum_sensitivity": "medium",
    },
    "geopolitical_event": {
        "keywords": ["war", "invasion", "sanction", "treaty", "election", "government"],
        "description": "Geopolitical events",
        "typical_categories": ["Geopolitics", "Politics"],
        "momentum_sensitivity": "high",
    },
    "climate_weather": {
        "keywords": ["temperature", "hurricane", "climate", "weather"],
        "description": "Climate and weather events",
        "typical_categories": ["Climate"],
        "momentum_sensitivity": "low",
    },
}

# ============================================================
# NARRATIVE ENGINE
# ============================================================

class NarrativeEngine:
    """
    Extract, track, and align market narratives.
    """
    
    def __init__(self):
        self.narrative_index = {}
        self._load_narrative_index()
    
    def _load_narrative_index(self):
        """Load existing narrative index if available."""
        try:
            idx_path = "/root/polymarket/skp/narrative_index.json"
            if os.path.exists(idx_path):
                with open(idx_path) as f:
                    self.narrative_index = json.load(f)
        except:
            pass
    
    def classify_narrative(self, question, category="Other"):
        """Classify a market question into a narrative template."""
        text = question.lower()
        
        best_match = None
        best_score = 0
        
        for name, template in NARRATIVE_TEMPLATES.items():
            score = 0
            for kw in template["keywords"]:
                if kw.lower() in text:
                    score += 1
            
            # Category bonus
            if category in template["typical_categories"]:
                score += 0.5
            
            if score > best_score:
                best_score = score
                best_match = name
        
        return best_match or "other"
    
    def detect_narrative_momentum(self, markets, window_hours=24):
        """
        Detect narrative momentum across active markets.
        
        Returns dominance, direction, velocity for each active narrative.
        """
        narrative_marks = defaultdict(list)
        
        for m in markets:
            question = m.get("question", "")
            category = m.get("category", "Other")
            narrative = self.classify_narrative(question, category)
            
            narrative_marks[narrative].append({
                "id": m.get("id"),
                "question": question[:100],
                "price": float(json.loads(m.get("outcomePrices", "[0.5, 0.5]"))[0]) if m.get("outcomePrices") else 0.5,
                "volume": float(m.get("volume", 0) or 0),
                "category": category,
            })
        
        momentum = {}
        for narrative, marks in narrative_marks.items():
            if not marks:
                continue
            
            avg_price = np.mean([m["price"] for m in marks])
            total_volume = sum(m["volume"] for m in marks)
            
            # Price skew: how much do marks lean Yes vs No?
            yes_marks = sum(1 for m in marks if m["price"] > 0.5)
            skew = (yes_marks / len(marks)) - 0.5  # -0.5 to +0.5
            
            # Velocity: how diverse are the prices?
            price_std = np.std([m["price"] for m in marks])
            velocity = "stable" if price_std < 0.1 else ("moderate" if price_std < 0.25 else "chaotic")
            
            momentum[narrative] = {
                "count": len(marks),
                "avg_yes_price": round(float(avg_price), 3),
                "total_volume": round(total_volume, 0),
                "dominance": round(len(marks) / max(len(markets), 1), 3),
                "skew": round(float(skew), 3),
                "velocity": velocity,
                "price_std": round(float(price_std), 3),
            }
        
        return momentum
    
    def detect_narrative_distortion(self, market_data, ai_probability):
        """
        Detect if market price is driven by narrative distortion.
        
        Returns distortion_score and explanation.
        """
        question = market_data.get("question", "")
        market_price = market_data.get("market_probability", 0.5)
        narrative = self.classify_narrative(question, market_data.get("category", ""))
        template = NARRATIVE_TEMPLATES.get(narrative, {})
        
        distortion_score = 0.0
        reasons = []
        
        # Check for narrative-driven pricing patterns
        if template.get("momentum_sensitivity") == "high":
            # High-sensitivity narratives tend to overshoot
            if market_price > 0.80 and ai_probability < 0.50:
                distortion_score += 0.4
                reasons.append("narrative overshoot detected")
            elif market_price < 0.20 and ai_probability > 0.50:
                distortion_score += 0.3
                reasons.append("narrative undershoot detected")
        
        if template.get("momentum_sensitivity") == "medium":
            if abs(market_price - ai_probability) > 0.20:
                distortion_score += 0.2
                reasons.append("narrative drift")
        
        # Volume-to-narrative check: high volume + extreme price = narrative-driven
        volume = market_data.get("volume", 0)
        if volume > 100000 and (market_price > 0.85 or market_price < 0.15):
            distortion_score += 0.15
            reasons.append("high-volume narrative pricing")
        
        return {
            "distortion_score": round(min(distortion_score, 1.0), 3),
            "narrative": narrative,
            "reasons": reasons,
            "narrative_sensitive": template.get("momentum_sensitivity", "low"),
        }
    
    def detect_multi_narrative_conflict(self, markets):
        """
        Detect when multiple narratives compete in the same market cluster.
        """
        from sklearn.cluster import KMeans
        import numpy as np
        
        if len(markets) < 10:
            return {"has_conflict": False, "narratives": {}}
        
        narratives = []
        for m in markets[:50]:  # Sample for performance
            cat = m.get("category", "Other")
            narrative = self.classify_narrative(m.get("question", ""), cat)
            narratives.append(narrative)
        
        narrative_counts = Counter(narratives)
        total = sum(narrative_counts.values())
        
        # Conflict: multiple narratives with significant representation
        dominant_count = narrative_counts.most_common(1)[0][1] if narrative_counts else 0
        concentration = dominant_count / max(total, 1)
        
        has_conflict = concentration < 0.60 and len(narrative_counts) >= 3
        
        return {
            "has_conflict": has_conflict,
            "concentration": round(float(concentration), 3),
            "narrative_distribution": dict(narrative_counts),
            "dominant_narrative": narrative_counts.most_common(1)[0][0] if narrative_counts else "none",
        }
    
    def get_narrative_alignment(self, question, category, ai_probability, market_price):
        """
        Get narrative alignment score: how well does AI agree with market given narrative context?
        """
        narrative = self.classify_narrative(question, category)
        template = NARRATIVE_TEMPLATES.get(narrative, {})
        
        edge = ai_probability - market_price
        
        alignment = 1.0 - min(abs(edge) / 0.5, 1.0)  # 1.0 = perfect alignment, 0.0 = total disagreement
        
        sensitivity_bonus = 0
        if template.get("momentum_sensitivity") == "high" and abs(edge) > 0.20:
            sensitivity_bonus = -0.2  # Reduce alignment for high-sensitivity narratives
        
        return {
            "narrative": narrative,
            "alignment_score": round(max(0, alignment + sensitivity_bonus), 3),
            "edge": round(float(edge), 4),
            "narrative_sensitive": template.get("momentum_sensitivity", "low"),
        }


# ============================================================
# MAIN
# ============================================================

def main():
    engine = NarrativeEngine()
    
    print("=" * 60)
    print("NARRATIVE INTELLIGENCE ENGINE")
    print("=" * 60)
    
    # Fetch live markets
    try:
        resp = httpx.get(
            f"{GAMMA_URL}/markets",
            params={"limit": 100, "active": "true", "closed": "false", "order": "volume", "ascending": "false"},
            timeout=15,
        )
        if resp.status_code == 200:
            markets = resp.json()
        else:
            markets = []
    except:
        markets = []
    
    if not markets:
        print("No markets fetched")
        return
    
    # 1. Narrative detection
    print(f"\n[1] Narrative Classification — {len(markets)} markets")
    narrative_counts = Counter()
    for m in markets:
        q = m.get("question", "")
        cat = "Other"
        narrative = engine.classify_narrative(q, cat)
        narrative_counts[narrative] += 1
    
    for narrative, count in narrative_counts.most_common(10):
        template = NARRATIVE_TEMPLATES.get(narrative, {})
        desc = template.get("description", f"Narrative: {narrative}")
        sensitivity = template.get("momentum_sensitivity", "unknown")
        print(f"  {narrative:25s}: {count:3} markets | {desc} | sensitivity: {sensitivity}")
    
    # 2. Narrative momentum
    print(f"\n[2] Narrative Momentum")
    momentum = engine.detect_narrative_momentum(markets)
    for narrative, mom in sorted(momentum.items(), key=lambda x: -x[1]["dominance"]):
        print(f"  {narrative:25s}: dominance={mom['dominance']:.1%} skew={mom['skew']:+.3f} vol=${mom['total_volume']:,.0f} velocity={mom['velocity']}")
    
    # 3. Multi-narrative conflict
    print(f"\n[3] Multi-Narrative Conflict")
    conflict = engine.detect_multi_narrative_conflict(markets)
    print(f"  Conflict detected: {'YES' if conflict['has_conflict'] else 'NO'}")
    print(f"  Concentration: {conflict['concentration']:.3f}")
    print(f"  Dominant: {conflict['dominant_narrative']}")
    
    # 4. Narrative alignment on sample market
    if markets:
        sample = markets[0]
        prices = json.loads(sample.get("outcomePrices", "[0.5, 0.5]"))
        market_price = float(prices[0])
        question = sample.get("question", "")
        
        alignment = engine.get_narrative_alignment(question, "Other", 0.50, market_price)
        print(f"\n[4] Sample Narrative Alignment")
        print(f"  Market: {question[:60]}...")
        print(f"  Narrative: {alignment['narrative']}")
        print(f"  Alignment: {alignment['alignment_score']:.3f}")
        print(f"  Edge: {alignment['edge']:+.3f}")
    
    # Save narrative index
    idx_path = "/root/polymarket/skp/narrative_index.json"
    engine_index = {
        "templates": {k: {"keywords": v["keywords"], "description": v["description"], "momentum_sensitivity": v["momentum_sensitivity"]} 
                     for k, v in NARRATIVE_TEMPLATES.items()},
        "last_detected": {n: c for n, c in narrative_counts.most_common(10)},
        "momentum": {k: v for k, v in momentum.items()},
    }
    with open(idx_path, "w") as f:
        json.dump(engine_index, f, indent=2)
    print(f"\nNarrative index saved to {idx_path}")


if __name__ == "__main__":
    main()
