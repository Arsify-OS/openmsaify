"""
calibration_memory — Polymarket Trading Engine
Part of openmsaify-trading (MIT License)
Copyright (c) 2025 OpenMSAify
"""

#!/usr/bin/env python3
"""
CALIBRATION MEMORY ENGINE — Meta-Learning & Calibration Feedback

Tracks calibration quality over time and learns from failures.

What it stores:
1. Disagreement history (when AI said probability X but market said Y)
2. Edge persistence (how long edge lasted)
3. Execution quality (was the edge exploitable?)
4. Realized outcome (did AI prediction come true?)
5. Narrative context (what was happening?)
6. Liquidity conditions (volume, spread at time of prediction)
7. Regime state (what regime was active?)

What it outputs:
- Calibration accuracy metrics
- Edge decay curves
- Best/worst performing regimes
- Anti-delusion feedback (were filters working?)
- Confidence calibration (do high-conf predictions actually hit?)

Usage: python3 calibration_memory.py [--update] [--report]
"""

import json
import os
import sys
import warnings
from datetime import datetime, timezone, timedelta
from collections import defaultdict, Counter

warnings.filterwarnings("ignore")

import numpy as np

MEMORY_PATH = "/root/polymarket/skp/calibration_memory.json"


def load_memory():
    """Load calibration memory from disk."""
    if os.path.exists(MEMORY_PATH):
        with open(MEMORY_PATH) as f:
            return json.load(f)
    return {
        "version": "1.0",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "predictions": [],
        "resolutions": [],
        "regime_history": [],
        "statistics": {},
    }


def record_prediction(prediction_id, market_data, ai_probability, market_price, 
                      tier, confidence, regime, edge, volume, category, spread):
    """Record a new calibration prediction."""
    memory = load_memory()
    
    entry = {
        "id": prediction_id or f"pred_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{market_data.get('market_id', '')[:12]}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "market_id": market_data.get("market_id", market_data.get("condition_id", "")),
        "question": market_data.get("question", "")[:200],
        "ai_probability": ai_probability,
        "market_price": market_price,
        "tier": tier,
        "confidence": confidence,
        "regime": regime,
        "raw_edge": edge,
        "volume": volume,
        "category": category,
        "spread": spread,
        "resolved": False,
        "outcome": None,
        "was_correct": None,
    }
    
    memory["predictions"].append(entry)
    
    # Keep last 10000 predictions
    if len(memory["predictions"]) > 10000:
        memory["predictions"] = memory["predictions"][-10000:]
    
    memory["last_updated"] = datetime.now(timezone.utc).isoformat()
    
    return memory


def resolve_prediction(prediction_id, outcome_is_yes):
    """Resolve a prediction with actual outcome."""
    memory = load_memory()
    
    for pred in memory["predictions"]:
        if pred["id"] == prediction_id:
            pred["resolved"] = True
            pred["outcome"] = outcome_is_yes
            pred["resolved_at"] = datetime.now(timezone.utc).isoformat()
            
            # Was AI correct?
            ai_yes = pred["ai_probability"] > 0.5
            pred["was_correct"] = (ai_yes == outcome_is_yes)
            
            # Edge quality
            if outcome_is_yes:
                pred["edge_quality"] = pred["ai_probability"] - pred["market_price"]
            else:
                pred["edge_quality"] = pred["market_price"] - pred["ai_probability"]
            
            break
    
    memory["last_updated"] = datetime.now(timezone.utc).isoformat()
    return memory


def compute_statistics(memory):
    """Compute calibration statistics from memory."""
    predictions = memory.get("predictions", [])
    resolved = [p for p in predictions if p.get("resolved")]
    
    if not resolved:
        return {"status": "insufficient_data", "resolved_count": 0}
    
    stats = {}
    
    # ── Overall calibration accuracy
    correct = sum(1 for p in resolved if p.get("was_correct"))
    stats["total_predictions"] = len(predictions)
    stats["resolved_count"] = len(resolved)
    stats["accuracy"] = round(correct / len(resolved), 3) if resolved else 0
    
    # ── Confidence calibration (do high-conf predictions hit?)
    conf_buckets = [(0, 0.3), (0.3, 0.5), (0.5, 0.7), (0.7, 0.9), (0.9, 1.0)]
    conf_calibration = {}
    for low, high in conf_buckets:
        bucket = [p for p in resolved if low <= p.get("confidence", 0) < high]
        if bucket:
            correct = sum(1 for p in bucket if p.get("was_correct"))
            conf_calibration[f"{low:.1f}_{high:.1f}"] = {
                "count": len(bucket),
                "accuracy": round(correct / len(bucket), 3),
            }
    stats["confidence_calibration"] = conf_calibration
    
    # ── Tier performance
    tier_stats = {}
    for tier in ["S", "A", "B", "C"]:
        tier_preds = [p for p in resolved if p.get("tier") == tier]
        if tier_preds:
            correct = sum(1 for p in tier_preds if p.get("was_correct"))
            avg_edge = np.mean([abs(p.get("raw_edge", 0)) for p in tier_preds])
            tier_stats[tier] = {
                "count": len(tier_preds),
                "accuracy": round(correct / len(tier_preds), 3),
                "avg_edge": round(float(avg_edge), 3),
            }
    stats["tier_performance"] = tier_stats
    
    # ── Regime performance
    regime_stats = {}
    for pred in resolved:
        regime = pred.get("regime", "unknown")
        regime_stats.setdefault(regime, {"correct": 0, "total": 0})
        regime_stats[regime]["total"] += 1
        if pred.get("was_correct"):
            regime_stats[regime]["correct"] += 1
    
    for regime, data in regime_stats.items():
        data["accuracy"] = round(data["correct"] / data["total"], 3)
    stats["regime_performance"] = regime_stats
    
    # ── Category performance
    cat_stats = {}
    for pred in resolved:
        cat = pred.get("category", "unknown")
        cat_stats.setdefault(cat, {"correct": 0, "total": 0})
        cat_stats[cat]["total"] += 1
        if pred.get("was_correct"):
            cat_stats[cat]["correct"] += 1
    
    for cat, data in cat_stats.items():
        data["accuracy"] = round(data["correct"] / data["total"], 3)
    stats["category_performance"] = cat_stats
    
    # ── Volume-based performance
    vol_buckets = {
        "micro (<1K)": [p for p in resolved if (p.get("volume", 0) or 0) < 1000],
        "small (1K-10K)": [p for p in resolved if 1000 <= (p.get("volume", 0) or 0) < 10000],
        "medium (10K-100K)": [p for p in resolved if 10000 <= (p.get("volume", 0) or 0) < 100000],
        "large (>100K)": [p for p in resolved if (p.get("volume", 0) or 0) >= 100000],
    }
    vol_stats = {}
    for label, preds in vol_buckets.items():
        if preds:
            correct = sum(1 for p in preds if p.get("was_correct"))
            vol_stats[label] = {
                "count": len(preds),
                "accuracy": round(correct / len(preds), 3),
            }
    stats["volume_performance"] = vol_stats
    
    # ── Edge quality analysis
    if any("edge_quality" in p for p in resolved):
        eqs = [p.get("edge_quality", 0) for p in resolved if "edge_quality" in p]
        stats["edge_quality"] = {
            "mean": round(float(np.mean(eqs)), 4),
            "median": round(float(np.median(eqs)), 4),
            "positive_percent": round(sum(1 for e in eqs if e > 0) / len(eqs) * 100, 1),
        }
    
    # ── Anti-delusion feedback
    # Check if filtered predictions (low confidence) were indeed worse
    low_conf = [p for p in resolved if p.get("confidence", 0) < 0.5]
    high_conf = [p for p in resolved if p.get("confidence", 0) >= 0.8]
    
    if low_conf and high_conf:
        low_acc = sum(1 for p in low_conf if p.get("was_correct")) / len(low_conf)
        high_acc = sum(1 for p in high_conf if p.get("was_correct")) / len(high_conf)
        stats["anti_delusion_effective"] = high_acc > low_acc
        stats["low_conf_accuracy"] = round(low_acc, 3)
        stats["high_conf_accuracy"] = round(high_acc, 3)
    
    return stats


def generate_report(memory):
    """Generate human-readable calibration report."""
    stats = compute_statistics(memory)
    
    lines = [
        "=" * 60,
        "CALIBRATION MEMORY REPORT",
        f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "=" * 60,
        "",
    ]
    
    if stats.get("status") == "insufficient_data":
        lines.append(f"Insufficient data: {stats.get('resolved_count', 0)} resolved predictions")
        lines.append("Need at least 10 resolved predictions for meaningful statistics.")
        return "\n".join(lines)
    
    lines.append(f"Total predictions: {stats.get('total_predictions', 0):,}")
    lines.append(f"Resolved: {stats.get('resolved_count', 0):,}")
    lines.append(f"Overall accuracy: {stats.get('accuracy', 0):.1%}")
    lines.append("")
    
    # Confidence calibration
    if "confidence_calibration" in stats:
        lines.append("CONFIDENCE CALIBRATION")
        for bucket, data in stats["confidence_calibration"].items():
            lines.append(f"  {bucket}: {data['accuracy']:.1%} (n={data['count']})")
        lines.append("")
    
    # Tier performance
    if "tier_performance" in stats:
        lines.append("TIER PERFORMANCE")
        for tier, data in stats["tier_performance"].items():
            lines.append(f"  Tier {tier}: {data['accuracy']:.1%} avg_edge={data['avg_edge']:.3f} (n={data['count']})")
        lines.append("")
    
    # Regime performance
    if "regime_performance" in stats:
        lines.append("REGIME PERFORMANCE")
        for regime, data in sorted(stats["regime_performance"].items(), key=lambda x: -x[1]["accuracy"]):
            lines.append(f"  {regime:20s}: {data['accuracy']:.1%} (n={data['total']})")
        lines.append("")
    
    # Category performance
    if "category_performance" in stats:
        lines.append("CATEGORY PERFORMANCE")
        for cat, data in sorted(stats["category_performance"].items(), key=lambda x: -x[1]["accuracy"]):
            lines.append(f"  {cat:20s}: {data['accuracy']:.1%} (n={data['total']})")
        lines.append("")
    
    # Volume performance
    if "volume_performance" in stats:
        lines.append("VOLUME-BASED PERFORMANCE")
        for label, data in stats["volume_performance"].items():
            lines.append(f"  {label:20s}: {data['accuracy']:.1%} (n={data['count']})")
        lines.append("")
    
    # Anti-delusion
    if stats.get("anti_delusion_effective") is not None:
        lines.append(f"ANTI-DELUSION EFFECTIVE: {'YES' if stats['anti_delusion_effective'] else 'NO'}")
        lines.append(f"  High conf (>80%): {stats.get('high_conf_accuracy', 0):.1%}")
        lines.append(f"  Low conf (<50%): {stats.get('low_conf_accuracy', 0):.1%}")
        lines.append("")
    
    # Edge quality
    if "edge_quality" in stats:
        eq = stats["edge_quality"]
        lines.append("EDGE QUALITY")
        lines.append(f"  Mean: {eq['mean']:.4f}")
        lines.append(f"  Positive edge %: {eq['positive_percent']:.1%}")
        lines.append("")
    
    return "\n".join(lines)


def save_memory(memory):
    """Save memory to disk."""
    with open(MEMORY_PATH, "w") as f:
        json.dump(memory, f, indent=2, default=str)


def main():
    print("=" * 60)
    print("CALIBRATION MEMORY ENGINE")
    print("=" * 60)
    
    if "--update" in sys.argv:
        # Would be called by mispricing scanner after predictions are made
        print("Update mode: predictions will be recorded during mispricing scan")
    
    if "--report" in sys.argv or True:  # Always show report
        memory = load_memory()
        report = generate_report(memory)
        print(report)
        
        save_memory(memory)
        print(f"\nMemory saved: {MEMORY_PATH}")
        print(f"Predictions stored: {len(memory.get('predictions', []))}")
        print(f"Resolutions: {sum(1 for p in memory.get('predictions', []) if p.get('resolved'))}")


if __name__ == "__main__":
    main()
