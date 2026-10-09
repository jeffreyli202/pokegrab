from pathlib import Path

import pytest

from pokegrab.config import load_settings

ROOT = Path(__file__).resolve().parents[1]


def test_example_config_loads():
    settings = load_settings(ROOT / "config.example.yaml", load_env=False)
    assert "elite trainer box" in settings.keywords
    assert settings.poll_seconds == 180
    assert settings.price_min == 10
    assert settings.price_max is None
    assert settings.stores["target"] is True


def test_poll_interval_is_at_least_one_minute(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("poll_seconds: 5\nkeywords:\n  - tin\n", encoding="utf-8")
    settings = load_settings(path, load_env=False)
    assert settings.poll_seconds == 60


def test_keywords_are_required(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("keywords: []\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_settings(path, load_env=False)
