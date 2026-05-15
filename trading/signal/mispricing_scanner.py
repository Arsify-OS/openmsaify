"""
mispricing_scanner — Polymarket Trading Engine
Part of openmsaify-trading (MIT License)
Copyright (c) 2025 OpenMSAify
"""

#!/usr/bin/env python3
"""
MISPRICING SCANNER v2.0 — Dedicated 6h Cron Job (Week 2 Integration)

Scans active Polymarket markets for probabilistic disagreement.
Classifies into tiers (S/A/B/C) based on edge quality.
Saves results to Supabase + calibration memory + delivers to Telegram.

Integrates:
- SKP Algorithm v2.0 (ensemble_calibrator)
- Regime Intelligence (regime_engine)
- Calibration Memory (calibration_memory)
- Narrative Intelligence (narrative_engine)
"""

import httpx
import json
import os
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, "/root/polymarket")
from ensemble_calibrator import EnsembleCalibrator, mispricing_tier
import historical_prior as hp
import calibration_memory as cm

# Supabase config
SUPABASE_URL = "https://dklsuxeqwzuroiikosqn.supabase.co"
SUPABASE_KEY = "sb_publishable_GwMAEA4xdQ7I5q0kCNtF7Q_tGsjTHXc"
GAMMA_URL = "https://gamma-api.polymarket.com"
HEADERS = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}", "Content-Type": "application/json"}


def fetch_all_active_markets():
    """Fetch all currently active markets from Gamma API."""
    all_markets = []
    for params in [
        {"limit": 200, "active": "true", "closed": "false", "order": "volume", "ascending": "false"},
        {"limit": 200, "active": "true", "closed": "false", "offset": "200"},
    ]:
        try:
            resp = httpx.get(f"{GAMMA_URL}/markets", params=params, timeout=15)
            if resp.status_code == 200 and resp.json():
                all_markets.extend(resp.json())
        except:
            pass
    return all_markets


def scan_mispriced(min_tier="B", save_to_supabase=True):
    """Full mispricing scan with Week 2 integrations."""
    tier_thresholds = {"S": 75, "A": 55, "B": 35, "C": 0}
    min_score = tier_thresholds.get(min_tier, 35)

    print("=" * 60)
    print("MISPRICING SCANNER v2.0 — Market Calibration Intelligence")
    print(f"Timestamp: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"Min tier: {min_tier} (score >= {min_score})")
    print("=" * 60)

    markets = fetch_all_active_markets()
    print(f"Fetched {len(markets)} active markets")

    if not markets:
        print("No markets found")
        return []

    calibrator = EnsembleCalibrator()
    print(f"EnsembleCalibrator v2.0 loaded: ML={'yes' if calibrator.ml_model else 'no'}, SKP={'yes' if calibrator.skp_knowledge else 'no'}, Regime={'yes' if calibrator.regime_engine else 'no'}, Narrative={'yes' if calibrator.narrative_engine else 'no'}")

    results = []
    tier_counts = {"S": 0, "A": 0, "B": 0, "C": 0}
    predictions_recorded = 0

    for i, m in enumerate(markets):
        try:
            prices = json.loads(m.get("outcomePrices", "[0.5, 0.5]"))
            yes_price = float(prices[0]) if prices else 0.5
            volume = float(m.get("volume", 0) or 0)
            spread = float(m.get("spread", 0) or 0) / 100 if m.get("spread") else None
            question = m.get("question", "")
            category = hp.derive_category(question)
            neg_risk = m.get("negRisk", False)

            # Skip neg_risk markets
            if neg_risk:
                continue

            # Skip micro-markets
            if volume < 500:
                continue

            # Run ensemble calibration (includes regime + narrative from Week 2)
            cal = calibrator.calibrate(
                market_price_yes=yes_price,
                question=question,
                category=category,
                volume=volume,
                spread=spread,
                signal_type="LOW_PRICE",
            )

            # Add market metadata
            cal["market_id"] = m.get("id")
            cal["condition_id"] = m.get("conditionId", "")
            cal["question"] = question[:200]
            cal["category"] = category
            cal["volume"] = volume
            cal["liquidity"] = float(m.get("liquidityNum", m.get("liquidity", 0) or 0))
            cal["end_date"] = m.get("endDate", "")[:10]
            cal["neg_risk"] = neg_risk

            # Classify tier
            tier, score = mispricing_tier(cal)
            cal["tier"] = tier
            cal["mispricing_score"] = score
            tier_counts[tier] = tier_counts.get(tier, 0) + 1

            # Record to calibration memory
            try:
                mem = cm.load_memory()
                cm.record_prediction(
                    prediction_id=f"mispr_{m.get('id', '')[:12]}_{int(datetime.now().timestamp())}",
                    market_data={
                        "market_id": str(m.get("id", "")),
                        "condition_id": str(m.get("conditionId", "")),
                        "question": question,
                    },
                    ai_probability=cal.get("final_probability", 0.5),
                    market_price=yes_price,
                    tier=tier,
                    confidence=cal.get("calibration_confidence", 0),
                    regime=cal.get("regime", "unknown"),
                    edge=cal.get("raw_edge", 0),
                    volume=volume,
                    category=category,
                    spread=spread,
                )
                cm.save_memory(mem)
                predictions_recorded += 1
            except:
                pass

            if score >= min_score:
                results.append(cal)

        except Exception as e:
            continue

    # Sort: Tier S first, then score descending
    tier_order = {"S": 0, "A": 1, "B": 2, "C": 3}
    results.sort(key=lambda x: (tier_order.get(x["tier"], 9), -x.get("mispricing_score", 0)))

    # ── Report
    print(f"\n{'='*60}")
    print(f"RESULTS BY TIER")
    print(f"{'='*60}")
    for t in ["S", "A", "B", "C"]:
        count = tier_counts.get(t, 0)
        print(f"  Tier {t}: {count} markets")

    print(f"\nTotal markets scanned: {len(markets)}")
    print(f"Markets >= Tier {min_tier}: {len(results)}")
    print(f"Predictions recorded in calibration memory: {predictions_recorded}")

    if results:
        print(f"\n{'='*60}")
        print(f"TOP MISPRICED MARKETS")
        print(f"{'='*60}")
        
        for r in results[:20]:
            tier = r["tier"]
            tier_icon = {"S": "💎", "A": "⭐", "B": "🔶", "C": "🔸"}.get(tier, "•")
            direction = "UNDervalued" if r["raw_edge"] > 0 else "OVERvalued"
            q = r["question"][:65]
            regime = r.get("regime", "")
            narrative = r.get("narrative_distortion", {}).get("narrative", "") if isinstance(r.get("narrative_distortion"), dict) else ""
            print(f"{tier_icon} [{tier}] {q}")
            print(f"  Market: {r['market_probability']:.1%} | AI: {r['final_probability']:.1%} | {direction} edge: {r['raw_edge']:+.1%}")
            print(f"  Eff edge: {r['effective_edge']:+.3f} | Conf: {r['calibration_confidence']:.2f} | Vol: ${r['volume']:,.0f}")
            print(f"  Regime: {regime} | Narrative: {narrative} | Efficiency: {r['market_efficiency']:.2f} | Category: {r['category']}")
            print()

    # ── Save to Supabase (limited to 50)
    if save_to_supabase and results:
        saved_count = 0
        for r in results[:50]:
            msg = json.dumps({
                "question": r.get("question", ""),
                "tier": r.get("tier", "B"),
                "raw_edge": r.get("raw_edge", 0),
                "effective_edge": r.get("effective_edge", 0),
                "market_prob": r.get("market_probability", 0),
                "ai_prob": r.get("final_probability", 0),
                "category": r.get("category", ""),
                "volume": r.get("volume", 0),
                "regime": r.get("regime", ""),
                "calibration_confidence": r.get("calibration_confidence", 0),
                "mispricing_score": r.get("mispricing_score", 0),
            })
            try:
                httpx.post(
                    f"{SUPABASE_URL}/rest/v1/market_alerts",
                    headers=HEADERS,
                    json={
                        "polymarket_id": str(r.get("condition_id", r.get("market_id", ""))),
                        "alert_type": "MISPRICING",
                        "threshold": r.get("raw_edge", 0),
                        "current_value": r.get("effective_edge", 0),
                        "previous_value": 0,
                        "message": msg,
                        "acknowledged": False,
                    },
                    timeout=10,
                )
                saved_count += 1
            except:
                pass
        print(f"Saved {saved_count} mispricings to Supabase market_alerts")

    # ── Save to local file
    output_path = "/root/polymarket/historical_data/mispricing_results.json"
    with open(output_path, "w") as f:
        json.dump({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "total_scanned": len(markets),
            "tier_counts": tier_counts,
            "min_tier": min_tier,
            "results": results[:100],
        }, f, indent=2, default=str)

    print(f"Saved results to {output_path}")

    # ── Telegram alert format
    if results:
        s_count = tier_counts.get("S", 0)
        a_count = tier_counts.get("A", 0)
        
        lines = [
            "🎯 MISPRICING SCAN v2.0",
            f"📅 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
            "",
            f"Scanned: {len(markets)} active markets",
            f"Tier S: {s_count} | Tier A: {a_count} | Tier B: {tier_counts.get('B', 0)}",
            "",
        ]
        
        top = results[:5]
        for r in top:
            tier = r["tier"]
            tier_icon = {"S": "💎", "A": "⭐"}.get(tier, "•")
            direction = "↗️ BUY" if r["raw_edge"] > 0 else "↘️ AVOID"
            q = r["question"][:50]
            lines.append(f"{tier_icon} [{tier}] {direction}")
            lines.append(f"  {q}...")
            lines.append(f"  Market {r['market_probability']:.1%} → AI {r['final_probability']:.1%} | Edge: {r['raw_edge']:+.1%}")
            lines.append(f"  Eff: {r['effective_edge']:+.3f} | Conf: {r['calibration_confidence']:.0%} | ${r['volume']:,.0f}")
            lines.append(f"  Regime: {r.get('regime', 'unknown')} | {r['category']}")
            lines.append("")
        
        lines.append("🤖 Ensemble Calibrator v2.0 | 95K prior + ML + regime + narrative")
        alert = "\n".join(lines)
        
        print(f"\n___ALERT___")
        print(alert)

    return results


def main():
    min_tier = "B"
    if "--min-tier" in sys.argv:
        idx = sys.argv.index("--min-tier") + 1
        if idx < len(sys.argv):
            min_tier = sys.argv[idx].upper()

    scan_mispriced(min_tier=min_tier)


if __name__ == "__main__":
    main()
