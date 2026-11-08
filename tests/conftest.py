"""Shared test setup."""

import os
from pathlib import Path

import pytest

# The desktop app's tests draw windows without a screen ("offscreen"), so they also run on CI
# servers and never pop up a window on a developer's desktop. Qt reads this when it starts.
os.environ["QT_QPA_PLATFORM"] = "offscreen"


@pytest.fixture(autouse=True)
def _isolated_settings(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Point the saved settings and notes at empty temp files, so no test touches real ones."""
    folder: Path = tmp_path_factory.mktemp("settings")
    monkeypatch.setenv("WOW_COACH_CONFIG_FILE", str(folder / "config.json"))
    monkeypatch.setenv("WOW_COACH_NOTES_FILE", str(folder / "coach-notes.md"))
    # Everything else wow-coach keeps (settings, conversations, the usage log...) goes here.
    monkeypatch.setenv("WOW_COACH_DATA_DIR", str(folder / "data"))
