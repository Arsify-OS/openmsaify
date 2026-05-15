#!/usr/bin/env bash
# ── Deploy: systemd service + enable + start ─────────────────────────────────
set -euo pipefail

BASE="/root/openmsaify"
SERVICE="paper-trade.service"
SYSTEMD="/etc/systemd/system/${SERVICE}"

echo "=== DEPLOY: openmsaify-trading ==="

# 1. Copy systemd unit
echo "[1/4] Installing systemd unit → ${SYSTEMD}"
cp "${BASE}/deploy/${SERVICE}" "$SYSTEMD"
systemctl daemon-reload

# 2. Enable + start
echo "[2/4] Enabling + starting service..."
systemctl enable --now "$SERVICE"
systemctl is-active --quiet "$SERVICE" && echo "  ✅ Service running" || echo "  ❌ Service failed"

# 3. Status
echo "[3/4] Service status:"
systemctl status "$SERVICE" --no-pager -l | head -10

# 4. Recent logs
echo "[4/4] Recent daemon logs:"
journalctl -u "$SERVICE" --no-pager -n 15 --since "5 min ago" || echo "(no recent logs)"

echo ""
echo "Commands:"
echo "  status:  systemctl status $SERVICE"
echo "  logs:    journalctl -u $SERVICE -f"
echo "  stop:    systemctl stop $SERVICE"
echo "  restart: systemctl restart $SERVICE"
