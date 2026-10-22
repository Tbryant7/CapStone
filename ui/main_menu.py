
"""Screen 1: COSMIIC Main Menu (SDS Figure 4.2)."""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

RECENT_PROGRAMS_FILE = (
    Path(__file__).resolve().parent.parent / "config" / "recent_programs.json"
)

STYLE_FILE = Path(__file__).resolve().parent / "main_menu.qss"


class MainMenuWindow(QMainWindow):
    """Screen 1 main menu based on SDS Figure 4.2."""

    def __init__(self) -> None:
        super().__init__()

        self.setWindowTitle("COSMIIC - Main Menu")
        self.setMinimumSize(900, 600)
        self.resize(900, 650)

        self._recent_programs = []

        self._build()
        self._load_recent_programs()

    def _build(self) -> None:
        root = QWidget(self)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Main header
        title = QLabel("COSMIIC Stimulation Software")
        title.setObjectName("mainHeader")
        title.setAlignment(Qt.AlignCenter)
        title.setFixedHeight(55)
        layout.addWidget(title)

        # Main content
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(15, 10, 15, 10)
        body_layout.setSpacing(10)

        # Beginner / Advanced mode
        mode_layout = QHBoxLayout()

        self.beginner_button = QPushButton("Beginner Mode")
        self.advanced_button = QPushButton("Advanced Mode")

        for button in (self.beginner_button, self.advanced_button):
            button.setCheckable(True)
            button.setFixedWidth(145)
            button.setFixedHeight(32)

        self.beginner_button.setChecked(True)

        self.beginner_button.clicked.connect(
            lambda: self._select_mode("Beginner")
        )
        self.advanced_button.clicked.connect(
            lambda: self._select_mode("Advanced")
        )

        mode_layout.addWidget(self.beginner_button)
        mode_layout.addWidget(self.advanced_button)
        mode_layout.addStretch()
        body_layout.addLayout(mode_layout)

        # Recent Programs and right panel
        content_layout = QHBoxLayout()
        content_layout.setSpacing(20)

        recent_group = QGroupBox("Recent Stimulation Programs")
        recent_layout = QVBoxLayout(recent_group)

        self.recent_list = QListWidget()
        self.recent_list.setObjectName("recentProgramsList")
        recent_layout.addWidget(self.recent_list)

        self.recent_list.currentRowChanged.connect(
            self._show_program_details
        )

        content_layout.addWidget(recent_group, 3)

        # Description panel
        right_panel = QVBoxLayout()
        right_panel.setSpacing(15)

        description_group = QGroupBox("Description")
        description_group.setFixedHeight(160)

        description_layout = QVBoxLayout(description_group)

        self.description_label = QLabel(
            "Select a recent program to view its details."
        )
        self.description_label.setWordWrap(True)
        self.description_label.setAlignment(Qt.AlignTop)

        description_layout.addWidget(self.description_label)
        right_panel.addWidget(description_group)

        # Four Main Menu buttons
        button_layout = QGridLayout()
        button_layout.setSpacing(10)

        self.new_button = QPushButton("New Program")
        self.import_button = QPushButton("Import Program / MATLAB File")
        self.open_button = QPushButton("Open Selected")
        self.help_button = QPushButton("Documentation / Help")

        # Names used by the QSS stylesheet
        self.new_button.setObjectName("newProgramButton")
        self.import_button.setObjectName("importProgramButton")
        self.open_button.setObjectName("openSelectedButton")
        self.help_button.setObjectName("helpButton")

        for button in (
            self.new_button,
            self.import_button,
            self.open_button,
            self.help_button,
        ):
            button.setFixedHeight(38)

        button_layout.addWidget(self.new_button, 0, 0)
        button_layout.addWidget(self.import_button, 0, 1)
        button_layout.addWidget(self.open_button, 1, 0)
        button_layout.addWidget(self.help_button, 1, 1)

        right_panel.addLayout(button_layout)
        right_panel.addStretch()

        content_layout.addLayout(right_panel, 2)
        body_layout.addLayout(content_layout, 1)
        layout.addWidget(body, 1)

        # Bottom device status
        self.status_label = QLabel("Device status: Not connected")
        self.status_label.setObjectName("deviceStatus")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setFixedHeight(38)

        status_container = QWidget()
        status_layout = QHBoxLayout(status_container)
        status_layout.setContentsMargins(15, 5, 15, 15)
        status_layout.addWidget(self.status_label)

        layout.addWidget(status_container)

        # Finish building the window
        self.setCentralWidget(root)

        # Load all styling from the separate QSS file
        if STYLE_FILE.exists():
            with STYLE_FILE.open("r", encoding="utf-8") as file:
                self.setStyleSheet(file.read())
        else:
            QMessageBox.warning(
                self,
                "Stylesheet Missing",
                "Could not find ui/main_menu.qss.",
            )

        # Connect the four buttons
        self.new_button.clicked.connect(self._coming_soon)
        self.help_button.clicked.connect(self._coming_soon)
        self.import_button.clicked.connect(self._choose_program_file)
        self.open_button.clicked.connect(self._open_selected_program)

    def _select_mode(self, mode: str) -> None:
        """Allow only one mode to be selected."""
        self.beginner_button.setChecked(mode == "Beginner")
        self.advanced_button.setChecked(mode == "Advanced")

    def _coming_soon(self) -> None:
        """Show a placeholder for future features."""
        QMessageBox.information(
            self,
            "Coming soon",
            "Coming soon",
        )

    def _load_recent_programs(self) -> None:
        """Read saved recent programs and display them."""
        self.recent_list.clear()
        self._recent_programs = []

        if not RECENT_PROGRAMS_FILE.exists():
            return

        try:
            with RECENT_PROGRAMS_FILE.open(
                "r", encoding="utf-8"
            ) as file:
                settings = json.load(file)

            programs = settings.get("recent_programs", [])

            if not isinstance(programs, list):
                raise ValueError("Recent programs must be a list")

            self._recent_programs = [
                program
                for program in programs
                if isinstance(program, dict)
            ]

            for program in self._recent_programs:
                name = program.get("name", "Unknown Program")
                description = program.get(
                    "description", "No description"
                )
                last_run = program.get(
                    "last_run", "Not available"
                )

                self.recent_list.addItem(
                    f"{name}\n{description}\nLast run: {last_run}"
                )

        except (OSError, ValueError, TypeError):
            self._recent_programs = []
            self.recent_list.clear()

    def _show_program_details(self, row: int) -> None:
        """Show details when a recent program is selected."""
        if row < 0 or row >= len(self._recent_programs):
            self.description_label.setText(
                "Select a recent program to view its details."
            )
            return

        program = self._recent_programs[row]

        self.description_label.setText(
            f"Program: {program.get('name', 'Unknown')}\n\n"
            f"Description: {program.get('description', 'No description available.')}\n\n"
            f"Last Run: {program.get('last_run', 'Not available')}"
        )

    def _save_recent_program(
        self,
        name: str,
        description: str,
        last_run: str,
    ) -> None:
        """Save a recently opened program to the settings file."""
        try:
            programs = []

            if RECENT_PROGRAMS_FILE.exists():
                with RECENT_PROGRAMS_FILE.open(
                    "r", encoding="utf-8"
                ) as file:
                    settings = json.load(file)

                programs = settings.get("recent_programs", [])

                if not isinstance(programs, list):
                    raise ValueError("Recent programs must be a list")

            # Remove any older entry with the same name
            programs = [
                program
                for program in programs
                if isinstance(program, dict)
                and program.get("name") != name
            ]

            # Put the newest program at the top
            programs.insert(
                0,
                {
                    "name": name,
                    "description": description,
                    "last_run": last_run,
                },
            )

            RECENT_PROGRAMS_FILE.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            with RECENT_PROGRAMS_FILE.open(
                "w", encoding="utf-8"
            ) as file:
                json.dump(
                    {"recent_programs": programs},
                    file,
                    indent=2,
                )

            self._load_recent_programs()

        except (OSError, ValueError, TypeError):
            QMessageBox.warning(
                self,
                "Save Error",
                "Unable to save the recent programs list.",
            )

    def _choose_program_file(self) -> None:
        """Open a file picker to select a program."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Import Program / MATLAB File",
            "",
            "Program Files (*.json *.mat);;JSON Files (*.json);;MATLAB Files (*.mat)",
        )

        if not file_path:
            return

        QMessageBox.information(
            self,
            "Program Selected",
            f"Selected file: {Path(file_path).name}\n\n"
            "Program loading will be available after "
            "ProgramFileManager integration.",
        )

    def _open_selected_program(self) -> None:
        """Handle opening a selected recent program."""
        row = self.recent_list.currentRow()

        if row < 0 or row >= len(self._recent_programs):
            QMessageBox.information(
                self,
                "No Program Selected",
                "Please select a recent program first.",
            )
            return

        QMessageBox.information(
            self,
            "Program Opening",
            "Program loading will be connected "
            "when ProgramFileManager is ready.",
        )
