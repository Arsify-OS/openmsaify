"""
nanoclaw_skp_adapter — Polymarket Trading Engine
Part of openmsaify-trading (MIT License)
Copyright (c) 2025 OpenMSAify
"""

#!/usr/bin/env python3
"""
nanoclaw_skp_adapter.py — Bridge SKP knowledge into NanoClaw trading decisions

NanoClaw reads /root/polymarket/skp/skp_skills.json to:
- Weight signal types by confidence score
- Apply trading rules from SKP
- Filter opportunities by SKP parameters
- Auto-adjust position sizing based on signal type

Usage: Called by nanoclaw.py before each trade decision
"""

import json
import os

SKP_SKILLS_PATH = "/root/polymarket/skp/skp_skills.json"
SKP_LATEST_PATH = "/root/polymarket/skp/latest.json"

class NanoClawSKPAdapter:
    """Read SKP knowledge and convert to NanoClaw trading parameters."""

    def __init__(self):
        self.skills = self._load_skills()

    def _load_skills(self):
        try:
            with open(SKP_SKILLS_PATH) as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {"skills": [], "skill_count": 0}

    def get_signal_confidence(self, signal_type):
        """Get current confidence score for a signal type from SKP."""
        type_map = {
            "LOW_PRICE": "low_price_entry",
            "VOLUME_SPIKE": "volume_spike_entry",
            "WHALE_BUY": "whale_follow",
            "CORRELATION": "correlation_arbitrage",
        }

        skill_name = type_map.get(signal_type)
        if not skill_name:
            return 0

        for skill in self.skills.get("skills", []):
            if skill["name"] == skill_name:
                return skill.get("confidence_score", 0)

        return 0

    def get_entry_params(self, signal_type):
        """Get optimized entry parameters from SKP for signal type."""
        type_map = {
            "LOW_PRICE": "low_price_entry",
            "VOLUME_SPIKE": "volume_spike_entry",
            "WHALE_BUY": "whale_follow",
            "CORRELATION": "correlation_arbitrage",
        }

        skill_name = type_map.get(signal_type)
        if not skill_name:
            return {}

        for skill in self.skills.get("skills", []):
            if skill["name"] == skill_name:
                return skill.get("parameters", {})

        return {}

    def should_execute(self, signal_type, min_confidence=5.0):
        """Check if SKP says signal is strong enough to execute."""
        confidence = self.get_signal_confidence(signal_type)
        return confidence >= min_confidence

    def get_position_multiplier(self, signal_type):
        """Kelly fraction multiplier based on signal confidence."""
        confidence = self.get_signal_confidence(signal_type)

        if confidence >= 9:
            return 0.85  # High confidence → large position
        elif confidence >= 7:
            return 0.60  # Good confidence → medium position
        elif confidence >= 5:
            return 0.30  # Moderate confidence → small position
        else:
            return 0.10  # Low confidence → tiny position

    def get_rules_for_signal(self, signal_type):
        """Get all trading rules that apply to this signal type."""
        type_map = {
            "LOW_PRICE": "low_price_entry",
            "VOLUME_SPIKE": "volume_spike_entry",
            "WHALE_BUY": "whale_follow",
            "CORRELATION": "correlation_arbitrage",
        }

        skill_name = type_map.get(signal_type)
        if not skill_name:
            return []

        for skill in self.skills.get("skills", []):
            if skill["name"] == skill_name:
                return skill.get("rules", [])

        return []

    def summary(self):
        """Print a summary of current SKP knowledge for NanoClaw debugging."""
        lines = ["📋 NanoClaw SKP Knowledge Summary:"]
        for skill in self.skills.get("skills", []):
            name = skill["name"]
            score = skill.get("confidence_score", 0)
            ptype = skill.get("type", "")
            params = skill.get("parameters", {})
            
            lines.append(f"  {name} [{ptype}] — Confidence: {score}/10")
            lines.append(f"    Params: {params}")
            pos_mul = self.get_position_multiplier(name.split("_")[0].upper())
            lines.append(f"    Position Multiplier: {pos_mul}")
        
        return "\n".join(lines)

if __name__ == "__main__":
    adapter = NanoClawSKPAdapter()
    print(adapter.summary())
    
    print("\nSignal Confidence Status:")
    for signal_type in ["LOW_PRICE", "VOLUME_SPIKE", "WHALE_BUY", "CORRELATION"]:
        conf = adapter.get_signal_confidence(signal_type)
        exec_ok = adapter.should_execute(signal_type)
        pos_mul = adapter.get_position_multiplier(signal_type)
        status = "✅" if exec_ok else "⏳"
        print(f"  {status} {signal_type}: {conf}/10 | Position: {pos_mul:.0%} | {'EXECUTABLE' if exec_ok else 'MONITOR ONLY'}")
