"""
auto_recalibration — Polymarket Trading Engine
Part of openmsaify-trading (MIT License)
Copyright (c) 2025 OpenMSAify
"""

#!/usr/bin/env python3
"""
AUTO-RECALIBRATION ENGINE — Week 3

Reads calibration memory and automatically adjusts ensemble weights
based on empirical performance, not theoretical assumptions.

What it does:
1. Reads historical prediction outcomes from calibration_memery.json
2. Computes per-signal-type, per-category, per-regime accuracy
3. Optimizes ensemble weights to maximize historical accuracy
4. Saves updated weights to SKP knowledge base
5. Generates recalibration report

Runs every 12 hours (via cron).

Usage: python3 auto_recalibration.py [--dry-run] [--report]
"""

import json
import os
import sys
from datetime import datetime, timezone, timedelta
from collections import defaultdict

import numpy as np

MEMORY_PATH = "/root/polymarket/skp/calibration_memory.json"
SKP_RULES_PATH = "/root/polymarket/skp/skp_five_layer_rules.json"
SKP_KNOWLEDGE_PATH = "/root/polymarket/skp/skp_knowledge.json"

INITIAL_WEIGHTS = {
    "historical_prior": 0.25,
    "ml_probability": 0.35,
    "category_baseline": 0.15,
    "seasonal_adjustment": 0.05,
    "spread_adjustment": 0.10,
    "cluster_adjustment": 0.10,
}

def load_memory():
    if os.path.exists(MEMORY_PATH):
        with open(MEMORY_PATH) as f:
            return json.load(f)
    return {"predictions": [], "resolutions": []}

def load_skp_knowledge():
    if os.path.exists(SKP_KNOWLEDGE_PATH):
        with open(SKP_KNOWLEDGE_PATH) as f:
            return json.load(f)
    return {}

def analyze_performance(memory):
    """Analyze past prediction performance."""
    predictions = memory.get("predictions", [])
    resolved = [p for p in predictions if p.get("resolved")]
    
    if len(resolved) < 30:  # Need minimum for statistical significance
        return {"status": "insufficient_data", "count": len(resolved), "message": f"Need at least 30 resolved predictions (currently {len(resolved)})"}
    
    # Group by tier, category, regime
    performance_by_tier = defaultdict(list)
    performance_by_category = defaultdict(list)
    performance_by_regime = defaultdict(list)
    performance_by_volume = {"micro": [], "small": [], "medium": [], "large": []}
    
    for p in resolved:
        was_correct = p.get("was_correct", False)
        edge_quality = p.get("edge_quality", 0)
        
        performance_by_tier[p.get("tier", "unknown")].append({"correct": was_correct, "edge": edge_quality})
        performance_by_category[p.get("category", "unknown")].append({"correct": was_correct, "edge": edge_quality})
        performance_by_regime[p.get("regime", "unknown")].append({"correct": was_correct, "edge": edge_quality})
        
        vol = p.get("volume", 0) or 0
        if vol < 1000:
            performance_by_volume["micro"].append({"correct": was_correct, "edge": edge_quality})
        elif vol < 10000:
            performance_by_volume["small"].append({"correct": was_correct, "edge": edge_quality})
        elif vol < 100000:
            performance_by_volume["medium"].append({"correct": was_correct, "edge": edge_quality})
        else:
            performance_by_volume["large"].append({"correct": was_correct, "edge": edge_quality})
    
    # Compute statistics
    def compute_stats(data_list):
        if not data_list:
            return {"count": 0, "accuracy": 0, "avg_edge": 0}
        correct = sum(1 for d in data_list if d["correct"])
        return {
            "count": len(data_list),
            "accuracy": correct / len(data_list),
            "avg_edge": np.mean([d["edge"] for d in data_list]),
        }
    
    stats = {
        "status": "ok",
        "sample_size": len(resolved),
        "overall_accuracy": compute_stats(resolved),
        "by_tier": {k: compute_stats(v) for k, v in performance_by_tier.items()},
        "by_category": {k: compute_stats(v) for k, v in performance_by_category.items()},
        "by_regime": {k: compute_stats(v) for k, v in performance_by_regime.items()},
        "by_volume": {k: compute_stats(v) for k, v in performance_by_volume.items()},
    }
    
    return stats

def optimize_weights(memory, initial_weights):
    """Optimize ensemble weights based on past performance."""
    stats = analyze_performance(memory)
    if stats.get("status") != "ok":
        return initial_weights, {"status": "skipped", "reason": stats.get("message")}
    
    # Simple weight optimization: boost weights for components that performed well historically
    # This is a heuristic approach, not full gradient descent
    
    new_weights = initial_weights.copy()
    adjustments = {}
    
    # Check tier performance: if S-tier accuracy < 60%, reduce ML weight (overconfident?)
    s_stats = stats.get("by_tier", {}).get("S", {})
    if s_stats.get("count", 0) > 10:
        if s_stats.get("accuracy", 0) < 0.60:
            # ML might be overconfident, reduce weight
            adjustment = -0.05
            new_weights["ml_probability"] = max(0.20, new_weights["ml_probability"] + adjustment)
            adjustments["ml_probability"] = adjustment
        else:
            adjustment = +0.05
            new_weights["ml_probability"] = min(0.50, new_weights["ml_probability"] + adjustment)
            adjustments["ml_probability"] = adjustment
    
    # Check category performance: adjust category baseline weight
    cat_stats = stats.get("by_category", {})
    if cat_stats:
        underperforming_cats = [k for k, v in cat_stats.items() if v.get("accuracy", 0) < 0.40]
        if len(underperforming_cats) > len(cat_stats) * 0.5:  # >50% categories underperforming
            adjustment = -0.05
            new_weights["category_baseline"] = max(0.05, new_weights["category_baseline"] + adjustment)
            adjustments["category_baseline"] = adjustment
    
    # Check regime performance: adjust historical prior weight if regime-aware predictions are better
    regime_stats = stats.get("by_regime", {})
    if regime_stats:
        high_perf_regimes = [k for k, v in regime_stats.items() if v.get("accuracy", 0) > 0.65]
        if high_perf_regimes:
            # Historical prior is working well, boost it
            adjustment = +0.05
            new_weights["historical_prior"] = min(0.40, new_weights["historical_prior"] + adjustment)
            adjustments["historical_prior"] = adjustment
    
    # Normalize weights to sum to 1.0
    total = sum(new_weights.values())
    for key in new_weights:
        new_weights[key] = round(new_weights[key] / total, 3)
    
    return new_weights, {
        "status": "optimized",
        "adjustments": adjustments,
        "new_total": round(sum(new_weights.values()), 3),
    }

def save_optimization(new_weights, optimization_info):
    """Save new weights to SKP knowledge."""
    try:
        # Update skp_knowledge.json
        knowledge = load_skp_knowledge()
        if "knowledge" not in knowledge:
            knowledge["knowledge"] = {}
        knowledge["knowledge"]["ensemble_weights"] = new_weights
        knowledge["last_recalibrated"] = datetime.now(timezone.utc).isoformat()
        
        with open(SKP_KNOWLEDGE_PATH, "w") as f:
            json.dump(knowledge, f, indent=2, default=str)
        
        # Update skp_five_layer_rules.json
        rules = {}
        if os.path.exists(SKP_RULES_PATH):
            with open(SKP_RULES_PATH) as f:
                rules = json.load(f)
        # Store optimization info
        rules["optimization_history"] = rules.get("optimization_history", [])
        rules["optimization_history"].append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "weights": new_weights,
            "adjustments": optimization_info.get("adjustments", {}),
            "sample_size": optimization_info.get("sample_size", 0),
        })
        # Keep only last 50 optimization runs
        if len(rules["optimization_history"]) > 50:
            rules["optimization_history"] = rules["optimization_history"][-50:]
            
        with open(SKP_RULES_PATH, "w") as f:
            json.dump(rules, f, indent=2, default=str)
            
        return True
    except Exception as e:
        print(f"Failed to save optimization: {e}")
        return False

def generate_report(stats, new_weights, opt_info):
    """Generate recalibration report."""
    lines = [
        "=" * 75,
        f"  AUTO-RECALIBRATION REPORT — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "=" * 75,
        "",
    ]
    
    if stats.get("status") != "ok":
        lines.append(f"Status: {stats.get('message')}")
        return "\n".join(lines)
    
    lines.append(f"Sample Size: {stats['sample_size']} resolved predictions")
    lines.append(f"Overall Accuracy: {stats['overall_accuracy']['accuracy']:.1%} (n={stats['overall_accuracy']['count']})")
    lines.append("")
    
    # Tier performance
    lines.append("TIER PERFORMANCE:")
    for tier, tstats in sorted(stats.get("by_tier", {}).items()):
        bar = "●" * int(tstats["count"] / 2)
        lines.append(f"  {tier:4s}: {tstats['accuracy']:.1%} {bar} (n={tstats['count']})")
    lines.append("")
    
    # Category performance (top 5)
    lines.append("CATEGORY PERFORMANCE:")
    cats = sorted(stats.get("by_category", {}).items(), key=lambda x: -x[1]["count"])[:5]
    for cat, cstats in cats:
        bar = "●" * int(cstats["count"] / 2)
        lines.append(f"  {cat:15s}: {cstats['accuracy']:.1%} {bar} (n={cstats['count']})")
    lines.append("")
    
    # Regime performance
    lines.append("REGIME PERFORMANCE:")
    for regime, rstats in sorted(stats.get("by_regime", {}).items(), key=lambda x: -x[1]["accuracy"]):
        lines.append(f"  {regime:20s}: {rstats['accuracy']:.1%} (n={rstats['count']})")
    lines.append("")
    
    # Volume performance
    lines.append("VOLUME-BASED PERFORMANCE:")
    for vol_label, vstats in stats.get("by_volume", {}).items():
        if vstats["count"] > 0:
            lines.append(f"  {vol_label:10s}: {vstats['accuracy']:.1%} (n={vstats['count']})")
    lines.append("")
    
    # Optimization results
    if opt_info.get("status") == "optimized":
        lines.append("WEIGHT OPTIMIZATION:")
        lines.append(f"  Previous → New")
        old_weights = INITIAL_WEIGHTS  # Or load from previous
        for key, new_val in new_weights.items():
            old_val = INITIAL_WEIGHTS.get(key, 0)
            change = new_val - old_val
            arrow = "↑" if change > 0 else ("↓" if change < 0 else "=")
            lines.append(f"  {key:20s}: {old_val:.3f} → {new_val:.3f} {arrow} {change:+.3f}")
        lines.append("")
        
        if opt_info.get("adjustments"):
            lines.append("ADJUSTMENTS MADE:")
            for comp, adj in opt_info["adjustments"].items():
                reason = "Boosted" if adj > 0 else "Reduced"
                lines.append(f"  {reason} {comp} by {abs(adj):.2f}")
    else:
        lines.append(f"Weight Optimization: {opt_info.get('reason', 'Skipped')}")
    lines.append("")
    
    # Recommendations
    lines.append("RECOMMENDATIONS:")
    if stats['overall_accuracy']['accuracy'] < 0.55:
        lines.append("  ⚠️ Overall accuracy below 55% → Consider increasing historical_prior weight")
    if stats['overall_accuracy']['accuracy'] > 0.70:
        lines.append("  ✅ Overall accuracy above 70% → System performing well")
    
    return "\n".join(lines)

def main():
    print("AUTO-RECALIBRATION ENGINE — Week 3")
    print("=" * 50)
    
    memory = load_memory()
    stats = analyze_performance(memory)
    new_weights, opt_info = optimize_weights(memory, INITIAL_WEIGHTS)
    
    report = generate_report(stats, new_weights, opt_info)
    print(report)
    
    if "--dry-run" in sys.argv:
        print("\n[DRY RUN] Weights would be saved but were not.")
        return
    
    if "--report" in sys.argv:
        print(f"\nReport generated. No changes made.")
        return
    
    if opt_info.get("status") == "optimized":
        success = save_optimization(new_weights, opt_info)
        if success:
            print(f"\n✅ New weights saved to {SKP_KNOWLEDGE_PATH}")
        else:
            print(f"\n❌ Failed to save weights.")

if __name__ == "__main__":
    main()
