"""Shared test setup: make scripts/ importable and keep tests off the real machine."""

import os
import sys

import pytest

SCRIPTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts")
sys.path.insert(0, SCRIPTS)

# permission_hook reads the Flipper address at import time and exits if it is unset.
os.environ.setdefault("CLAUDE_FLIP_MAC", "AA:BB:CC:DD:EE:FF")

# tests/hardware holds manual BLE probes that need a real Flipper; never collect them.
collect_ignore = ["hardware"]


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Point HOME/XDG at a temp dir so no test touches ~/.claude or ~/.config."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.delenv("FLIPPER_ADDRESS", raising=False)
    monkeypatch.setenv("CLAUDE_FLIP_MAC", "AA:BB:CC:DD:EE:FF")
    return tmp_path
