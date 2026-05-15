# Deploy Guide — openmsaify-trading

Three deployment options available.

---

## Option A: systemd (recommended)

```bash
# One-command deploy
bash /root/openmsaify/deploy/deploy.sh

# Manual
cp /root/openmsaify/deploy/paper-trade.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now paper-trade
journalctl -u paper-trade -f
```

Service auto-restarts on crash with exponential backoff (5s → 300s cap).
PID file: `/root/openmsaify/daemon.pid`
Logs: `journalctl -u paper-trade` + `/root/openmsaify/paper_trade_daemon.log`

---

## Option B: Docker

```bash
# Build
docker build -f /root/openmsaify/deploy/Dockerfile -t openmsaify-paper:latest /root/openmsaify/deploy/

# Run (bind-mount config + env)
docker run -d --name paper-trade \
  --env-file /root/openmsaify/.env \
  -v /root/openmsaify/paper_trade_daemon.log:/app/paper_trade_daemon.log \
  openmsaify-paper:latest

# Logs
docker logs -f paper-trade
```

---

## Option C: Direct (foreground / cron)

```bash
# Foreground
python3 /root/openmsaify/trading/execution/nanoclaw_paper_trade.py

# Cron (every 5 min)
*/5 * * * * /usr/bin/python3 /root/openmsaify/trading/execution/nanoclaw_paper_trade.py >> /root/openmsaify/cron.log 2>&1
```

---

## Environment Variables

| Variable | Required | Purpose |
|----------|----------|---------|
| `POLYMARKET_PRIVATE_KEY` | no | Wallet private key |
| `POLYMARKET_ADDRESS` | no | Wallet address |
| `POLYMARKET_API_KEY` | no | CLOB API key |
| `POLYMARKET_API_SECRET` | no | CLOB secret |
| `POLYMARKET_API_PASSPHRASE` | no | CLOB passphrase |
| `GAMMA_API_BASE` | no | Gamma API URL |
| `TELEGRAM_BOT_TOKEN` | no | Notification bot |

Without credentials the system runs in **paper trade mode** (no real funds).

---

## Package Import

```python
# pip install openmsaify-trading  (from /root/pip install -e .)
from trading.execution import Nanoclaw, PaperTradeEngine, PositionSizing, RiskManagement
from trading.signal import AutoTraderV2, MispricingScanner
from trading.context import RegimeEngine, NarrativeEngine
from trading.decision import EnsembleCalibrator, AntiDelusionFilter

# Backward compat
from auto_trader_v2 import AutoTrader
from nanoclaw import Nanoclaw, ClobClient
```
