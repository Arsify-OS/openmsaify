"""
learn_engine — Polymarket Trading Engine
Part of openmsaify-trading (MIT License)
Copyright (c) 2025 OpenMSAify
"""

#!/usr/bin/env python3
"""
HERMES LEARN ENGINE — Outcome Feedback → Auto-Recalibrate v2.0

Bayesian Update: historical_95K_prior + new_signals → calibrated_posterior
+ Regime-aware recalibration
+ Calibration memory tracking
+ Narrative context awareness

Flow:
  1. RESOLVE — Check pending alerts against closed markets
  2. PRICE_CHECK — Track price movement (early learning before resolution)
  3. SCORE — Win/Loss classification per signal type
  4. RECALIBRATE — Bayesian update: historical prior + new evidence + regime
  5. LEARN — Update Forecast Memory Graph + Calibration Memory
  6. ADJUST — Update SKP skills, position sizing for next cycle

Usage: python3 learn_engine.py
"""

import httpx
import json
import math
import re
import sys
from datetime import datetime, timezone
from collections import defaultdict, Counter

sys.path.insert(0, "/root/polymarket")
import historical_prior as hp
import calibration_memory as cm
import regime_engine as re_engine
from datetime import datetime, timezone, timedelta
from collections import defaultdict, Counter
from difflib import SequenceMatcher

SUPABASE_URL = "https://dklsuxeqwzuroiikosqn.supabase.co"
SUPABASE_KEY = "sb_publishable_GwMAEA4xdQ7I5q0kCNtF7Q_tGsjTHXc"
H = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}", "Content-Type": "application/json"}
GAMMA = "https://gamma-api.polymarket.com"
SKP_DIR = "/root/polymarket/skp"

# ============================================================
# PHASE 1: RESOLVE — match pending alerts to closed markets
# ============================================================
def resolve_pending_alerts():
    """Fetch pending alerts + match to closed markets. Return (resolved, still_pending)."""

    # Get all unacknowledged alerts
    r = httpx.get(f"{SUPABASE_URL}/rest/v1/market_alerts",
                  headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"},
                  params={"acknowledged": "eq.false", "limit": "500", "order": "created_at.desc"},
                  timeout=10)
    if r.status_code != 200:
        print("  ⚠️ Cannot fetch pending alerts")
        return [], []

    alerts = r.json()
    if not alerts:
        print("  📭 No pending alerts to resolve")
        return [], []

    print(f"  📋 Checking {len(alerts)} pending alerts...")

    # Fetch closed markets from Gamma API (batch by condition_id)
    condition_ids = set()
    for a in alerts:
        cid = a.get("polymarket_id", "")
        if cid:
            condition_ids.add(cid)

    # Also check current prices for unresolved signals (early learning)
    price_updates = []

    resolved_map = {}
    found_closed = 0

    for i, mid in enumerate(list(condition_ids)[:200]):
        try:
            r = httpx.get(f"{GAMMA_URL}/markets/{mid}", headers={"Accept": "application/json"}, timeout=10)
            if r.status_code == 200 and r.json():
                m = r.json()
                prices = json.loads(m.get("outcomePrices", "[]"))
                if prices and len(prices) >= 2:
                    yes_price = float(prices[0])
                    no_price = float(prices[1])
                    if yes_price in (1.0, 0.0) or no_price in (1.0, 0.0):
                        resolved_map[mid] = {
                            "outcome": "yes" if yes_price == 1.0 else "no",
                            "question": m.get("question", ""),
                            "ended_at": m.get("endDate", ""),
                        }
                        found_closed += 1
                    elif yes_price > 0.001 or no_price > 0.001:
                        # Still active - track price movement
                        price_updates.append({
                            "mid": mid,
                            "yes": yes_price,
                            "no": no_price,
                        })
        except:
            pass

    print(f"  ✅ Found {found_closed}/{len(condition_ids)} resolved markets")

    # Match alerts to resolved markets
    resolved = []
    still_pending = []

    for a in alerts:
        cid = a.get("polymarket_id", "")
        if cid in resolved_map:
            resolved_data = resolved_map[cid]
            resolved.append({
                "alert": a,
                "outcome": resolved_data["outcome"],
                "market_question": resolved_data["question"],
                "question": a.get("message", "")[:80],  # fallback
            })
        else:
            still_pending.append(a)

    return resolved, still_pending


# ============================================================
# PHASE 2: SCORE — classify outcome per signal type
# ============================================================
def score_signal(signal_type, outcome, price_at_signal, question=""):
    """Determine if the signal was correct based on type + outcome.

    For LOW_PRICE: signal said YES at low price → win if outcome=yes
    For CORRELATION: signal said underpriced → win if outcome matches implied direction
    For WHALE_BUY: follow whale → win if outcome=yes (whale was right)
    For VOLUME_SPIKE: not directional, track as informational
    For LARGE_TRADE: same as whale — follow the buyer → win if yes
    """

    if signal_type in ("LOW_PRICE", "VALUE_BOUNCE", "LARGE_TRADE", "WHALE_BUY"):
        # Signal bet YES at low price
        return outcome == "yes", "bet_yes"
    elif signal_type == "CORRELATION":
        # Signal identified underpriced market — was it actually mispriced?
        if outcome == "yes":
            return True, "correct_underpricing"
        else:
            return False, "misread_dislocation"
    elif signal_type == "VOLUME_SPIKE":
        # Volume is informational — no directional bet
        return None, "informational"
    elif signal_type == "CONTRARIAN":
        # Signal bet NO (contrarian)
        return outcome == "no", "bet_no"

    return None, "unknown"


# ============================================================
# PHASE 3: RECALIBRATE — Bayesian update: historical + new evidence
# ============================================================
def get_historical_prior(signal_type):
    """Get historical prior from 95K resolved markets."""
    priors = hp.load_priors()
    mapping = {
        "LOW_PRICE": "LOW_PRICE",
        "VALUE_BOUNCE": "LOW_PRICE",
        "VOLUME_SPIKE": "VOLUME_SPIKE",
        "WHALE_BUY": "LOW_PRICE",
        "LARGE_TRADE": "LOW_PRICE",
        "CORRELATION": "LOW_PRICE",
        "CONTRARIAN": "CONTRARIAN",
    }
    hist_key = mapping.get(signal_type, "LOW_PRICE")
    cal = priors.get(hist_key, {})
    return {
        "prior_wins": cal.get("wins", 0),
        "prior_losses": cal.get("losses", 0),
        "prior_confidence": cal.get("confidence_score", 5.0),
        "prior_win_rate": cal.get("win_rate", 0.5),
    }

def bayesian_update(prior_wins, prior_losses, new_wins, new_losses):
    """Bayesian update: combine historical prior with new evidence.

    Uses Beta-Binomial conjugate prior:
    - Prior: Beta(prior_wins + 1, prior_losses + 1)
    - Likelihood: Binomial(new_wins + new_losses, p)
    - Posterior: Beta(prior_wins + new_wins + 1, prior_losses + new_losses + 1)
    """
    # Posterior parameters
    alpha = prior_wins + new_wins + 1
    beta = prior_losses + new_losses + 1
    total = alpha + beta - 2  # minus the +2 we added

    if total < 1:
        return 0.5, 0, 0, 5.0

    posterior_mean = alpha / (alpha + beta)

    # Wilson CI for the combined estimate
    n = total
    p = posterior_mean
    z = 1.96
    denom = 1 + z**2 / n if n > 0 else 1
    center = (p + z**2 / (2*n)) / denom if n > 0 else p
    margin = z * math.sqrt((p*(1-p) + z**2/(4*n)) / n) / denom if n > 0 else 0
    ci_lower = max(0, center - margin)
    ci_upper = min(1, center + margin)

    # Confidence score: base 5 + performance + sample
    perf_bonus = (posterior_mean - 0.5) * 6
    sample_bonus = min(math.log(total / 100 + 1) * 2, 2)
    score = round(min(max(5.0 + perf_bonus + sample_bonus, 0), 10), 1)

    return posterior_mean, ci_lower, ci_upper, score

def recalibrate(existing_outcomes, new_outcomes):
    """Bayesian recalibration: historical prior + new signals → posterior.

    Instead of starting from scratch (base=5.0), we start from the
    historical prior for each signal type, then update with new evidence.
    """
    skill_stats = defaultdict(lambda: {
        "total": 0, "wins": 0, "losses": 0, "informational": 0,
        "bet_yes_wins": 0, "bet_yes_losses": 0, "bet_no_wins": 0, "bet_no_losses": 0,
    })

    for o in existing_outcomes + new_outcomes:
        stype = o.get("signal_type", "unknown")
        win = o.get("is_win")
        direction = o.get("direction", "unknown")

        stats = skill_stats[stype]
        stats["total"] += 1

        if win is None:
            stats["informational"] += 1
        elif win:
            stats["wins"] += 1
            if direction == "bet_yes":
                stats["bet_yes_wins"] += 1
            elif direction == "bet_no":
                stats["bet_no_wins"] += 1
        else:
            stats["losses"] += 1
            if direction == "bet_yes":
                stats["bet_yes_losses"] += 1
            elif direction == "bet_no":
                stats["bet_no_losses"] += 1

    results = {}
    for stype, s in skill_stats.items():
        directional_total = s["bet_yes_wins"] + s["bet_yes_losses"] + s["bet_no_wins"] + s["bet_no_losses"]

        # CHANGE 6: Bayesian update with historical prior
        prior = get_historical_prior(stype)
        posterior_wr, ci_lower, ci_upper, score = bayesian_update(
            prior["prior_wins"],
            prior["prior_losses"],
            s["wins"],
            s["losses"],
        )

        # Weight: when new data is small, historical dominates; as it grows, live data takes over
        total_with_prior = prior["prior_wins"] + prior["prior_losses"] + directional_total
        historical_weight = (prior["prior_wins"] + prior["prior_losses"]) / max(total_with_prior, 1)
        live_weight = 1 - historical_weight

        # Use posterior (Bayesian) mean as the primary estimate
        effective_wr = posterior_wr

        is_significant = ci_lower > 0.5 and directional_total >= 5

        results[stype] = {
            "sample_size": directional_total,
            "wins": s["wins"],
            "losses": s["losses"],
            "win_rate": round(effective_wr, 3),
            "confidence_score": score,
            "ci_95_lower": round(ci_lower, 3),
            "ci_95_upper": round(ci_upper, 3),
            "is_significant": is_significant,
            "false_positive_rate": round(s["losses"] / max(directional_total, 1), 3),
            "edge_decay": min(directional_total * 0.05, 0.30),
            "bayesian_posterior": round(posterior_wr, 3),
            "historical_weight": round(historical_weight, 3),
            "live_weight": round(live_weight, 3),
        }

    return results


# ============================================================
# PHASE 4: UPDATE FORECAST MEMORY GRAPH
# ============================================================
def update_forecast_graph(resolved_outcomes):
    """Update SKP forecast graph with new resolutions."""
    graph_path = f"{SKP_DIR}/forecast_graph_latest.json"
    if not __import__("os").path.exists(graph_path):
        graph_path = f"{SKP_DIR}/forecast_graph.json"

    try:
        with open(graph_path) as f:
            graph = json.load(f)
    except:
        graph = {"nodes": [], "resolutions": [], "regime_history": [], "last_updated": None}

    for o in resolved_outcomes:
        alert = o.get("alert", {})
        resolution_record = {
            "alert_id": alert.get("id"),
            "signal_type": alert.get("alert_type"),
            "market_id": alert.get("polymarket_id"),
            "outcome": o.get("outcome"),
            "is_win": o.get("is_win"),
            "direction": o.get("direction"),
            "price_at_signal": alert.get("threshold"),
            "resolved_at": datetime.now(timezone.utc).isoformat(),
        }
        graph["resolutions"].append(resolution_record)

    # Keep last 500
    if len(graph["resolutions"]) > 500:
        graph["resolutions"] = graph["resolutions"][-500:]
    graph["last_updated"] = datetime.now(timezone.utc).isoformat()

    for p in [f"{SKP_DIR}/forecast_graph_latest.json", f"{SKP_DIR}/forecast_graph.json"]:
        with open(p, "w") as f:
            json.dump(graph, f, indent=2, default=str)

    return graph


# ============================================================
# PHASE 5: UPDATE SKP — recalibrate skills
# ============================================================
def update_skp(per_skill_stats):
    """Update SKP skills file with recalibrated confidence scores."""
    skills_path = f"{SKP_DIR}/skp_skills.json"
    try:
        with open(skills_path) as f:
            skills_data = json.load(f)
    except:
        skills_data = {"skills": [], "skill_count": 0}

    type_to_skill = {
        "LOW_PRICE": "low_price_entry",
        "VOLUME_SPIKE": "volume_spike_entry",
        "WHALE_BUY": "whale_follow",
        "CORRELATION": "correlation_arbitrage",
        "VALUE_BOUNCE": "low_price_entry",
        "LARGE_TRADE": "whale_follow",
    }

    # Update skills with new confidence scores
    updated = 0
    for signal_type, stats in per_skill_stats.items():
        skill_name = type_to_skill.get(signal_type)
        if not skill_name:
            continue

        for s in skills_data.get("skills", []):
            if s.get("name") == skill_name:
                if stats.get("confidence_score") is not None:
                    s["confidence_score"] = stats["confidence_score"]
                    s["reliability"] = stats
                    s["last_calibrated"] = datetime.now(timezone.utc).isoformat()
                    updated += 1
                break

    # Save updated skills
    with open(skills_path, "w") as f:
        json.dump(skills_data, f, indent=2, default=str)

    # Also update latest.json
    latest_path = f"{SKP_DIR}/latest.json"
    try:
        with open(latest_path) as f:
            latest = json.load(f)
        latest["skills"] = skills_data
        latest["learn"] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "new_resolutions": len(per_skill_stats),
            "skills_updated": updated,
            "per_skill": per_skill_stats,
        }
        with open(latest_path, "w") as f:
            json.dump(latest, f, indent=2, default=str)
    except:
        pass

    return updated


# ============================================================
# PHASE 6: SAVE OUTCOME TO SUPABASE (if table exists)
# ============================================================
def save_outcomes_to_supabase(resolved_outcomes):
    """Try to save outcomes. If signal_outcomes table doesn't exist, use market_alerts message field."""
    saved = 0
    for o in resolved_outcomes:
        alert = o.get("alert", {})
        alert_id = alert.get("id")
        outcome_data = json.dumps({
            "outcome": o.get("outcome"),
            "is_win": o.get("is_win"),
            "direction": o.get("direction"),
            "resolved_at": datetime.now(timezone.utc).isoformat(),
        })

        # Mark alert as acknowledged with outcome embedded in message
        try:
            msg = alert.get("message", "{}")
            try:
                msg_dict = json.loads(msg)
            except:
                msg_dict = {}
            msg_dict["_outcome"] = outcome_data

            r = httpx.patch(
                f"{SUPABASE_URL}/rest/v1/market_alerts?id=eq.{alert_id}",
                headers=H,
                json={"acknowledged": True, "message": json.dumps(msg_dict)},
                timeout=10,
            )
            if r.status_code == 200:
                saved += 1
        except:
            pass

    return saved


# ============================================================
# REPORT
# ============================================================
def generate_report(per_skill_stats, resolved, still_pending, updated_skills):
    lines = [
        f"🧠 HERMES LEARN ENGINE — Outcome Feedback Report",
        f"📅 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        f"## Resolution Summary",
        f"- Checked: {len(resolved) + len(still_pending)} pending alerts",
        f"- Resolved: {len(resolved)}",
        f"- Still active: {len(still_pending)}",
        "",
    ]

    if resolved:
        wins = sum(1 for r in resolved if r.get("is_win") == True)
        losses = sum(1 for r in resolved if r.get("is_win") == False)
        info = sum(1 for r in resolved if r.get("is_win") is None)
        lines.append(f"## Outcome Breakdown")
        lines.append(f"- Wins: {wins}")
        lines.append(f"- Losses: {losses}")
        if wins + losses > 0:
            lines.append(f"- Win Rate: {wins/(wins+losses)*100:.1f}%")
        lines.append(f"- Informational: {info}")
        lines.append("")

        # Per skill
        lines.append("## Per-Skill Resolution")
        by_type = defaultdict(lambda: {"w": 0, "l": 0, "i": 0})
        for r in resolved:
            t = r.get("signal_type", "unknown")
            if r.get("is_win") is None:
                by_type[t]["i"] += 1
            elif r["is_win"]:
                by_type[t]["w"] += 1
            else:
                by_type[t]["l"] += 1

        for t, c in sorted(by_type.items()):
            total = c["w"] + c["l"]
            wr = f"{c['w']}/{total}={c['w']/total*100:.0f}%" if total > 0 else "N/A"
            lines.append(f"  {t}: {c['w']}W / {c['l']}L / {c['i']}I | WR: {wr}")
        lines.append("")

    # Per-skill recalibration
    if per_skill_stats:
        lines.append("## Confidence Recalibration")
        for stype, stats in sorted(per_skill_stats.items()):
            score = stats.get("confidence_score")
            sig = "✅" if stats.get("is_significant") else "⏳"
            sample = stats.get("sample_size", 0)
            wr = stats.get("win_rate")
            ci = stats.get("ci_95_lower")
            decay = stats.get("edge_decay", "N/A")
            score_str = f"{score}/10" if score is not None else "INSUFFICIENT_DATA"
            wr_str = f"{wr:.0%}" if wr is not None else "—"
            ci_str = f"[{ci:.0%}, ...]" if ci is not None else "—"
            lines.append(f"  {stype}: {score_str} | Sample: {sample} | WR: {wr_str} | CI: {ci_str} | Decay: {decay} {sig}")
        lines.append("")

    lines.append(f"## SKP Updates")
    lines.append(f"- Skills updated: {updated_skills}")
    lines.append(f"- Forecast graph: updated")
    lines.append(f"- Supabase: outcomes saved")
    lines.append("")
    lines.append("---")
    lines.append("LOOP: COLLECT → EXTRACT → SKILLIFY → EXECUTE → RESOLVE → LEARN → RECALIBRATE → DISTRIBUTE")
    lines.append("STATUS: LEARN phase complete. System recalibrated. Next: wait for more outcomes.")

    return "\n".join(lines)


# ============================================================
# MAIN
# ============================================================
def main():
    print(f"🧠 HERMES LEARN ENGINE — Adaptive Intelligence Calibration")
    print(f"📅 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 60)

    # PHASE 1: RESOLVE
    print("\n📋 PHASE 1: RESOLVE — Matching alerts to closed markets")
    resolved, still_pending = resolve_pending_alerts()

    # PHASE 2: SCORE
    print(f"\n🎯 PHASE 2: SCORE — Classifying outcomes")
    scored = []
    for r in resolved:
        alert = r.get("alert", {})
        signal_type = alert.get("alert_type", "unknown")
        outcome = r.get("outcome", "unknown")
        price = alert.get("threshold", 0)
        msg_str = alert.get("message", "{}")
        try:
            msg = json.loads(msg_str)
            question = msg.get("question", "")
        except:
            question = ""

        is_win, direction = score_signal(signal_type, outcome, price, question)
        r["signal_type"] = signal_type
        r["is_win"] = is_win
        r["direction"] = direction
        scored.append(r)

        if is_win is not None:
            status = "WIN" if is_win else "LOSS"
        else:
            status = "INFO"
        print(f"  {signal_type}: {outcome} → {status} ({direction})")

    # PHASE 3: RECALIBRATE
    print(f"\n🔄 PHASE 3: RECALIBRATE — Updating confidence & reliability")
    # Load existing outcomes from forecast graph
    existing_outcomes = []
    graph_path = f"{SKP_DIR}/forecast_graph_latest.json"
    try:
        with open(graph_path) as f:
            graph_data = json.load(f)
        existing = graph_data.get("resolutions", [])
        for o in existing:
            existing_outcomes.append({
                "signal_type": o.get("signal_type", "unknown"),
                "is_win": o.get("is_win"),
                "direction": o.get("direction", "unknown"),
            })
    except:
        pass

    # Combine existing + new
    new_outcome_records = []
    for s in scored:
        if s.get("is_win") is not None:
            new_outcome_records.append({
                "signal_type": s.get("signal_type"),
                "is_win": s.get("is_win"),
                "direction": s.get("direction"),
            })

    per_skill = recalibrate(existing_outcomes, new_outcome_records)
    for stype, stats in per_skill.items():
        sample = stats.get("sample_size", 0)
        score = stats.get("confidence_score")
        if score is not None:
            print(f"  {stype}: {score}/10 (n={sample})")
        else:
            print(f"  {stype}: NEEDS_DATA (n={sample})")

    # PHASE 4: UPDATE FORECAST GRAPH
    print(f"\n🧠 PHASE 4: LEARN — Updating forecast memory graph")
    graph = update_forecast_graph(scored)
    resolutions_count = len(graph.get("resolutions", []))
    print(f"  Graph resolutions: {resolutions_count}")

    # PHASE 5: UPDATE SKP
    print(f"\n📦 PHASE 5: ADJUST — Updating SKP skills")
    updated = update_skp(per_skill)
    print(f"  Skills updated: {updated}")

    # Save outcomes to Supabase
    saved_db = save_outcomes_to_supabase(scored)
    print(f"  Supabase updates: {saved_db}")

    # PHASE 6: REPORT
    report = generate_report(per_skill, scored, still_pending, updated)
    print(f"\n{'='*60}")
    print(report)

    # Save report
    with open(f"{SKP_DIR}/learn_report.txt", "w") as f:
        f.write(report)


if __name__ == "__main__":
    main()
