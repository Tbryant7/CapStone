"""Shared pytest setup.

Qt windows created by the GUI tests must be destroyed while the
QApplication still exists. Otherwise Python may tear them down after it
during interpreter shutdown, which crashes the process (segfault / bus
error) even though every test passed. This hook cleans them up at the end
of the session.
"""

from __future__ import annotations

import gc
import sys


def pytest_sessionfinish(session, exitstatus):
    if "PySide6.QtWidgets" not in sys.modules:
        return
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        return
    for widget in QApplication.topLevelWidgets():
        widget.close()
        widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    app.processEvents()
    gc.collect()
