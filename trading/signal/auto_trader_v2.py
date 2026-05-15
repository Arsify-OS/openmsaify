"""
auto_trader_v2 — Polymarket Trading Engine
Part of openmsaify-trading (MIT License)
Copyright (c) 2025 OpenMSAify
"""

#!/usr/bin/env python3
"""
Polymarket AutoTrader v2 - Data Collection + Telegram Alert System
Categories: LOW_PRICE, VOLUME_SPIKE, PRICE_PATTERN, LARGE_TRADE
Storage: Supabase market_alerts table
Delivery: Telegram via Hermes cron job
"""

import sys
import httpx
import json
import os
from datetime import datetime, timedelta, timezone
from collections import defaultdict

# Historical prior engine for Bayesian calibration
# Load dependencies
sys.path.insert(0, "/root/polymarket")
import historical_prior as hp
import ensemble_calibrator as ec

# Lazy-loaded ensemble calibrator
_calibrator = None
def get_calibrator():
    global _calibrator
    if _calibrator is None:
        _calibrator = ec.EnsembleCalibrator()
    return _calibrator

# Supabase config from environment
SUPABASE_URL = os.getenv("NEXT_PUBLIC_SUPABASE_URL", "https://dklsuxeqwzuroiikosqn.supabase.co")
SUPABASE_ANON_KEY = os.getenv("NEXT_PUBLIC_SUPABASE_ANON_KEY", "")

if not SUPABASE_ANON_KEY:
    # Fallback to known key
    SUPABASE_ANON_KEY = "sb_publishable_GwMAEA4xdQ7I5q0kCNtF7Q_tGsjTHXc"

class SupabaseStorage:
    """Read/write signals to Supabase market_alerts + trades tables"""

    def __init__(self):
        self.base_url = SUPABASE_URL
        self.headers = {
            "apikey": SUPABASE_ANON_KEY,
            "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
            "Content-Type": "application/json",
        }

    def get_recent_signals(self, hours=12):
        """Get recent alerts for deduplication"""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        try:
            resp = httpx.get(
                f"{self.base_url}/rest/v1/market_alerts",
                headers=self.headers,
                params={"created_at": f"gt.{cutoff.isoformat()}", "limit": "500"},
                timeout=10,
            )
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            pass
        return []

    def save_alert(self, alert_type, market_id, threshold, current_value, message_json):
        """Save alert to market_alerts table"""
        record = {
            "polymarket_id": market_id,
            "alert_type": alert_type,
            "threshold": threshold,
            "current_value": current_value,
            "previous_value": 0,
            "message": message_json,
            "acknowledged": False,
        }
        try:
            resp = httpx.post(
                f"{self.base_url}/rest/v1/market_alerts",
                headers=self.headers,
                json=record,
                timeout=10,
            )
            return resp.status_code in (200, 201)
        except Exception as e:
            print(f"save_alert error: {e}")
            return False

    def save_snapshot(self, polymarket_id, question, slug, outcome_prices,
                      volume_24hr, liquidity, end_date, active, category, tags, raw_data):
        """Insert market snapshot to market_snapshots table (time-series, no dedup)"""
        record = {
            "polymarket_id": str(polymarket_id),
            "question": question,
            "slug": slug,
            "outcome_prices": json.dumps(outcome_prices) if not isinstance(outcome_prices, str) else outcome_prices,
            "volume_24hr": volume_24hr,
            "liquidity": liquidity,
            "total_volume": volume_24hr,
            "end_date": end_date if end_date else None,
            "active": active,
            "category": category or None,
            "tags": json.dumps(tags) if tags else None,
            "raw_data": json.dumps(raw_data) if not isinstance(raw_data, str) else raw_data,
            "captured_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            resp = httpx.post(
                f"{self.base_url}/rest/v1/market_snapshots",
                headers=self.headers,
                json=record,
                timeout=10,
            )
            return resp.status_code in (200, 201)
        except Exception as e:
            print(f"save_snapshot error: {e}")
            return False


class PolymarketScanner:
    """4-category Polymarket opportunity scanner"""

    def __init__(self):
        self.gamma = "https://gamma-api.polymarket.com"
        self.data = "https://data-api.polymarket.com"
        self.clob = "https://clob.polymarket.com"
        self.storage = SupabaseStorage()

    # ------------------------------------------------------------------
    # Category 1: Low Price Opportunities
    # ------------------------------------------------------------------
    def scan_low_price(self, min_volume=500, max_price=0.20, min_price=0.02):
        """Buy < max_price, sell at $1.00 = (1/price - 1) * 100 return
        Now filters out NEG_RISK markets and scores with historical prior."""
        resp = httpx.get(f"{self.gamma}/markets", params={
            "limit": 200, "active": True, "closed": False,
            "order": "volume", "ascending": False,
        }, timeout=15)
        if resp.status_code != 200:
            return []

        results = []
        for m in resp.json():
            # CHANGE 4: Skip neg_risk markets (86.1% resolve No historically)
            if m.get("negRisk") is True:
                continue

            try:
                prices = json.loads(m["outcomePrices"])
                yes = float(prices[0])
                vol = float(m.get("volume", 0))
                liq = float(m.get("liquidityNum", m.get("liquidity", 0)))
                spread = float(m.get("spread", 0)) / 100 if m.get("spread") else None
                if min_price <= yes <= max_price and vol >= min_volume:
                    roi = (1.0 / yes) - 1

                    # CHANGE 5: Score with historical prior + category
                    scoring = hp.score_with_prior(
                        "LOW_PRICE", m.get("question", ""), m.get("slug", ""),
                        neg_risk=False, volume=vol, spread=spread
                    )

                    results.append({
                        "type": "LOW_PRICE",
                        "market_id": m.get("conditionId", ""),
                        "question": m["question"],
                        "price": yes,
                        "volume": vol,
                        "liquidity": liq,
                        "roi": roi,
                        "score": scoring["score"],
                        "historical_confidence": scoring["confidence"],
                        "category": scoring["category"],
                    })
            except Exception:
                continue
        results.sort(key=lambda x: x["score"], reverse=True)
        return results

    # ------------------------------------------------------------------
    # Category 2: Volume Spike Detector
    # ------------------------------------------------------------------
    def scan_volume_spikes(self, lookback_hours=24, min_trades=3, spike_ratio=0.4):
        """Markets where 24h trade volume > spike_ratio * total volume
         Min total volume $100 to filter micro-markets
         Now filters out NEG_RISK markets and scores with historical prior."""
        resp = httpx.get(f"{self.gamma}/markets", params={
            "limit": 50, "active": True, "closed": False,
            "order": "volume", "ascending": False,
        }, timeout=15)
        if resp.status_code != 200:
            return []

        results = []
        now = datetime.now(timezone.utc).timestamp()
        cutoff = now - (lookback_hours * 3600)

        for m in resp.json():
            cond_id = m.get("conditionId", "")

            # CHANGE 4: Skip neg_risk markets
            if m.get("negRisk") is True:
                continue

            try:
                total_vol = float(m.get("volume", 0))
                if total_vol < 100:
                    continue
                trades_resp = httpx.get(f"{self.data}/trades",
                                   params={"market": cond_id, "limit": 50},
                                   timeout=10)
                trades = trades_resp.json() or []
                recent = [t for t in trades if t.get("timestamp", 0) >= cutoff]
                if len(recent) < min_trades:
                    continue
                vol_24h = sum(t.get("size", 0) * t.get("price", 0) for t in recent)
                if total_vol > 0 and vol_24h / total_vol > spike_ratio:
                    # CHANGE 5: Score with historical prior + spread
                    spread_val = float(m.get("spread", 0) or 0) / 100 if m.get("spread") else None
                    scoring = hp.score_with_prior(
                        "VOLUME_SPIKE", m.get("question", ""), m.get("slug", ""),
                        neg_risk=False, volume=total_vol, spread=spread_val
                    )

                    results.append({
                        "type": "VOLUME_SPIKE",
                        "market_id": cond_id,
                        "question": m["question"],
                        "volume_24h": vol_24h,
                        "total_volume": total_vol,
                        "ratio": vol_24h / total_vol,
                        "trade_count": len(recent),
                        "score": scoring["score"],
                        "historical_confidence": scoring["confidence"],
                        "category": scoring["category"],
                    })
            except Exception:
                continue
        results.sort(key=lambda x: x["score"], reverse=True)
        return results

    # ------------------------------------------------------------------
    # Category 3: Price History Patterns (value bounce)
    # ------------------------------------------------------------------
    def scan_price_patterns(self, min_points=10):
        """Find markets that dropped from high to low - potential bounce candidates
         Uses CLOB price history with fallback to current price analysis
         Now filters out NEG_RISK markets."""
        resp = httpx.get(f"{self.gamma}/markets", params={
            "limit": 30, "active": True, "closed": False,
            "order": "volume", "ascending": False,
        }, timeout=15)
        if resp.status_code != 200:
            return []

        results = []
        for m in resp.json():
            # CHANGE 4: Skip neg_risk
            if m.get("negRisk") is True:
                continue

            try:
                prices = json.loads(m["outcomePrices"])
                cur = float(prices[0])
                cond = m.get("conditionId", "")
                total_vol = float(m.get("volume", 0))

                # Skip micro-markets and extremes
                if total_vol < 500 or cur < 0.03 or cur > 0.90:
                    continue

                # Try CLOB history first
                hist_resp = httpx.get(f"{self.clob}/prices-history", params={
                    "market": cond, "interval": "1m", "fidelity": 50,
                }, timeout=10)

                history = []
                if hist_resp.status_code == 200:
                    history = hist_resp.json().get("history", [])

                if len(history) >= min_points:
                    pts = [float(p["p"]) for p in history]
                    hi, lo = max(pts), min(pts)
                    # Value bounce: was >60c, now <30c
                    if hi > 0.60 and cur < 0.30 and (hi - lo) > 0.30:
                        recovery = (hi - cur) / cur
                        spread = float(m.get("spread", 0)) / 100 if m.get("spread") else None
                        scoring = hp.score_with_prior(
                            "LOW_PRICE", m.get("question", ""), m.get("slug", ""),
                            neg_risk=False, volume=total_vol, spread=spread
                        )
                        results.append({
                            "type": "VALUE_BOUNCE",
                            "market_id": cond,
                            "question": m["question"],
                            "price": cur,
                            "high": hi,
                            "low": lo,
                            "recovery": recovery,
                            "score": scoring["score"],
                            "historical_confidence": scoring["confidence"],
                            "category": scoring["category"],
                        })
                else:
                    # Fallback: use outcomePrices to detect interesting patterns
                    no_price = float(prices[1]) if len(prices) > 1 else 1 - cur
                    if no_price > 0.85 and total_vol > 5000:
                        scoring = hp.score_with_prior(
                            "CONTRARIAN", m.get("question", ""), m.get("slug", ""),
                            neg_risk=True, volume=total_vol  # neg_risk=True penalizes heavily
                        )
                        # Still surface if historically justified despite contrarian penalty
                        if scoring["score"] >= 3.0:
                            results.append({
                                "type": "CONTRARIAN",
                                "market_id": cond,
                                "question": m["question"],
                                "price": cur,
                                "no_price": no_price,
                                "volume": total_vol,
                                "score": scoring["score"],
                                "historical_confidence": scoring["confidence"],
                                "category": scoring["category"],
                            })
            except Exception:
                continue
        results.sort(key=lambda x: x["score"], reverse=True)
        return results

    # ------------------------------------------------------------------
    # Category 4: Large Trade Detection
    # ------------------------------------------------------------------
    def scan_large_trades(self, min_value=50, max_price=0.25):
        """Recent BUY orders >= $min_value at price <= max_price
        Now filters out NEG_RISK markets and scores with historical prior."""
        resp = httpx.get(f"{self.data}/trades",
                         params={"limit": 100}, timeout=10)
        if resp.status_code != 200:
            return []

        results = []
        for t in resp.json():
            try:
                size = float(t.get("size", 0))
                price = float(t.get("price", 0))
                val = size * price
                if t.get("side") == "BUY" and val >= min_value and price <= max_price:
                    # CHANGE 5: Score with historical prior
                    scoring = hp.score_with_prior(
                        "LOW_PRICE", t.get("title", ""), "",
                        neg_risk=False, volume=val
                    )

                    results.append({
                        "type": "LARGE_TRADE",
                        "market_id": t.get("conditionId", ""),
                        "question": t.get("title", "N/A"),
                        "price": price,
                        "size": size,
                        "value": val,
                        "wallet": t.get("proxyWallet", ""),
                        "score": scoring["score"],
                        "historical_confidence": scoring["confidence"],
                        "category": scoring["category"],
                    })
            except Exception:
                continue
        results.sort(key=lambda x: x["score"], reverse=True)
        return results

    # ------------------------------------------------------------------
    # Category 5: Whale Activity Tracker — Track profitable wallets
    # ------------------------------------------------------------------
    def scan_whale_activity(self, min_value=200, max_price=0.30):
        """Detect when tracked profitable wallets or new large-buy wallets
        enter markets. Focus on BUY orders >= $min_value at price <= max_price.
        Now filters out NEG_RISK markets and scores with historical prior."""
        resp = httpx.get(f"{self.data}/trades",
                         params={"limit": 200}, timeout=10)
        if resp.status_code != 200:
            return []

        # Load known profitable whales from previous tracker runs
        known_whales = {}
        try:
            with open("/tmp/profitable_whales.json") as f:
                for w in json.load(f):
                    known_whales[w["wallet"]] = w
        except FileNotFoundError:
            pass

        results = []
        for t in resp.json():
            try:
                size = float(t.get("size", 0))
                price = float(t.get("price", 0))
                val = size * price
                is_whale_wallet = t.get("proxyWallet", "") in known_whales

                # Include if: large BUY at low price, OR known whale buys anything
                if val >= min_value and price <= max_price:
                    wallet = t.get("proxyWallet", "")
                    pseudonym = t.get("pseudonym", "")

                    # CHANGE 5: Score with historical prior
                    scoring = hp.score_with_prior(
                        "LOW_PRICE", t.get("title", ""), "",
                        neg_risk=False, volume=val
                    )

                    score = scoring["score"]
                    if is_whale_wallet:
                        score = min(10, score * 1.5)  # Boost known whale signals

                    results.append({
                        "type": "WHALE_BUY",
                        "market_id": t.get("conditionId", ""),
                        "question": t.get("title", "N/A"),
                        "price": price,
                        "size": size,
                        "value": val,
                        "wallet": wallet,
                        "pseudonym": pseudonym,
                        "is_known_whale": is_whale_wallet,
                        "whale_data": known_whales.get(wallet, {}),
                        "score": score,
                        "historical_confidence": scoring["confidence"],
                        "category": scoring["category"],
                    })
            except Exception:
                continue

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:15]  # Top 15 whale signals

    # ------------------------------------------------------------------
    # Category 6: Market Correlation & Arbitrage Detection
    # ------------------------------------------------------------------
    def scan_correlations(self):
        """Detect arbitrage opportunities in mutually exclusive event groups.
        Now filters out NEG_RISK markets and scores with historical prior."""
        try:
            # Run correlation engine
            import subprocess
            r = subprocess.run(
                ["python3", "/root/polymarket/correlation_engine.py"],
                capture_output=True, text=True, timeout=30
            )

            # Load opportunities from the correlation engine output
            opportunities = []
            try:
                with open("/tmp/arbitrage_opportunities.json") as f:
                    opportunities = json.load(f)
            except FileNotFoundError:
                pass

            results = []
            high_conf = [o for o in opportunities if o.get("confidence") == "HIGH"]
            med_conf = [o for o in opportunities if o.get("confidence") == "MEDIUM"]

            # Only surface medium+ confidence opportunities
            for opp in (high_conf + med_conf)[:5]:
                # CHANGE 4: Skip neg_risk
                if opp.get("negRisk") is True:
                    continue

                yes_price = opp.get("yes_price", 0)
                if yes_price > 0:
                    roi = (1.0 / yes_price) - 1
                else:
                    roi = 999

                # CHANGE 5: Score with historical prior
                scoring = hp.score_with_prior(
                    "LOW_PRICE", opp.get("market", ""), "",
                    neg_risk=False, volume=opp.get("volume", 0)
                )

                results.append({
                    "type": opp.get("type", "CORRELATION"),
                    "market_id": opp.get("market_id", ""),
                    "question": opp.get("market", "")[:80],
                    "price": opp.get("yes_price", 0),
                    "roi": roi,
                    "potential_roi": opp.get("potential_roi", 0),
                    "confidence": scoring["confidence"],
                    "group": opp.get("group", ""),
                    "score": scoring["score"],
                    "volume": opp.get("volume", 0),
                    "discount_pct": opp.get("discount_pct", 0),
                    "category": scoring["category"],
                })

            return results

        except Exception:
            return []

    # ==================================================================
    # ML OVERLAY — Ensemble Calibration (disagreement detector)
    # ==================================================================
    def _enrich_with_ensemble_cal(self, results):
        """Add ML ensemble calibration to all scanner results.

        Does NOT trigger trades. Acts as:
        - Calibration layer
        - Disagreement detector
        - Probabilistic filter
        - Confidence modifier
        """
        try:
            cal = get_calibrator()
        except Exception as e:
            return results  # If calibrator fails, return original results unchanged

        enriched = {}
        for scan_type, items in results.items():
            enriched_items = []
            for item in items:
                try:
                    # Extract market data from the scanner result
                    price = item.get("price", 0.5)
                    volume = item.get("volume", 0)
                    question = item.get("question", "")
                    cat = item.get("category", hp.derive_category(question) if question else "Other")
                    
                    # Estimate spread from liquidity (wider for low liq)
                    liq = item.get("liquidity", 0)
                    spread = 0.01 if liq > 10000 else (0.05 if liq > 1000 else 0.15)
                    
                    signal_type = item.get("type", "LOW_PRICE")
                    
                    cal_result = cal.calibrate(
                        market_price_yes=price,
                        question=question,
                        category=cat,
                        volume=volume,
                        spread=spread,
                        signal_type=signal_type,
                    )
                    
                    tier, tier_score = ec.mispricing_tier({**cal_result, "volume": volume, "mispricing_score": 0, "market_id": "", "question": question, "category": cat, "neg_risk": False})
                    
                    item.update({
                        "ml_model_probability": cal_result.get("ml_prob"),
                        "market_probability": price,
                        "raw_edge": cal_result.get("raw_edge", 0),
                        "effective_edge": cal_result.get("effective_edge", 0),
                        "liquidity_adjusted_edge": cal_result.get("effective_edge", 0),
                        "calibration_confidence": cal_result.get("calibration_confidence", 0),
                        "market_efficiency_score": cal_result.get("market_efficiency", 0),
                        "regime_classification": cal_result.get("regime", ""),
                        "tier": tier,
                        "mispricing_score": tier_score,
                        "final_ai_probability": cal_result.get("final_probability", 0.5),
                    })
                except:
                    pass  # Skip enrichment for individual items that fail
                    
                enriched_items.append(item)
            enriched[scan_type] = enriched_items

        return enriched

    def run_all(self, snapshot_all=True):
        """Run all 6 scanners. If snapshot_all, also save ALL active markets
         to market_snapshots table for historical tracking."""
        results = {
            "low_price": self.scan_low_price(),
            "volume_spikes": self.scan_volume_spikes(),
            "price_patterns": self.scan_price_patterns(),
            "large_trades": self.scan_large_trades(),
            "whale_activity": self.scan_whale_activity(),
            "correlations": self.scan_correlations(),
        }

        # CHANGE 6: Apply category preference filter
        results = self._apply_category_filter(results)

        # PHASE 3: ML Overlay — ensemble calibration
        results = self._enrich_with_ensemble_cal(results)

        if snapshot_all:
            self.save_full_snapshot()
        return results

    def _apply_category_filter(self, results):
        """Filter results using historical category preferences.
        Crypto/Sports = preferred. Climate/Tech Companies = deprioritized."""
        priors = hp.load_priors()
        preferred_cats = {
            "Crypto": priors.get("CATEGORY_CRYPTO", {}).get("score", 6.5),
            "Sports": priors.get("CATEGORY_SPORTS", {}).get("score", 6.3),
            "Politics": priors.get("CATEGORY_POLITICS", {}).get("score", 5.8),
            "Technology": priors.get("CATEGORY_TECHNOLOGY", {}).get("score", 5.5),
            "Other": priors.get("CATEGORY_OTHER", {}).get("score", 5.5),
            "Climate": priors.get("CATEGORY_CLIMATE", {}).get("score", 4.9),
            "Geopolitics": priors.get("CATEGORY_GEOPOLITICS", {}).get("score", 5.4),
            "Entertainment": priors.get("CATEGORY_ENTERTAINMENT", {}).get("score", 5.3),
            "Tech Companies": priors.get("CATEGORY_TECH COMPANIES", {}).get("score", 5.1),
            "Economy": priors.get("CATEGORY_ECONOMY", {}).get("score", 5.0),
            "Legal": priors.get("CATEGORY_LEGAL", {}).get("score", 5.0),
            "Health": priors.get("CATEGORY_HEALTH", {}).get("score", 5.0),
        }

        filtered = {}
        for scan_type, items in results.items():
            scored_items = []
            for item in items:
                cat = item.get("category", "Other")
                cat_score = preferred_cats.get(cat, 5.0)
                # Apply category weight: 80% original score + 20% category
                item_score = item.get("score", 5.0) * 0.8 + cat_score * 0.2
                item["category_weighted_score"] = round(item_score, 1)
                item["category_score"] = cat_score
                scored_items.append(item)

            # Sort by category-weighted score
            scored_items.sort(key=lambda x: x.get("category_weighted_score", 0), reverse=True)
            filtered[scan_type] = scored_items

        return filtered

    # ------------------------------------------------------------------
    # Market Snapshots: save ALL active markets for historical analysis
    # ------------------------------------------------------------------
    def save_full_snapshot(self, limit=200):
        """Snapshot all active markets to Supabase market_snapshots table.
         This builds the historical dataset needed for backtesting."""
        resp = httpx.get(f"{self.gamma}/markets", params={
            "limit": limit, "active": True, "closed": False,
            "order": "volume", "ascending": False,
        }, timeout=15)
        if resp.status_code != 200:
            print("  snapshot: API error")
            return 0

        markets = resp.json()
        saved = 0
        for m in markets:
            try:
                prices = json.loads(m.get("outcomePrices", "[]"))
                yes_price = float(prices[0]) if prices else 0
                vol = float(m.get("volume", 0))
                liq = float(m.get("liquidity", 0))
                raw = {
                    "id": m.get("id", ""),
                    "question": m.get("question", ""),
                    "condition_id": m.get("conditionId", ""),
                    "yes_price": yes_price,
                    "volume": vol,
                    "liquidity": liq,
                    "captured_at": datetime.now(timezone.utc).isoformat(),
                }
                ok = self.storage.save_snapshot(m.get("id", ""), m.get("question", ""),
                                                 m.get("slug", ""), prices, vol, liq,
                                                 m.get("endDate", ""), m.get("active", True),
                                                 m.get("category", ""), m.get("tags", []), raw)
                if ok:
                    saved += 1
            except Exception:
                continue
        print(f"  snapshot: {saved}/{len(markets)} markets saved")
        return saved


# ======================================================================
# Alert formatting
# ======================================================================

def make_alert(results):
    lines = [
        "🔍 POLYMARKET AUTO-TRADER",
        f"📅 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "📊 Historical Prior: 95K resolved markets",
        "",
    ]

    # Low Price (top 5 by score)
    lp = sorted(results.get("low_price", []), key=lambda x: x.get("category_weighted_score", x.get("score", 0)), reverse=True)[:5]
    lines.append(f"💰 LOW PRICE ({len(lp)} found)")
    if lp:
        for m in lp:
            cents = m["price"] * 100
            roi = m["roi"]
            conf = m.get("historical_confidence", "LOW")
            cat = m.get("category", "")
            score = m.get("category_weighted_score", m.get("score", 0))
            tier = m.get("tier", "")
            edge = m.get("raw_edge", 0)
            lines.append(f"• {m['question'][:55]}...")
            lines.append(f"  {cents:.1f}¢ | Vol ${m['volume']:,.0f} | ROI +{roi*100:.0f}% ({roi:.1f}x)")
            tier_str = f" | Tier: {tier}" if tier else ""
            edge_str = f" | Edge: {edge:+.1%}" if edge else ""
            lines.append(f"  Score: {score}/10 [{conf}] | {cat}{tier_str}{edge_str}")
    else:
        lines.append("  -")
    lines.append("")

    # Volume Spikes
    vs = sorted(results.get("volume_spikes", []), key=lambda x: x.get("category_weighted_score", x.get("score", 0)), reverse=True)[:3]
    lines.append(f"📈 VOLUME SPIKES ({len(vs)} found)")
    for m in vs:
        conf = m.get("historical_confidence", "LOW")
        cat = m.get("category", "")
        score = m.get("category_weighted_score", m.get("score", 0))
        lines.append(f"• {m['question'][:55]}...")
        lines.append(f"  24h ${m['volume_24h']:,.0f} | ratio {m['ratio']:.1f}x | {m['trade_count']} trades")
        lines.append(f"  Score: {score}/10 [{conf}] | {cat}")
    if not vs:
        lines.append("  -")
    lines.append("")

    # Price Patterns (top 3 by score)
    pp = sorted(results.get("price_patterns", []), key=lambda x: x.get("category_weighted_score", x.get("score", 0)), reverse=True)[:3]
    lines.append(f"🔄 PATTERNS ({len(pp)} found)")
    for m in pp:
        score = m.get("category_weighted_score", m.get("score", 0))
        conf = m.get("historical_confidence", "LOW")
        cat = m.get("category", "")
        if m.get("type") == "VALUE_BOUNCE":
            lines.append(f"• BOUNCE: {m['question'][:45]}...")
            lines.append(f"  Hi ${(m['high']*100):.0f}¢ → Now ${(m['price']*100):.0f}¢ | recovery +{m['recovery']*100:.0f}%")
        else:
            lines.append(f"• CONTRARIAN: {m['question'][:45]}...")
            lines.append(f"  No ${(m['no_price']*100):.0f}% | Vol ${m['volume']:,.0f}")
        lines.append(f"  Score: {score}/10 [{conf}] | {cat}")
    if not pp:
        lines.append("  -")
    lines.append("")

    # Large Trades (top 3 by score)
    lt = sorted(results.get("large_trades", []), key=lambda x: x.get("category_weighted_score", x.get("score", 0)), reverse=True)[:3]
    lines.append(f"🐋 LARGE TRADES ({len(lt)} found)")
    for m in lt:
        score = m.get("category_weighted_score", m.get("score", 0))
        conf = m.get("historical_confidence", "LOW")
        cat = m.get("category", "")
        lines.append(f"• BUY ${m['value']:,.0f} @ {m['price']*100:.1f}¢")
        lines.append(f"  {m['question'][:55]}...")
        lines.append(f"  Score: {score}/10 [{conf}] | {cat}")
    if not lt:
        lines.append("  -")
    lines.append("")

    # Whale Activity (top 5 by score)
    wa = sorted(results.get("whale_activity", []), key=lambda x: x.get("category_weighted_score", x.get("score", 0)), reverse=True)[:5]
    lines.append(f"🎯 WHALE ACTIVITY ({len(wa)} found)")
    known_count = sum(1 for m in wa if m.get("is_known_whale"))
    if known_count:
        lines.append(f"  ⚠️ {known_count} from KNOWN profitable wallets!")
    for m in wa:
        score = m.get("category_weighted_score", m.get("score", 0))
        conf = m.get("historical_confidence", "LOW")
        cat = m.get("category", "")
        whale_tag = "🐋 KNOWN WHALE" if m.get("is_known_whale") else ""
        lines.append(f"• {'BUY' if whale_tag else 'BUY'} ${m['value']:,.0f} @ {m['price']*100:.1f}¢ {whale_tag}")
        if m.get("pseudonym"):
            lines.append(f"  {m['pseudonym']}: {m['question'][:50]}...")
        else:
            lines.append(f"  {m['question'][:55]}...")
        if m.get("is_known_whale") and m.get("whale_data"):
            wd = m["whale_data"]
            wr = wd.get("win_rate", 0)
            pnl = wd.get("pnl", 0)
            lines.append(f"    WR: {wr}% | PnL: ${pnl:,.0f} | PF: {wd.get('profit_factor', 'N/A')}")
        lines.append(f"  Score: {score}/10 [{conf}] | {cat}")
    if not wa:
        lines.append("  -")
    lines.append("")

    # Correlation & Arbitrage (top 3 by score)
    co = sorted(results.get("correlations", []), key=lambda x: x.get("category_weighted_score", x.get("score", 0)), reverse=True)[:3]
    lines.append(f"🔗 CORRELATIONS ({len(co)} found)")
    for m in co:
        score = m.get("category_weighted_score", m.get("score", 0))
        cat = m.get("category", "")
        lines.append(f"• [{m['confidence']}] {m['question'][:55]}...")
        lines.append(f"  {m['price']:.1%} | ROI {m.get('potential_roi',0):.0f}x | {m.get('group','')}")
        lines.append(f"  Score: {score}/10 | {cat}")
    if not co:
        lines.append("  -")
    lines.append("")
    lines.append("🤖 AutoTrader v2 | 95K historical prior | DYOR")

    return "\n".join(lines)


# ======================================================================
# Supabase integration + dedup
# ======================================================================

def save_and_dedup(scanner, results):
    """Save new signals, return count of alerts worth notifying about"""
    recent = scanner.storage.get_recent_signals(hours=6)
    seen_ids = {r.get("polymarket_id") for r in recent}

    saved = 0
    for r in results.get("low_price", []):
        if r["market_id"] in seen_ids:
            continue
        msg = json.dumps({"question": r["question"], "price": r["price"],
                          "volume": r["volume"], "roi": r["roi"]})
        ok = scanner.storage.save_alert("LOW_PRICE", r["market_id"],
                                         r["price"], r["volume"], msg)
        if ok:
            saved += 1
            seen_ids.add(r["market_id"])

    for r in results.get("volume_spikes", []):
        if r["market_id"] in seen_ids:
            continue
        msg = json.dumps({"question": r["question"], "ratio": r["ratio"],
                          "trades": r["trade_count"]})
        ok = scanner.storage.save_alert("VOLUME_SPIKE", r["market_id"],
                                         r["ratio"], r["volume_24h"], msg)
        if ok:
            saved += 1
            seen_ids.add(r["market_id"])

    for r in results.get("price_patterns", []):
        if r["market_id"] in seen_ids:
            continue
        msg = json.dumps({"question": r["question"], "high": r["high"],
                          "price": r["price"], "recovery": r["recovery"]})
        ok = scanner.storage.save_alert("VALUE_BOUNCE", r["market_id"],
                                         r["price"], r["recovery"], msg)
        if ok:
            saved += 1
            seen_ids.add(r["market_id"])

    for r in results.get("large_trades", []):
        if r["market_id"] in seen_ids:
            continue
        msg = json.dumps({"question": r["question"], "value": r["value"],
                          "price": r["price"], "wallet": r["wallet"]})
        ok = scanner.storage.save_alert("LARGE_TRADE", r["market_id"],
                                         r["price"], r["value"], msg)
        if ok:
            saved += 1
            seen_ids.add(r["market_id"])

    # Whale Activity — track known whales entering markets
    for r in results.get("whale_activity", []):
        if r["market_id"] in seen_ids:
            continue
        msg = json.dumps({
            "question": r["question"], "value": r["value"],
            "price": r["price"], "wallet": r["wallet"],
            "pseudonym": r.get("pseudonym", ""),
            "is_known_whale": r.get("is_known_whale", False),
        })
        ok = scanner.storage.save_alert("WHALE_BUY", r["market_id"],
                                         r["price"], r["value"], msg)
        if ok:
            saved += 1
            seen_ids.add(r["market_id"])

    # Correlation & Arbitrage — unique signal type
    for r in results.get("correlations", []):
        mid = r.get("market_id") or r.get("question", "corr")[:30]
        if mid in seen_ids:
            continue
        msg = json.dumps({
            "question": r["question"], "price": r["price"],
            "confidence": r.get("confidence"), "group": r.get("group"),
            "potential_roi": r.get("potential_roi", 0),
        })
        ok = scanner.storage.save_alert("CORRELATION", mid,
                                         r["price"], r.get("potential_roi", 0), msg)
        if ok:
            saved += 1
            seen_ids.add(mid)

    return saved


# ======================================================================
# Main
# ======================================================================

def main():
    print("=" * 50)
    print("POLYMARKET AUTOTRADER SCAN")
    print("=" * 50)

    scanner = PolymarketScanner()
    results = scanner.run_all()

    counts = {k: len(v) for k, v in results.items()}
    for k, v in counts.items():
        print(f"  {k}: {v}")

    saved = save_and_dedup(scanner, results)
    print(f"  saved (new): {saved}")

    total = sum(counts.values())
    if total > 0:
        alert = make_alert(results)
        print(f"\n{alert}")
        print("\n___ALERT___")
        print(alert)
    else:
        print("\nNo signals found.")


if __name__ == "__main__":
    main()
