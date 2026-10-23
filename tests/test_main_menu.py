
import os
import sys
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from PySide6.QtWidgets import QApplication
from ui.main_menu import MainMenuWindow


class TestMainMenu(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_main_menu_opens(self):
        window = MainMenuWindow()

        self.assertEqual(
            window.windowTitle(),
            "COSMIIC - Main Menu"
        )
        self.assertIsNotNone(window.recent_list)
        self.assertIsNotNone(window.description_label)

        window.close()

    def test_mode_toggle(self):
        window = MainMenuWindow()

        # Beginner Mode is selected by default.
        self.assertTrue(window.beginner_button.isChecked())
        self.assertFalse(window.advanced_button.isChecked())

        # Switch to Advanced Mode.
        window._select_mode("Advanced")
        self.assertFalse(window.beginner_button.isChecked())
        self.assertTrue(window.advanced_button.isChecked())

        # Switch back to Beginner Mode.
        window._select_mode("Beginner")
        self.assertTrue(window.beginner_button.isChecked())
        self.assertFalse(window.advanced_button.isChecked())

        window.close()

    def test_recent_program_saving(self):
        with tempfile.TemporaryDirectory() as folder:
            settings_file = Path(folder) / "recent_programs.json"

            with patch("ui.main_menu.RECENT_PROGRAMS_FILE", settings_file):
                window = MainMenuWindow()

                window._save_recent_program(
                    "Test Program",
                    "Testing recent programs",
                    "2026-10-23",
                    "/example/test_program.json",
                )

                with settings_file.open("r", encoding="utf-8") as file:
                    data = json.load(file)

                program = data["recent_programs"][0]

                self.assertEqual(program["name"], "Test Program")
                self.assertEqual(
                    program["description"],
                    "Testing recent programs"
                )
                self.assertEqual(program["last_run"], "2026-10-23")
                self.assertEqual(
                    program["file_path"],
                    "/example/test_program.json"
                )

                self.assertEqual(window.recent_list.count(), 1)

                window.close()

    def test_recent_program_display(self):
        with tempfile.TemporaryDirectory() as folder:
            settings_file = Path(folder) / "recent_programs.json"

            with settings_file.open("w", encoding="utf-8") as file:
                json.dump({
                    "recent_programs": [{
                        "name": "Test Program",
                        "description": "Four-channel test",
                        "last_run": "2026-10-23",
                        "file_path": "/example/test.json"
                    }]
                }, file)

            with patch("ui.main_menu.RECENT_PROGRAMS_FILE", settings_file):
                window = MainMenuWindow()

                self.assertEqual(window.recent_list.count(), 1)

                item_text = window.recent_list.item(0).text()
                self.assertIn("Test Program", item_text)
                self.assertIn("Four-channel test", item_text)
                self.assertIn("2026-10-23", item_text)

                window.recent_list.setCurrentRow(0)

                self.assertIn(
                    "Four-channel test",
                    window.description_label.text()
                )

                window.close()


if __name__ == "__main__":
    unittest.main()
