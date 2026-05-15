"""
mispricing_scanner — Polymarket Trading Engine
Part of openmsaify-trading (MIT License)
Copyright (c) 2025 OpenMSAify
"""

"""Backward-compatibility shim — DO NOT EDIT. Auto-generated."""
import sys
from importlib import import_module

TARGET = "trading.signal.mispricing_scanner"

if __name__ == "__main__":
    import runpy
    runpy.run_module(TARGET, run_name="__main__", alter_sys=True)
else:
    _mod = import_module(TARGET)
    globals().update(_mod.__dict__)
