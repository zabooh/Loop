#!/usr/bin/env python3
"""
project_config.py — read the values written by setup_flasher.py.

The test tools call flasher_port() for their default `--port`, so once
setup_flasher.py has been run the whole tool-chain finds the board without any
command-line arguments. Falls back to COM12 if the config is absent.
"""
import json
import os

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FLASHER_CONFIG = os.path.join(_HERE, "setup_flasher.config")


def _load(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def flasher_port(default="COM12"):
    """Serial console port of the Curiosity Nano (from setup_flasher.config)."""
    return _load(FLASHER_CONFIG).get("com_port") or default


def flasher_serial(default=None):
    """Debugger serial of the Curiosity Nano, or *default* if unknown."""
    return _load(FLASHER_CONFIG).get("serial") or default
