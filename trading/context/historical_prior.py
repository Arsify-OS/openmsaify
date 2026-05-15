"""
historical_prior — Polymarket Trading Engine
Part of openmsaify-trading (MIT License)
Copyright (c) 2025 OpenMSAify
"""

#!/usr/bin/env python3
"""
Historical Prior Engine — Bayesian calibration from 95K resolved markets.

Provides:
1. Category derivation from question/slug
2. Historical confidence scores per signal type
3. Neg risk penalty
4. High spread bonus
5. Scoring with historical prior
"""

import json
import os

HIST_FILE = "/root/polymarket/skp/historical_training_results.json"

# Lazy-loaded cache
_priors = None

def load_priors():
    global _priors
    if _priors is None:
        try:
            with open(HIST_FILE) as f:
                data = json.load(f)
            _priors = data.get("calibrated_skills", {})
        except:
            _priors = {}
    return _priors

CATEGORY_RULES = [
    (["bitcoin", "btc", "ethereum", "eth", "crypto", "solana", "doge", "xrp", "defi", "token", "web3"], "Crypto"),
    (["nfl", "nba", "mlb", "nhl", "soccer", "football", "basketball", "baseball", "hockey", "tennis", "golf", "mma", "ufc", "premier", "championship", "fifa", "world cup", "olympic", "matchup", "game "], "Sports"),
    (["trump", "biden", "harris", "bush", "clinton", "obama", "election", "vote", "president", "senate", "congress", "governor", "referendum", "brexit", "politics", "republican", "democrat"], "Politics"),
    (["climate", "temperature", "weather", "hurricane", "earthquake", "flood", "wildfire", "sea level"], "Climate"),
    (["ai ", "llm", "gpt-", "claude ", "openai", "robot", "machine learning"], "Technology"),
    (["russia", "ukraine", "nato", "sanction", "invasion", "taiwan", "north korea", "iran", "israel", "gaza", "middle east"], "Geopolitics"),
    (["twitter", "x.com", "facebook", "meta ", "google", "apple ", "amazon", "tesla", "microsoft", "elon musk", "zuckerberg"], "Tech Companies"),
    (["movie", "album", "song", "celebrity", "oscar", "grammy", "music", "entertainment", "netflix", "disney", "marvel", "superhero"], "Entertainment"),
    (["fed ", "interest rate", "inflation", "recession", "cpi ", "gdp ", "economy", "treasury", "bond ", "s&p", "nasdaq", "dow jones"], "Economy"),
    (["court", "supreme court", "judge", "verdict", "guilty", "prison", "sentence", "indictment", "lawyer"], "Legal"),
    (["covid", "coronavirus", "vaccine", "pandemic", "omicron", "health", "hospital"], "Health"),
]


def derive_category(question, slug=""):
    """Derive market category from question/slug keywords."""
    text = f"{question} {slug}".lower()
    for keywords, cat in CATEGORY_RULES:
        if any(kw in text for kw in keywords):
            return cat
    return "Other"


def score_with_prior(signal_type, question="", slug="", neg_risk=False, volume=0, spread=None):
    """Score a signal using historical prior + market features.

    Returns dict with:
    - score: 0-10 composite score
    - confidence: HIGH/MEDIUM/LOW
    - category: derived category
    - prior_weighted: True if historical data was used
    """
    priors = load_priors()
    base_score = 5.0
    prior_weighted = False

    # 1. Apply historical signal-type prior
    if signal_type in priors:
        cal = priors[signal_type]
        base_score = cal.get("confidence_score", 5.0)
        prior_weighted = True

    # 2. Category boost/drag
    if question:
        cat = derive_category(question, slug)
        cat_key = f"CATEGORY_{cat.upper()}"
        if cat_key in priors:
            cat_cal = priors[cat_key]
            cat_score = cat_cal.get("confidence_score", 5.0)
            # Weighted: 70% signal type, 30% category
            base_score = base_score * 0.7 + cat_score * 0.3

    # 3. Neg risk penalty
    if neg_risk:
        nr_cal = priors.get("NEG_RISK", {})
        penalty = 5.0 - nr_cal.get("confidence_score", 4.8)
        base_score = max(0, base_score - penalty * 1.5)

    # 4. High spread bonus (44.9% Yes = best signal)
    if spread is not None and spread > 0.05:
        hs_cal = priors.get("HIGH_SPREAD", {})
        bonus = hs_cal.get("confidence_score", 6.7) - 5.0
        base_score = min(10, base_score + bonus * 0.3)

    # 5. Volume factor (high volume = efficient = slight drag)
    if volume > 300000:
        vs_cal = priors.get("VOLUME_SPIKE", {})
        if vs_cal.get("confidence_score", 5.0) < 6.0:
            base_score = max(0, base_score - 0.5)

    # Clamp
    score = round(min(max(base_score, 0), 10), 1)

    # Confidence level
    hist_cal = priors.get(signal_type, {})
    ci = hist_cal.get("ci_95_lower", 0)
    n = hist_cal.get("sample_size", 0)
    if ci > 0.3 and n >= 5000:
        confidence = "HIGH"
    elif ci > 0.2 and n >= 1000:
        confidence = "MEDIUM"
    else:
        confidence = "LOW"

    return {
        "score": score,
        "confidence": confidence,
        "prior_weighted": prior_weighted,
        "category": derive_category(question, slug) if question else "Unknown",
    }


def should_skip_neg_risk(m):
    """Check if market should be skipped due to neg_risk flag."""
    if m.get("negRisk") is True or m.get("neg_risk") is True:
        return True
    # Also check if grouped (multi-outcome) based on question patterns
    q = m.get("question", "").lower()
    multi_indicators = ["between", "exact number", "range", "or more", "or less",
                       "greater than", "less than", "how many", "number of"]
    # Only skip if explicitly neg_risk flagged, not all multi-outcome
    # (some multi-outcome markets are interesting)
    return False


def get_category_preference():
    """Return ordered list of preferred categories by historical win rate."""
    priors = load_priors()
    cats = []
    for key, cal in priors.items():
        if key.startswith("CATEGORY_"):
            cats.append({
                "name": key.replace("CATEGORY_", ""),
                "score": cal.get("confidence_score", 5.0),
                "win_rate": cal.get("win_rate", 0.5),
                "sample_size": cal.get("sample_size", 0),
            })
    cats.sort(key=lambda x: -x["score"])
    return cats
