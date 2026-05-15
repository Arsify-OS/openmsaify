#!/usr/bin/env python3
"""
Paper Trade Daemon — runs nanoclaw_paper_trade.py in a loop.
Restarts on failure, logs to file + Telegram.
Usage:
  python daemon.py                    # foreground
  python daemon.py --daemon           # background with PID file
  python daemon.py --stop              # stop running daemon
"""

import os
import sys
import time
import signal
import subprocess
import logging
from pathlib import Path
from datetime import datetime, timezone

# ── Config ────────────────────────────────────────────────────────────────
BASE = Path("/root/openmsaify")
PID_FILE = BASE / "daemon.pid"
LOG_FILE = BASE / "paper_trade_daemon.log"
ENTRYPOINT = BASE / "trading/execution/nanoclaw_paper_trade.py"
POLL_INTERVAL = 30  # seconds between restarts on error
MAX_BACKOFF = 300   # 5 min cap

# ── Logging ──────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("daemon")


def is_running() -> bool:
    if not PID_FILE.exists():
        return False
    try:
        pid = int(PID_FILE.read_text().strip())
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, ValueError):
        PID_FILE.unlink(missing_ok=True)
        return False


def start():
    if is_running():
        log.warning("Daemon already running (PID %s)", PID_FILE.read_text().strip())
        return
    
    log.info("Starting paper trade daemon...")
    pid = os.fork()
    if pid > 0:
        sys.exit(0)  # parent exits
    
    # Child — daemonize
    os.setsid()
    PID_FILE.write_text(str(os.getpid()))
    
    backoff = 5
    while True:
        try:
            log.info("Launching %s", ENTRYPOINT.name)
            result = subprocess.run(
                [sys.executable, str(ENTRYPOINT)],
                capture_output=False,
                text=False,
                cwd=BASE,
            )
            log.warning("Entrypoint exited with code %s", result.returncode)
        except Exception as e:
            log.error("Fatal error: %s", e)
        
        log.info("Restarting in %ds...", backoff)
        time.sleep(backoff)
        backoff = min(backoff * 2, MAX_BACKOFF)
        log.info("Backoff: %ds", backoff)


def stop():
    if not PID_FILE.exists():
        print("Daemon not running.")
        return
    pid = int(PID_FILE.read_text().strip())
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
        print(f"Stopped daemon (PID {pid})")
        PID_FILE.unlink(missing_ok=True)
    except ProcessLookupError:
        print(f"Process {pid} already dead.")
        PID_FILE.unlink(missing_ok=True)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Paper Trade Daemon")
    parser.add_argument("--daemon", action="store_true", help="Run in background")
    parser.add_argument("--stop", action="store_true", help="Stop running daemon")
    args = parser.parse_args()

    if args.daemon:
        start()
    elif args.stop:
        stop()
    else:
        # Foreground — run once then exit (for systemd)
        backoff = 5
        while True:
            try:
                log.info("Running %s (foreground)", ENTRYPOINT.name)
                result = subprocess.run(
                    [sys.executable, str(ENTRYPOINT)],
                    capture_output=False,
                    cwd=BASE,
                )
                log.warning("Exited with code %s, restarting in %ds...", result.returncode, backoff)
            except Exception as e:
                log.error("Error: %s, restarting in %ds...", e, backoff)
            time.sleep(backoff)
