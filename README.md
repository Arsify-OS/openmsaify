# OpenMSAify Trading Engine

> Polymarket prediction market trading engine — decision → signal → context → execution → feedback

**Version:** 0.1.0
**License:** MIT
**Python:** ≥ 3.11

---

## Overview

`openmsaify-trading` is a structured, layered trading engine built for [Polymarket](https://polymymarket.com). It transforms raw market data into calibrated trading decisions through five composable layers:

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
| **Execution** | Order routing, risk management, CLOB client | `nanoclaw`, `paper_trade_engine`, `position_sizing`, `risk_management` |
| **Feedback** | Performance tracking & dashboard | `performance_dashboard` |

## Quick Start

### Install

```bash
pip install openmsaify-trading
# or from source
pip install -e .
```

### Import

```python
from trading.execution import Nanoclaw, PaperTradeEngine, PositionSizing, RiskManagement
from trading.signal import AutoTraderV2, MispricingScanner
from trading.context import RegimeEngine, NarrativeEngine
from trading.decision import EnsembleCalibrator, AntiDelusionFilter
```

### Run Paper Trading

```bash
python trading/execution/nanoclaw_paper_trade.py
```

## Branch Structure

This repository has two branches:

| Branch | Visibility | Contents |
|--------|-----------|---------|
| `main` | PRIVATE | Full internal codebase (live trading, configs, data pipelines) |
| `open` | PUBLIC | Public package — `trading/` + docs only |

Clone `open` branch for package use:
```bash
git clone -b open --single-branch https://github.com/Arsify-OS/openmsaify.git
```

## Configuration

Set via environment variables or `.env` file:

| Variable | Purpose |
|----------|---------|
| `POLYMARKET_WALLET_KEY` | Ethereum private key for order signing |
| `POLYMARKET_WALLET_ADDRESS` | Your wallet address |
| `POLYMARKET_CLOB_API_KEY` | CLOB API key |
| `POLYMARKET_CLOB_PASSPHRASE` | CLOB API signature passphrase |
| `POLYMARKET_CLOB_SECRET` | CLOB API secret |
| `GAMMA_API_BASE` | Gamma API URL (default: https://gamma-api.polymarket.com) |
| `TELEGRAM_BOT_TOKEN` | Optional: Telegram notification |

Without credentials the engine runs in **paper trading mode** (no real funds).

## Dependencies

| Package | Purpose |
|---------|---------|
| `httpx` | Async HTTP client API access |
| `numpy` | Numerical computation for models |
| `python-dotenv` | Environment loading |
| `scikit-learn` | ML calibration models |

## License

MIT — see [LICENSE](LICENSE) for full text.
