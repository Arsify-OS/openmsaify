# OpenMSAify Trading Engine

> Polymarket prediction market trading engine — decision → signal → context → execution → feedback

**Version:** 0.1.0
**License:** MIT
**Python:** ≥ 3.11

---

## Overview

`openmsaify-trading` is a structured, layered trading engine built for [Polymarket](https://polymarket.com). It transforms raw market data into calibrated trading decisions through five composable layers, with governance-aware risk management at every step.

```
Decision → Signal → Context → Execution → Feedback
   (D)        (S)       (C)       (E)         (F)
```

## Architecture

| Layer | Purpose | Key Modules |
|-------|---------|-------------|
| **Decision** | Ensemble scoring, anti-delusion filters, learning engine | `anti_delusion_filter`, `ensemble_calibrator`, `learn_engine` |
| **Signal** | Opportunity detection & entry signals | `mispricing_scanner`, `auto_trader_v2`, `correlation_scanner` |
| **Context** | Regime classification, narrative analysis, calibration memory | `regime_engine`, `narrative_engine`, `historical_prior`, `calibration_memory`, `auto_recalibration` |
| **Execution** | Order routing, risk management, Nanoclaw CLOB client | `nanoclaw`, `paper_trade_engine`, `position_sizing`, `risk_management` |
| **Feedback** | Performance tracking & dashboard | `performance_dashboard` |

## Quick Start

### Install

```bash
pip install openmsaify-trading
# or from source
pip install -e .
```

### Run Paper Trading

```bash
python nanoclaw_paper_trade.py
```

### Import in your code

```python
# Direct layer imports
from trading.execution import Nanoclaw, PaperTradeEngine, PositionSizing, RiskManagement
from trading.signal import AutoTraderV2, MispricingScanner
from trading.context import RegimeEngine, NarrativeEngine
from trading.decision import EnsembleCalibrator, AntiDelusionFilter

# Backward-compatible root-level imports also work
from auto_trader_v2 import AutoTrader
from nanoclaw import Nanoclaw, ClobClient
```

## Configuration

Environment variables (use a `.env` file or export directly):

| Variable | Purpose |
|----------|---------|
| `POLYMARKET_PRIVATE_KEY` | Ethereum private key for wallet signing |
| `POLYMARKET_ADDRESS` | Wallet address |
| `POLYMARKET_API_KEY` | CLOB API key |
| `POLYMARKET_API_PASSPHRASE` | CLOB API passphrase |
| `POLYMARKET_API_SECRET` | CLOB API secret |
| `GAMMA_API_BASE` | Gamma API URL |
| `TELEGRAM_BOT_TOKEN` | Telegram notification |

## Dependencies

| Package | Purpose |
|---------|---------|
| `httpx` | Async HTTP client for Polymarket + Gamma APIs |
| `numpy` | Numeric computation for calibration |
| `python-dotenv` | Environment variable loading |
| `scikit-learn` | ML calibration models |

## Governance Fields

Each trading decision carries governance metadata:

- `spread` — market spread in basis points
- `confidence_multiplier` — calibrated confidence score [0–1]
- `regime_factor` — current regime multiplier
- `tier_cap` — position tier cap

## Paper Trading → Live

Phase 2a (paper trading) runs by default. To enable Phase 2b live trading:

1. Set `ENABLE_LIVE = True` in `auto_trader_v2.py`
2. Provide funded wallet credentials via env vars
3. Restart the paper trade daemon

## License

MIT — see [LICENSE](LICENSE) for full text.
