"""
correlation_scanner — Polymarket Trading Engine
Part of openmsaify-trading (MIT License)
Copyright (c) 2025 OpenMSAify
"""

#!/usr/bin/env python3
"""
CORRELATION SCANNER v2 — Week 6B

Auto-detects cross-market mispricings WITHOUT hardcoded event groups.

Detection methods:
1. KEYWORD CLUSTERING: Find markets sharing key entities (BTC, $100k, May)
2. LOGICAL IMPLICATION: If A implies B, then P(A) should ≤ P(B)
3. TEMPORAL NESTING: "May 13" implies "May" — prices should be nested
4. PRICE RANGE CONTRADICTIONS: "BTC > $100k" vs "BTC > $120k" — second must be cheaper
5. MUTUAL EXCLUSION: Winner markets that sum != 1.0

For each detected contradiction → generates a CORRELATION signal.

Usage: python3 correlation_scanner.py [--save] [--min-score 3]
"""

import json
import os
import sys
import re
import warnings
from datetime import datetime, timezone
from collections import defaultdict

warnings.filterwarnings("ignore")

import httpx

GAMMA_URL = "https://gamma-api.polymarket.com"
OUTPUT_PATH = "/root/polymarket/skp/correlation_signals.json"


# ============================================================
# TEXT PROCESSING
# ============================================================

def tokenize(q):
    """Extract key tokens from market question."""
    text = q.lower()
    # Remove stop words, keep entities, numbers, keywords
    stop = {"the", "a", "an", "is", "are", "will", "be", "in", "on", "at", "to", 
            "of", "and", "or", "by", "for", "with", "from", "not", "that", "this",
            "before", "after", "during", "if", "than", "when"}
    tokens = set()
    for word in re.findall(r"[a-z]+\$?\$?[\d.]+%?\s*|\b[a-z]+\b", text):
        word = word.strip()
        if word not in stop and len(word) > 1:
            tokens.add(word)
    return tokens


def extract_entities(q):
    """Extract named entities and key numeric values."""
    entities = {}
    
    # Currency/price: "$100k", "$1.5M", "100,000"
    prices = re.findall(r"\$[\d,.]+[mk]?\$?", q.lower())
    prices += re.findall(r"\d{3,}[mk]?", q.lower())
    entities["prices"] = set(p.lower() for p in prices)
    
    # Dates: "May 13", "2026", "June 2026"
    dates = re.findall(r"\b(january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{1,2}", q.lower())
    dates += re.findall(r"\b\d{4}\b", q)
    entities["dates"] = set(d.lower() for d in dates)
    
    # Key entities (capitalized words, specific names)
    names = re.findall(r"\b[A-Z][a-z]+(?:\s[A-Z][a-z]+)+\b", q)
    names += re.findall(r"\b(BTC|ETH|SOL|XRP|DOGE|GTA|FIFA|NBA|NFL|MLB|LCK)\b", q)
    entities["names"] = set(n.lower() for n in names)
    
    # Comparison operators
    entities["above"] = bool(re.search(r"abov[e]|greater|more than|higher", q.lower()))
    entities["below"] = bool(re.search(r"below|less than|under|lower", q.lower()))
    entities["between"] = bool(re.search(r"between", q.lower()))
    
    return entities


# ============================================================
# DETECTION METHODS
# ============================================================

def detect_temporal_nesting(markets):
    """
    Find markets where one timeframe is nested in another.
    
    FIXED: Only match markets that share the SAME named entity.
    A date match alone is too noisy.
    """
    # Require same named entity for grouping
    groups = defaultdict(list)
    for m in markets:
        ents = extract_entities(m["question"])
        # Need at least one named entity (not just dates)
        if not ents["names"]:
            continue
        key = "|".join(sorted(ents["names"]))
        groups[key].append(m)
    
    contradictions = []
    for key, group in groups.items():
        if len(group) < 2:
            continue
        
        # Find pairs with different date specificity
        for i, m1 in enumerate(group):
            for m2 in group[i+1:]:
                e1 = extract_entities(m1["question"])
                e2 = extract_entities(m2["question"])
                
                d1_dates = e1["dates"]
                d2_dates = e2["dates"]
                
                # Skip if both or neither have dates
                has_dates1 = len(d1_dates) >= 1
                has_dates2 = len(d2_dates) >= 1
                if not (has_dates1 or has_dates2):
                    continue
                
                # Check price relationship: different timeframes, different prices
                price_diff = abs(m1["yes_price"] - m2["yes_price"])
                if price_diff < 0.20:
                    continue  # Not significant
                
                # Determine which is more specific
                d1_specific = len(d1_dates) >= 2  # day + month  
                d2_specific = len(d2_dates) >= 2
                
                # The more specific market should have extreme price relative to the less specific
                if m1["yes_price"] < 0.30 and m2["yes_price"] > 0.50 and d1_specific and not d2_specific:
                    contradictions.append({
                        "type": "TEMPORAL_NESTING",
                        "entity": key,
                        "market_1": f"{m1['question'][:80]} ({m1['yes_price']:.1%})",
                        "market_2": f"{m2['question'][:80]} ({m2['yes_price']:.1%})",
                        "price_1": m1["yes_price"],
                        "price_2": m2["yes_price"],
                        "edge": round(m2["yes_price"] - m1["yes_price"], 4),
                        "score": 4,
                        "reason": f"Specific date {m1['yes_price']:.1%} vs broad {m2['yes_price']:.1%} — anomaly",
                    })
                elif m2["yes_price"] < 0.30 and m1["yes_price"] > 0.50 and d2_specific and not d1_specific:
                    contradictions.append({
                        "type": "TEMPORAL_NESTING",
                        "entity": key,
                        "market_1": f"{m2['question'][:80]} ({m2['yes_price']:.1%})",
                        "market_2": f"{m1['question'][:80]} ({m1['yes_price']:.1%})",
                        "price_1": m2["yes_price"],
                        "price_2": m1["yes_price"],
                        "edge": round(m1["yes_price"] - m2["yes_price"], 4),
                        "score": 4,
                        "reason": f"Specific date {m2['yes_price']:.1%} vs broad {m1['yes_price']:.1%} — anomaly",
                    })
    
    return contradictions


def detect_price_range_contradictions(markets):
    """
    Find markets with overlapping price ranges that should have consistent ordering.
    
    FIXED: Only group markets that share the SAME entity name.
    """
    # Extract numeric price targets
    def get_price_target(q):
        matches = re.findall(r"\$?([\d,.]+)[mk]?", q.lower())
        if matches:
            num = matches[-1].replace(",", "")
            if "m" in q.lower():
                num += "000000"
            elif "k" in q.lower():
                num += "000"
            try:
                return float(num[:12])
            except:
                return None
        return None
    
    # Group by entity names + similar dates
    groups = defaultdict(list)
    for m in markets:
        ents = extract_entities(m["question"])
        if not ents["names"]:
            continue
        key = "|".join(sorted(ents["names"])) + "|FDV" if "fdv" in m["question"].lower() else "|".join(sorted(ents["names"]))
        price = get_price_target(m["question"])
        if price is not None:
            groups[key].append({**m, "price_target": price, "above": ents["above"], "below": ents["below"]})
    
    contradictions = []
    for key, group in groups.items():
        if len(group) < 2:
            continue
        
        # Check ABOVE markets: higher target should have lower price
        above_markets = [m for m in group if m.get("above")]
        above_markets.sort(key=lambda x: x["price_target"])
        
        for i in range(len(above_markets) - 1):
            m1 = above_markets[i]  # lower target
            m2 = above_markets[i+1]  # higher target
            
            # m2 (higher target) should be cheaper than m1
            if m2["yes_price"] >= m1["yes_price"]:
                contradictions.append({
                    "type": "PRICE_RANGE_ABOVE",
                    "entity": key,
                    "market_1": f"{m1['question'][:80]} (>${m1['price_target']:,.0f}={m1['yes_price']:.1%})",
                    "market_2": f"{m2['question'][:80]} (>${m2['price_target']:,.0f}={m2['yes_price']:.1%})",
                    "higher_target_price": m2["yes_price"],
                    "lower_target_price": m1["yes_price"],
                    "target_1": m1["price_target"],
                    "target_2": m2["price_target"],
                    "edge": round(m2["yes_price"] - m1["yes_price"], 4),
                    "score": 5,
                    "reason": f"Higher target (${m2['price_target']:,.0f}) priced >= lower target (${m1['price_target']:,.0f})",
                })
    
    return contradictions


def detect_mutual_exclusion_violations(markets):
    """
    Find groups of markets that should be mutually exclusive but don't sum to ~1.0.
    
    Auto-detects: look for markets sharing the same "winner" question pattern.
    """
    # Find candidate ME groups by keyword patterns
    me_patterns = [
        (r"win the \d{4}\s+.*(?:mayoral|presidential|championship|cup|title)", "election"),
        (r"(?:will|who) (?:win|be) the \d{4}", "winner"),
        (r"(?:winner|champion) of", "winner"),
    ]
    
    groups = defaultdict(list)
    for m in markets:
        q = m["question"].lower()
        for pattern, gtype in me_patterns:
            if re.search(pattern, q):
                # Extract entity for grouping
                entities = extract_entities(m["question"])
                key = "|".join(sorted(entities["dates"])) + "|" + "|".join(sorted(entities["names"]))
                if key:
                    groups[key].append(m)
    
    contradictions = []
    for key, group in groups.items():
        if len(group) < 2:
            continue
        
        sum_yes = sum(m["yes_price"] for m in group)
        
        # If sum is significantly off from 1.0, there's a mispricing
        if sum_yes < 0.85 or sum_yes > 1.15:
            # Find the most underpriced market in the group
            cheapest = min(group, key=lambda x: x["yes_price"])
            
            # How much is the deviation
            deviation = abs(1.0 - sum_yes)
            underpriced = []
            for m in group:
                true_prob = m["yes_price"] / max(sum_yes, 0.01)
                if m["yes_price"] < true_prob * 0.8:
                    underpriced.append({
                        "market": m["question"][:80],
                        "price": m["yes_price"],
                        "implied_true": round(true_prob, 3),
                        "discount": round((1 - m["yes_price"] / true_prob) * 100, 0),
                    })
            
            if underpriced:
                contradictions.append({
                    "type": "MUTUAL_EXCLUSION",
                    "group_size": len(group),
                    "sum_yes": round(sum_yes, 3),
                    "deviation": round(deviation, 3),
                    "underpriced": underpriced,
                    "score": 4,
                    "reason": f"Sum of YES = {sum_yes:.2f} (should be ~1.0)",
                })
    
    return contradictions


def detect_keyword_clusters(markets):
    """
    Simple keyword clustering: find markets with high token overlap
    and check for internal consistency.
    """
    # Build token similarity matrix
    indexed = []
    for m in markets:
        tokens = tokenize(m["question"])
        if len(tokens) >= 3:  # Need meaningful content
            indexed.append({"market": m, "tokens": tokens})
    
    contradictions = []
    checked = set()
    
    for i, a in enumerate(indexed):
        for j, b in enumerate(indexed[i+1:], i+1):
            pair_key = (i, j)
            if pair_key in checked:
                continue
            checked.add(pair_key)
            
            token_overlap = a["tokens"] & b["tokens"]
            overlap_ratio = len(token_overlap) / max(len(a["tokens"] | b["tokens"]), 1)
            
            # High overlap but very different prices → potential mispricing
            if overlap_ratio > 0.7:
                price_diff = abs(a["market"]["yes_price"] - b["market"]["yes_price"])
                
                if price_diff > 0.30:
                    # 30%+ price difference despite 70%+ token match
                    contradictions.append({
                        "type": "KEYWORD_SIMILARITY_PRICE_GAP",
                        "market_1": f"{a['market']['question'][:80]} ({a['market']['yes_price']:.1%})",
                        "market_2": f"{b['market']['question'][:80]} ({b['market']['yes_price']:.1%})",
                        "token_overlap": round(overlap_ratio, 2),
                        "price_diff": round(price_diff, 4),
                        "score": 3,
                        "reason": f"70%+ similar questions but {price_diff*100:.0f}pp price gap",
                    })
    
    return contradictions


# ============================================================
# MAIN
# ============================================================

def fetch_active_markets(limit=500):
    """Fetch active markets from Gamma API in pages."""
    all_markets = []
    try:
        for offset in range(0, 1000, 100):
            resp = httpx.get(
                f"{GAMMA_URL}/markets",
                params={"limit": 100, "active": "true", "closed": "false",
                        "order": "volume", "ascending": "false",
                        "offset": offset},
                timeout=15,
            )
            if resp.status_code != 200 or not resp.json():
                break
            batch = resp.json()
            all_markets.extend(batch)
            if len(all_markets) >= limit:
                break
            if len(batch) < 100:
                break
    except Exception:
        pass
    
    markets = []
    seen = set()
    for m in all_markets[:limit]:
        pid = m.get("id") or m.get("conditionId", "")
        if pid in seen:
            continue
        seen.add(pid)
        
        prices = json.loads(m.get("outcomePrices", "[0.5, 0.5]"))
        yes = float(prices[0]) if prices else 0.5
        no = float(prices[1]) if len(prices) >= 2 else (1.0 - yes)
        
        markets.append({
            "id": m.get("id"),
            "condition_id": m.get("conditionId", ""),
            "question": m.get("question", ""),
            "yes_price": yes,
            "no_price": no,
            "volume": float(m.get("volume", 0) or 0),
            "liquidity": float(m.get("liquidity", 0) or 0),
            "end_date": m.get("endDate", ""),
            "neg_risk": m.get("negRisk", False),
        })
    return markets


def run_scanner(min_score=3):
    """Run all correlation detection methods."""
    print("=" * 60)
    print("CORRELATION SCANNER v2 — Cross-Market Mispricing Detection")
    print(f"Timestamp: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 60)
    
    # Fetch markets
    markets = fetch_active_markets(300)
    if not markets:
        print("No markets fetched")
        return []
    
    # Filter out neg_risk and micro-markets
    markets = [m for m in markets if not m.get("neg_risk") and m.get("volume", 0) >= 1000]
    print(f"Analyzed {len(markets)} active markets (volume >= $1K)\n")
    
    all_contradictions = []
    
    # Method 1: Temporal nesting
    print("[1] Detecting temporal nesting...")
    c1 = detect_temporal_nesting(markets)
    all_contradictions.extend(c1)
    print(f"    Found: {len(c1)} temporal contradictions")
    
    # Method 2: Price range contradictions
    print("[2] Detecting price range contradictions...")
    c2 = detect_price_range_contradictions(markets)
    all_contradictions.extend(c2)
    print(f"    Found: {len(c2)} price contradictions")
    
    # Method 3: Mutual exclusion violations  
    print("[3] Detecting mutual exclusion violations...")
    c3 = detect_mutual_exclusion_violations(markets)
    all_contradictions.extend(c3)
    print(f"    Found: {len(c3)} mutual exclusion issues")
    
    # Method 4: Keyword cluster price gaps
    print("[4] Detecting keyword cluster price gaps...")
    c4 = detect_keyword_clusters(markets)
    all_contradictions.extend(c4)
    print(f"    Found: {len(c4)} similarity gaps")
    
    # Filter by score
    signals = [c for c in all_contradictions if c.get("score", 0) >= min_score]
    signals.sort(key=lambda x: -x.get("score", 0))
    
    print(f"\n{'='*60}")
    print(f"Total signals (score >= {min_score}): {len(signals)}")
    print(f"{'='*60}")
    
    for s in signals[:20]:
        print(f"\n⚡ [{s['type']}] Score: {s['score']}")
        print(f"  {s.get('reason', '')}")
        if "market_1" in s:
            print(f"  A: {s['market_1']}")
        if "market_2" in s:
            print(f"  B: {s['market_2']}")
        if "edge" in s:
            print(f"  Edge: {s['edge']:+.3f}")
    
    # Save signals
    if signals:
        with open(OUTPUT_PATH, "w") as f:
            json.dump({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "markets_scanned": len(markets),
                "signals": signals,
            }, f, indent=2, default=str)
        print(f"\nSaved {len(signals)} signals to {OUTPUT_PATH}")
    
    return signals


if __name__ == "__main__":
    min_score = 3
    if "--min-score" in sys.argv:
        idx = sys.argv.index("--min-score") + 1
        if idx < len(sys.argv):
            min_score = int(sys.argv[idx])
    
    run_scanner(min_score=min_score)
