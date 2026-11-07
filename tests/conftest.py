"""Shared test setup."""

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolated_settings(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Point the saved settings at an empty temp file, so a test never reads the real one."""
    folder: Path = tmp_path_factory.mktemp("settings")
    monkeypatch.setenv("WOW_COACH_CONFIG_FILE", str(folder / "config.json"))
