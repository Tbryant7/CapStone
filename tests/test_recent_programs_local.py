"""The recent programs list is per person: it is not in Git, so the Main Menu
must start cleanly when the file doesn't exist yet and create it on first use."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWidgets")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_menu_starts_with_empty_recent_list_when_file_is_missing(app, tmp_path):
    from ui.main_menu import MainMenuWindow

    missing = tmp_path / "recent_programs.json"
    with patch("ui.main_menu.RECENT_PROGRAMS_FILE", missing):
        window = MainMenuWindow()
        assert window.recent_list.count() == 0
        assert not missing.exists()  # opening the menu alone doesn't create it
        window.close()


def test_first_opened_program_creates_the_file(app, tmp_path):
    from ui.main_menu import MainMenuWindow

    recent = tmp_path / "recent_programs.json"
    with patch("ui.main_menu.RECENT_PROGRAMS_FILE", recent):
        window = MainMenuWindow()
        assert window.open_program_file(ROOT / "samples" / "valid_1_channel.json")
        data = json.loads(recent.read_text(encoding="utf-8"))
        assert data["recent_programs"][0]["name"] == "Single channel test"
        window.close()


def test_recent_programs_file_is_ignored_by_git():
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "config/recent_programs.json" in ignored
