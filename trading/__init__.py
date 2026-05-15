"""
openmsaify-trading — Polymarket Trading Engine
Layers: decision | signal | context | execution | feedback
"""
from importlib import import_module as _imp

def __getattr__(name):
    """Lazy import for trading subpackages."""
    _map = {
        # decision
        "anti_delusion_filter": "trading.decision.anti_delusion_filter",
        "ensemble_calibrator":  "trading.decision.ensemble_calibrator",
        "learn_engine":         "trading.decision.learn_engine",
        # signal
        "mispricing_scanner":   "trading.signal.mispricing_scanner",
        "auto_trader_v2":       "trading.signal.auto_trader_v2",
        "correlation_scanner":  "trading.signal.correlation_scanner",
        # context
        "regime_engine":        "trading.context.regime_engine",
        "narrative_engine":     "trading.context.narrative_engine",
        "historical_prior":     "trading.context.historical_prior",
        "calibration_memory":   "trading.context.calibration_memory",
        "auto_recalibration":   "trading.context.auto_recalibration",
        # execution
        "nanoclaw":             "trading.execution.nanoclaw",
        "nanoclaw_skp_adapter": "trading.execution.nanoclaw_skp_adapter",
        "nanoclaw_paper_trade": "trading.execution.nanoclaw_paper_trade",
        "nanoclaw_scan":        "trading.execution.nanoclaw_scan",
        "paper_trade_engine":   "trading.execution.paper_trade_engine",
        "position_sizing":      "trading.execution.position_sizing",
        "risk_management":      "trading.execution.risk_management",
        # feedback
        "performance_dashboard":"trading.feedback.performance_dashboard",
    }
    if name not in _map:
        raise AttributeError(f"module 'trading' has no attribute {name!r}")
    return _imp(_map[name])

__all__ = [
    "anti_delusion_filter", "ensemble_calibrator", "learn_engine",
    "mispricing_scanner", "auto_trader_v2", "correlation_scanner",
    "regime_engine", "narrative_engine", "historical_prior",
    "calibration_memory", "auto_recalibration",
    "nanoclaw", "nanoclaw_skp_adapter", "nanoclaw_paper_trade", "nanoclaw_scan",
    "paper_trade_engine", "position_sizing", "risk_management",
    "performance_dashboard",
]
