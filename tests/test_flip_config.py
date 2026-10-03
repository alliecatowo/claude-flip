import json

import pytest

import flip_config


def test_env_var_wins(monkeypatch):
    monkeypatch.setenv("CLAUDE_FLIP_MAC", "11:22:33:44:55:66")
    assert flip_config.get_flipper_address() == "11:22:33:44:55:66"


def test_legacy_env_var_is_honoured(monkeypatch):
    monkeypatch.delenv("CLAUDE_FLIP_MAC")
    monkeypatch.setenv("FLIPPER_ADDRESS", "AA:AA:AA:AA:AA:AA")
    assert flip_config.get_flipper_address() == "AA:AA:AA:AA:AA:AA"


def test_config_file_is_used_when_env_is_unset(monkeypatch, isolated_home):
    monkeypatch.delenv("CLAUDE_FLIP_MAC")
    cfg = isolated_home / "cfg.json"
    cfg.write_text(json.dumps({"address": "CC:CC:CC:CC:CC:CC"}))
    monkeypatch.setattr(flip_config, "CONFIG_PATH", cfg)
    assert flip_config.get_flipper_address() == "CC:CC:CC:CC:CC:CC"


def test_missing_address_exits_with_help(monkeypatch, isolated_home, capsys):
    monkeypatch.delenv("CLAUDE_FLIP_MAC")
    monkeypatch.setattr(flip_config, "CONFIG_PATH", isolated_home / "nope.json")
    with pytest.raises(SystemExit) as exit_info:
        flip_config.get_flipper_address()
    assert exit_info.value.code == 1
    assert "not configured" in capsys.readouterr().err


def test_not_required_returns_none(monkeypatch, isolated_home):
    monkeypatch.delenv("CLAUDE_FLIP_MAC")
    monkeypatch.setattr(flip_config, "CONFIG_PATH", isolated_home / "nope.json")
    assert flip_config.get_flipper_address(required=False) is None


def test_private_log_path_honours_xdg_state_home(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    assert flip_config.private_log_path("a.log") == tmp_path / "xdg" / "claude-flip" / "a.log"
    monkeypatch.delenv("XDG_STATE_HOME")
    assert flip_config.private_log_path("a.log").parts[-4:-1] == (".local", "state", "claude-flip")
