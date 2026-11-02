"""The Recent Stimulation Programs list scrolls both ways with the wheel,
a touchpad (small pixel steps) and the scrollbar, whatever Qt style is in
use. It once got stuck when scrolling back up on Windows."""

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

from PySide6.QtCore import QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QWheelEvent  # noqa: E402
from PySide6.QtWidgets import QAbstractItemView, QApplication, QStyleFactory  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def menu(app, tmp_path):
    from ui.main_menu import MainMenuWindow

    recent = tmp_path / "recent.json"
    recent.write_text(json.dumps({"recent_programs": [
        {"name": f"Program {i}", "description": "desc", "last_run": "Not run yet", "file_path": ""}
        for i in range(10)
    ]}), encoding="utf-8")
    with patch("ui.main_menu.RECENT_PROGRAMS_FILE", recent):
        window = MainMenuWindow()
        window.resize(960, 800)
        window.show()
        app.processEvents()
        yield window
        window.close()


def _wheel(app, widget, pixels, angle):
    event = QWheelEvent(QPointF(40, 40), QPointF(40, 40), QPoint(0, pixels), QPoint(0, angle),
                        Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
    app.sendEvent(widget.viewport(), event)
    app.processEvents()


def test_list_scrolls_by_pixel_with_a_visible_scrollbar(menu):
    lst = menu.recent_list
    assert lst.verticalScrollMode() == QAbstractItemView.ScrollPerPixel
    assert lst.verticalScrollBar().maximum() > 0
    assert lst.verticalScrollBar().isVisible()


@pytest.mark.parametrize("pixels, angle", [(0, 120), (6, 12)])  # mouse wheel, touchpad
def test_scrolls_down_and_back_up(app, menu, pixels, angle):
    lst, bar = menu.recent_list, menu.recent_list.verticalScrollBar()
    for _ in range(200):
        _wheel(app, lst, -pixels, -angle)
    assert bar.value() == bar.maximum()
    for _ in range(200):
        _wheel(app, lst, pixels, angle)
    assert bar.value() == 0


def test_scrollbar_drag_both_ways(menu):
    bar = menu.recent_list.verticalScrollBar()
    bar.setValue(bar.maximum())
    assert bar.value() == bar.maximum()
    bar.setValue(0)
    assert bar.value() == 0


@pytest.mark.parametrize("style", [s for s in ("Windows", "Fusion") if s in QStyleFactory.keys()])
def test_scrolls_back_up_in_other_styles(app, menu, style):
    old = app.style().name()
    app.setStyle(style)
    try:
        lst, bar = menu.recent_list, menu.recent_list.verticalScrollBar()
        for _ in range(200):
            _wheel(app, lst, -6, -12)
        assert bar.value() > 0
        for _ in range(200):
            _wheel(app, lst, 6, 12)
        assert bar.value() == 0
    finally:
        app.setStyle(old)


def test_selecting_the_last_program_scrolls_it_into_view_and_back(menu, app):
    lst = menu.recent_list
    lst.setCurrentRow(lst.count() - 1)
    app.processEvents()
    assert lst.verticalScrollBar().value() > 0
    lst.setCurrentRow(0)
    app.processEvents()
    assert lst.verticalScrollBar().value() == 0
