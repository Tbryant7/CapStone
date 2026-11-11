"""New Program screen: build a program from blocks, one tab per channel.

Works like Scratch: drag a block from the palette on the left (pulse width,
amplitude, frequency, or a "starter" block that adds all three) onto the
channel area, then set its number. Clicking a palette block adds it too.

Each channel has its own tab, like browser tabs: "+" adds a channel, the "x"
on a tab closes it, tabs can be dragged into a different order, and
right-clicking a tab offers "Duplicate channel" to build a new channel off an
existing one.

Total time, active channels and time step are the same three settings a
MATLAB stimulation file is built from (``files/stim_matrix.py``). With a total
time, each channel gets total time / time step + 1 values, and pulse width and
amplitude blocks can "ramp to" an end value. "Export .mat..." writes the
program in that MATLAB layout, which the Main Menu imports again.

The whole program is validated on every change (REQ-16). "Save Program..."
is only enabled when it passes, and it saves through ProgramFileManager, which
refuses unsafe programs anyway (REQ-17). After the first save, "Save" keeps
writing to the same file, and the Main Menu opens it ready to edit.

    window = NewProgramWindow(file_manager)
    window.program_saved.connect(main_menu.open_program_file)
    window.show()
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QMimeData, QPoint, Qt, Signal
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from files import Channel, Program, ProgramFileError, ProgramFileManager, TimeSeriesPoint
from files.stim_matrix import export_mat

#: Shared light theme (also keeps text readable in Windows dark mode).
MAIN_STYLE_FILE = Path(__file__).resolve().parent.parent / "ui" / "main_menu.qss"

#: Extra rules for this screen: Chrome-style channel tabs.
EDITOR_STYLE = """
QScrollArea, QScrollArea > QWidget > QWidget { background-color: #ffffff; }
QFrame#palette { background-color: #f2f5f8; border: 1px solid #c5ced8; border-radius: 8px; }
QTabWidget#channelTabs QTabBar { background: #ffffff; }
QTabWidget#channelTabs::pane { border: 1px solid #b8c6d4; border-top: none; background: #ffffff; }
QTabWidget#channelTabs QTabBar::tab {
    background: #dfe6ee; color: #333333; border: 1px solid #b8c6d4; border-bottom: none;
    border-top-left-radius: 9px; border-top-right-radius: 9px;
    padding: 7px 14px; margin-right: 2px; min-width: 90px;
}
QTabWidget#channelTabs QTabBar::tab:selected { background: #ffffff; font-weight: bold; }
QTabWidget#channelTabs QTabBar::tab:!selected { margin-top: 3px; }
QToolButton#addChannelButton {
    font-size: 16px; font-weight: bold; min-width: 30px; min-height: 26px;
    border: 1px solid #b8c6d4; border-radius: 13px; background: #e5edf5;
}
"""

#: Default folder for new programs (created on first save, not committed).
PROGRAMS_FOLDER = Path(__file__).resolve().parent.parent / "programs"

#: MIME type carried by a dragged palette block.
BLOCK_MIME = "application/x-cosmiic-block"

#: Ask before closing with unsaved changes. Tests turn this off.
CONFIRM_DISCARD = True

#: Most channels a program can have here (the WSS has up to 8 sockets).
MAX_CHANNEL_NUMBER = 32


@dataclass(frozen=True)
class BlockKind:
    key: str
    label: str           # "Pulse width"
    attribute: str       # Channel attribute it sets
    parameter: str       # RangeTable parameter that limits it
    unit: str
    decimals: int
    default: float       # starting value, if inside the safe range
    color: str           # Scratch-style block colour


BLOCKS = {
    kind.key: kind
    for kind in (
        BlockKind("pulse_width", "Pulse width", "pulse_width_us", "pulse_width", "µs", 0, 50, "#4c97ff"),
        BlockKind("amplitude", "Amplitude", "amplitude_ma", "amplitude", "mA", 2, 1.0, "#9966ff"),
        BlockKind("frequency", "Frequency", "frequency_hz", "frequency", "Hz", 1, 20, "#d98c00"),
    )
}

#: Blocks that can change over the total time (as in the .mat layout).
RAMPABLE = ("pulse_width", "amplitude")

#: Most time-series points per channel the screen will build.
MAX_POINTS = 100_000

#: A palette block that drops all three value blocks at once.
STARTER = "starter"
STARTER_COLOR = "#3f9c3f"

BLOCK_STYLE = """
QFrame#{name} {{
    background-color: {color};
    border: 2px solid {border};
    border-radius: 10px;
}}
QFrame#{name} QLabel {{ color: white; font-weight: bold; background: transparent; }}
"""


def _darker(color: str) -> str:
    value = int(color.lstrip("#"), 16)
    r, g, b = (value >> 16) & 255, (value >> 8) & 255, value & 255
    return "#{:02x}{:02x}{:02x}".format(int(r * 0.75), int(g * 0.75), int(b * 0.75))


# ---------------------------------------------------------------- palette


class PaletteBlock(QFrame):
    """A block in the palette. Drag it onto a channel, or click it."""

    clicked = Signal(str)

    def __init__(self, key: str, text: str, color: str, parent=None) -> None:
        super().__init__(parent)
        self.key = key
        name = f"palette_{key}"
        self.setObjectName(name)
        self.setStyleSheet(BLOCK_STYLE.format(name=name, color=color, border=_darker(color)))
        self.setCursor(Qt.OpenHandCursor)
        self.setToolTip("Drag onto the channel, or click to add it.")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.addWidget(QLabel(text))
        self._press: QPoint | None = None

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt name)
        if event.button() == Qt.LeftButton:
            self._press = event.position().toPoint()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 (Qt name)
        if self._press is None:
            return
        if (event.position().toPoint() - self._press).manhattanLength() < QApplication.startDragDistance():
            return
        self._press = None
        mime = QMimeData()
        mime.setData(BLOCK_MIME, self.key.encode())
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.setPixmap(self.grab())
        drag.setHotSpot(event.position().toPoint())
        drag.exec(Qt.CopyAction)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 (Qt name)
        if self._press is not None and event.button() == Qt.LeftButton:
            self.clicked.emit(self.key)
        self._press = None


# ---------------------------------------------------------------- channel


class ValueBlock(QFrame):
    """A placed block: "set amplitude to [1.00] mA  x".

    With a total time set, pulse width and amplitude blocks can also "ramp
    to" an end value: a straight line from the start value at t = 0 to the
    end value at the total time.
    """

    changed = Signal()
    removed = Signal(object)

    def __init__(self, kind: BlockKind, value: float, parent=None) -> None:
        super().__init__(parent)
        self.kind = kind
        name = f"block_{kind.key}"
        self.setObjectName(name)
        self.setStyleSheet(BLOCK_STYLE.format(name=name, color=kind.color, border=_darker(kind.color)))

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 6, 6, 6)
        layout.addWidget(QLabel(f"set {kind.label.lower()} to"))
        self.spin = QDoubleSpinBox()
        self.spin.setObjectName(f"{kind.key}Value")
        self.spin.setDecimals(kind.decimals)
        self.spin.setRange(0, 100000)  # the ValidationEngine judges what is safe
        self.spin.setSingleStep(1 if kind.decimals == 0 else 0.1)
        self.spin.setValue(value)
        self.spin.setMinimumWidth(90)
        self.spin.valueChanged.connect(lambda _v: self.changed.emit())
        layout.addWidget(self.spin)
        layout.addWidget(QLabel(kind.unit))

        self.ramp_box = QCheckBox("ramp to")
        self.ramp_box.setObjectName(f"{kind.key}Ramp")
        self.ramp_box.setStyleSheet("QCheckBox { color: white; font-weight: bold; background: transparent; }")
        self.end_spin = QDoubleSpinBox()
        self.end_spin.setObjectName(f"{kind.key}End")
        self.end_spin.setDecimals(kind.decimals)
        self.end_spin.setRange(0, 100000)
        self.end_spin.setSingleStep(1 if kind.decimals == 0 else 0.1)
        self.end_spin.setValue(value)
        self.end_spin.setMinimumWidth(90)
        self.end_spin.setEnabled(False)
        self.end_unit = QLabel(kind.unit)
        self.ramp_box.toggled.connect(self.end_spin.setEnabled)
        self.ramp_box.toggled.connect(lambda _on: self.changed.emit())
        self.end_spin.valueChanged.connect(lambda _v: self.changed.emit())
        for widget in (self.ramp_box, self.end_spin, self.end_unit):
            layout.addWidget(widget)
        self.can_ramp = kind.key in RAMPABLE
        self.set_timed(False)
        layout.addStretch()
        self.remove_button = QToolButton()
        self.remove_button.setText("✕")
        self.remove_button.setToolTip(f"Remove the {kind.label.lower()} block")
        self.remove_button.clicked.connect(lambda: self.removed.emit(self))
        layout.addWidget(self.remove_button)

    def value(self):
        return self._round(self.spin.value())

    def set_value(self, value) -> None:
        self.spin.setValue(value)

    def set_timed(self, timed: bool) -> None:
        """Show the ramp controls only when the program has a total time."""
        self.timed = timed and self.can_ramp
        for widget in (self.ramp_box, self.end_spin, self.end_unit):
            widget.setVisible(self.timed)

    def ramps(self) -> bool:
        return self.timed and self.ramp_box.isChecked()

    def set_ramp(self, end) -> None:
        self.end_spin.setValue(end)
        self.ramp_box.setChecked(True)

    def end_value(self):
        """The value at the end of the total time (the start value if it doesn't ramp)."""
        return self._round(self.end_spin.value()) if self.ramps() else self.value()

    def values(self, rows: int) -> list:
        """One value per time step: constant, or a straight-line ramp."""
        start, end = self.value(), self.end_value()
        if rows == 1 or start == end:
            return [start] * rows
        return [self._round(start + (end - start) * i / (rows - 1)) for i in range(rows)]

    def _round(self, value):
        value = round(value, self.kind.decimals)
        return int(value) if self.kind.decimals == 0 else value


class ChannelCanvas(QWidget):
    """One channel's tab: its WSS channel number and the blocks dropped on it."""

    changed = Signal()

    def __init__(self, number: int, ranges=None, parent=None) -> None:
        super().__init__(parent)
        self.ranges = ranges
        self.blocks: dict[str, ValueBlock] = {}
        self.timed = False
        self.setAcceptDrops(True)

        outer = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel("WSS channel:"))
        self.number_box = QSpinBox()
        self.number_box.setObjectName("channelNumber")
        self.number_box.setRange(1, MAX_CHANNEL_NUMBER)
        self.number_box.setValue(number)
        self.number_box.valueChanged.connect(lambda _v: self.changed.emit())
        top.addWidget(self.number_box)
        top.addStretch()
        outer.addLayout(top)

        self.drop_area = QFrame()
        self.drop_area.setObjectName("dropArea")
        self.drop_area.setStyleSheet(
            "QFrame#dropArea { border: 2px dashed #9aa7b4; border-radius: 10px; background: #f7f9fb; }"
        )
        self.stack = QVBoxLayout(self.drop_area)
        self.stack.setSpacing(6)
        self.hint = QLabel("Drag blocks here (or click them in the palette).\n"
                           "A channel needs pulse width, amplitude and frequency.")
        self.hint.setAlignment(Qt.AlignCenter)
        self.hint.setStyleSheet("color: #5a6672; border: none;")
        self.stack.addWidget(self.hint)
        self.stack.addStretch()
        outer.addWidget(self.drop_area, 1)

    # -------------------------------------------------- drag and drop

    def dragEnterEvent(self, event) -> None:  # noqa: N802 (Qt name)
        if event.mimeData().hasFormat(BLOCK_MIME):
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:  # noqa: N802 (Qt name)
        if event.mimeData().hasFormat(BLOCK_MIME):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802 (Qt name)
        if not event.mimeData().hasFormat(BLOCK_MIME):
            return
        self.add_block(bytes(event.mimeData().data(BLOCK_MIME)).decode())
        event.acceptProposedAction()

    # -------------------------------------------------- blocks

    def add_block(self, key: str, value=None) -> None:
        """Add a value block, or all three for the starter block.

        A channel has one block per value: adding one it already has just
        highlights the existing block instead of adding a second.
        """
        if key == STARTER:
            for kind in BLOCKS:
                if kind not in self.blocks:
                    self.add_block(kind)
            return
        kind = BLOCKS.get(key)
        if kind is None:
            return
        if key in self.blocks:
            self.blocks[key].spin.setFocus()
            self.blocks[key].spin.selectAll()
            return
        block = ValueBlock(kind, self._default(kind) if value is None else value)
        block.set_timed(self.timed)
        block.changed.connect(self.changed.emit)
        block.removed.connect(self._remove_block)
        self.blocks[key] = block
        self.stack.insertWidget(self.stack.count() - 1, block)  # above the stretch
        self.hint.setVisible(False)
        self.changed.emit()

    def _remove_block(self, block: ValueBlock) -> None:
        self.blocks.pop(block.kind.key, None)
        self.stack.removeWidget(block)
        block.deleteLater()
        self.hint.setVisible(not self.blocks)
        self.changed.emit()

    def _default(self, kind: BlockKind):
        """The block's usual value, or the middle of its safe range if that is outside it."""
        value = kind.default
        if self.ranges is not None:
            try:
                limit = self.ranges[kind.parameter]
            except KeyError:
                return value
            if not limit.contains(value):
                value = (limit.min + limit.max) / 2
        value = round(value, kind.decimals)
        return int(value) if kind.decimals == 0 else value

    # -------------------------------------------------- model

    def number(self) -> int:
        return self.number_box.value()

    def set_timed(self, timed: bool) -> None:
        """Turn the ramp controls on when the program has a total time."""
        self.timed = timed
        for block in self.blocks.values():
            block.set_timed(timed)

    def channel(self, rows: int | None = None, step_s: float | None = None) -> Channel:
        """This tab as a Channel; with ``rows``, also one time-series point per step."""
        values = {kind.attribute: None for kind in BLOCKS.values()}
        for key, block in self.blocks.items():
            values[BLOCKS[key].attribute] = block.value()
        channel = Channel(number=self.number(), **values)
        if rows and all(key in self.blocks for key in RAMPABLE):
            widths = self.blocks["pulse_width"].values(rows)
            amps = self.blocks["amplitude"].values(rows)
            channel.time_series = [
                TimeSeriesPoint(time_s=round(i * step_s, 9), pulse_width_us=pw, amplitude_ma=amp)
                for i, (pw, amp) in enumerate(zip(widths, amps))
            ]
        return channel

    def load(self, channel: Channel) -> None:
        """Add blocks with ``channel``'s values (a time series becomes a ramp)."""
        for key, kind in BLOCKS.items():
            value = getattr(channel, kind.attribute)
            if value is None:
                continue
            self.add_block(key, value)
            points = channel.time_series
            if key in RAMPABLE and points:
                end = getattr(points[-1], kind.attribute)
                if end != value:
                    self.blocks[key].set_ramp(end)

    def has_problem(self) -> bool:
        if len(self.blocks) < len(BLOCKS):
            return True
        if self.ranges is None:
            return False
        return any(
            not self.ranges[BLOCKS[key].parameter].contains(value)
            for key, block in self.blocks.items()
            for value in (block.value(), block.end_value())
        )


# ---------------------------------------------------------------- window


class NewProgramWindow(QMainWindow):
    """SDS Screen 2: build a new program, one channel per tab."""

    #: Emitted with the file path every time the program is saved.
    program_saved = Signal(object)

    def __init__(self, file_manager: ProgramFileManager | None = None, parent=None) -> None:
        super().__init__(parent)
        self.file_manager = file_manager or ProgramFileManager()
        self.ranges = self.file_manager.engine.ranges
        self.path: Path | None = None
        self.dirty = False
        self.problems: list[str] = []

        self.setWindowTitle("COSMIIC - New Program")
        self.setMinimumSize(900, 620)
        self.resize(1000, 680)
        style = MAIN_STYLE_FILE.read_text(encoding="utf-8") if MAIN_STYLE_FILE.exists() else ""
        self.setStyleSheet(style + EDITOR_STYLE)
        self._build()
        self.add_channel()          # start with one channel holding the starter blocks
        self.current_canvas().add_block(STARTER)
        self.dirty = False
        self._refresh()

    def _build(self) -> None:
        root = QWidget(self)
        layout = QVBoxLayout(root)

        title = QLabel("New Stimulation Program")
        title.setObjectName("editorHeader")
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        layout.addWidget(title)

        # Program details
        form = QFormLayout()
        self.name_edit = QLineEdit()
        self.name_edit.setObjectName("programNameEdit")
        self.name_edit.setPlaceholderText("e.g. Wrist extension")
        self.description_edit = QLineEdit()
        self.description_edit.setObjectName("programDescriptionEdit")
        self.description_edit.setPlaceholderText("Optional")
        self.time_step_box = QSpinBox()
        self.time_step_box.setObjectName("timeStepBox")
        self.time_step_box.setRange(0, 100000)
        self.time_step_box.setSuffix(" ms")
        step = self.ranges["time_step"]
        self.time_step_box.setValue(50 if step.contains(50) else int((step.min + step.max) / 2))
        # The three settings a MATLAB stimulation file is built from
        # (files/stim_matrix.py): total time, active channels, time step.
        self.total_time_box = QDoubleSpinBox()
        self.total_time_box.setObjectName("totalTimeBox")
        self.total_time_box.setRange(0, 3600)
        self.total_time_box.setDecimals(3)
        self.total_time_box.setSingleStep(0.5)
        self.total_time_box.setSuffix(" s")
        self.total_time_box.setSpecialValueText("None (values stay constant)")
        self.total_time_box.setToolTip(
            "Total time length. With a total time, pulse width and amplitude can ramp, "
            "and each channel gets total time / time step + 1 values."
        )
        self.channel_count_box = QSpinBox()
        self.channel_count_box.setObjectName("channelCountBox")
        self.channel_count_box.setRange(0, MAX_CHANNEL_NUMBER)
        self.channel_count_box.setToolTip("Number of active channels (one tab each)")
        self.channel_count_box.valueChanged.connect(self.set_channel_count)
        self.shape_label = QLabel()
        self.shape_label.setObjectName("shapeLabel")
        self.shape_label.setStyleSheet("color: #5a6672;")

        form.addRow("Program name:", self.name_edit)
        form.addRow("Description:", self.description_edit)
        form.addRow("Total time:", self.total_time_box)
        form.addRow("Active channels:", self.channel_count_box)
        form.addRow("Time step:", self.time_step_box)
        form.addRow("", self.shape_label)
        layout.addLayout(form)
        for signal in (self.name_edit.textChanged, self.description_edit.textChanged,
                       self.time_step_box.valueChanged, self.total_time_box.valueChanged):
            signal.connect(self._changed)

        # Palette | channel tabs
        middle = QHBoxLayout()
        palette = QFrame()
        palette.setObjectName("palette")
        palette.setFixedWidth(220)
        palette_layout = QVBoxLayout(palette)
        palette_layout.addWidget(QLabel("<b>Blocks</b>"))
        self.palette_blocks: dict[str, PaletteBlock] = {}
        for key, text, color in (
            [(STARTER, "Starter: all three", STARTER_COLOR)]
            + [(kind.key, f"{kind.label} ({kind.unit})", kind.color) for kind in BLOCKS.values()]
        ):
            block = PaletteBlock(key, text, color)
            block.clicked.connect(lambda k: self.current_canvas() and self.current_canvas().add_block(k))
            self.palette_blocks[key] = block
            palette_layout.addWidget(block)
        tip = QLabel("Drag a block onto the channel, or click it. Right-click a tab to "
                     "duplicate a channel.")
        tip.setWordWrap(True)
        tip.setStyleSheet("color: #5a6672;")
        palette_layout.addWidget(tip)
        palette_layout.addStretch()
        middle.addWidget(palette)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("channelTabs")
        self.tabs.setDocumentMode(True)
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.tabCloseRequested.connect(self.close_channel)
        self.tabs.tabBar().tabMoved.connect(lambda *_: self._changed())
        self.tabs.tabBar().setContextMenuPolicy(Qt.CustomContextMenu)
        self.tabs.tabBar().customContextMenuRequested.connect(self._tab_menu)
        self.add_tab_button = QToolButton()
        self.add_tab_button.setObjectName("addChannelButton")
        self.add_tab_button.setText("+")
        self.add_tab_button.setToolTip("Add a channel")
        self.add_tab_button.clicked.connect(lambda: self.add_channel())
        self.tabs.setCornerWidget(self.add_tab_button, Qt.TopRightCorner)
        middle.addWidget(self.tabs, 1)
        layout.addLayout(middle, 1)

        # Validation and save
        self.validation_label = QLabel()
        self.validation_label.setObjectName("validationResult")
        layout.addWidget(self.validation_label)
        self.problems_label = QLabel()
        self.problems_label.setObjectName("validationProblems")
        self.problems_label.setWordWrap(True)
        self.problems_label.setStyleSheet("color: #b00020;")
        layout.addWidget(self.problems_label)

        buttons = QHBoxLayout()
        self.save_status_label = QLabel()
        self.save_status_label.setObjectName("saveStatus")
        buttons.addWidget(self.save_status_label, 1)
        self.save_button = QPushButton("Save Program...")
        self.save_button.setObjectName("saveProgramButton")
        self.save_button.clicked.connect(self.save)
        self.save_as_button = QPushButton("Save As...")
        self.save_as_button.clicked.connect(lambda: self.save(ask_path=True))
        self.save_as_button.hide()
        self.export_button = QPushButton("Export .mat...")
        self.export_button.setObjectName("exportMatButton")
        self.export_button.setToolTip("Save in the MATLAB stimulation-matrix layout (docs/MATLAB_IMPORT.md)")
        self.export_button.clicked.connect(self.export_mat)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.close)
        for button in (self.save_button, self.save_as_button, self.export_button, close_button):
            button.setFixedHeight(34)
            buttons.addWidget(button)
        layout.addLayout(buttons)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(root)
        self.setCentralWidget(scroll)

    # -------------------------------------------------- channels (tabs)

    def canvases(self) -> list[ChannelCanvas]:
        """Channel tabs in their on-screen order."""
        return [self.tabs.widget(i) for i in range(self.tabs.count())]

    def current_canvas(self) -> ChannelCanvas | None:
        return self.tabs.currentWidget()

    def add_channel(self, copy_from: ChannelCanvas | None = None) -> ChannelCanvas:
        """Add a channel tab with the lowest unused channel number."""
        used = {canvas.number() for canvas in self.canvases()}
        number = next(n for n in range(1, MAX_CHANNEL_NUMBER + 2) if n not in used)
        canvas = ChannelCanvas(min(number, MAX_CHANNEL_NUMBER), self.ranges)
        rows, _ = self.timing()
        canvas.set_timed(rows is not None)
        if copy_from is not None:
            canvas.load(copy_from.channel(rows, self._step_s()))
        canvas.changed.connect(self._changed)
        index = self.tabs.addTab(canvas, "")
        self.tabs.setCurrentIndex(index)
        self._changed()
        return canvas

    def duplicate_channel(self, index: int) -> ChannelCanvas:
        """New tab with the same values as tab ``index``, to build off it."""
        return self.add_channel(copy_from=self.tabs.widget(index))

    def close_channel(self, index: int) -> None:
        widget = self.tabs.widget(index)
        self.tabs.removeTab(index)
        if widget is not None:
            widget.deleteLater()
        self._changed()

    def set_channel_count(self, count: int) -> None:
        """Add or remove tabs (from the end) until there are ``count`` channels."""
        while self.tabs.count() < count:
            self.add_channel()
        while self.tabs.count() > count:
            self.close_channel(self.tabs.count() - 1)

    def _tab_menu(self, position) -> None:
        index = self.tabs.tabBar().tabAt(position)
        if index < 0:
            return
        menu = QMenu(self)
        duplicate = menu.addAction("Duplicate channel")
        close = menu.addAction("Close channel")
        chosen = menu.exec(self.tabs.tabBar().mapToGlobal(position))
        if chosen is duplicate:
            self.duplicate_channel(index)
        elif chosen is close:
            self.close_channel(index)

    # -------------------------------------------------- program

    def timing(self) -> tuple[int | None, str | None]:
        """``(rows, problem)``: points per channel for the total time, or why not.

        ``rows`` is None with no total time (constant values). As in the
        MATLAB layout, rows = total time / time step + 1.
        """
        total_s, step_ms = self.total_time_box.value(), self.time_step_box.value()
        if total_s <= 0 or step_ms <= 0:
            return None, None
        exact = total_s * 1000.0 / step_ms
        steps = round(exact)
        if abs(exact - steps) > 1e-6 * max(1.0, exact):
            return None, (f"Total time {total_s:g} s is not a whole number of {step_ms} ms "
                          "time steps. Change the total time or the time step.")
        if steps + 1 > MAX_POINTS:
            return None, (f"{steps + 1} points per channel is more than {MAX_POINTS}. "
                          "Use a shorter total time or a longer time step.")
        return steps + 1, None

    def _step_s(self) -> float:
        return self.time_step_box.value() / 1000.0

    def program(self) -> Program:
        rows, _ = self.timing()
        return Program(
            name=self.name_edit.text().strip(),
            description=self.description_edit.text().strip(),
            time_step_ms=self.time_step_box.value(),
            channels=[canvas.channel(rows, self._step_s()) for canvas in self.canvases()],
        )

    def _changed(self) -> None:
        self.dirty = True
        self._refresh()

    def _refresh(self) -> None:
        """Re-check the program and update tab titles, messages and the Save button."""
        rows, timing_problem = self.timing()
        count = self.tabs.count()
        for i, canvas in enumerate(self.canvases()):
            canvas.set_timed(rows is not None)
            mark = "  ⚠" if canvas.has_problem() else ""
            self.tabs.setTabText(i, f"Channel {canvas.number()}{mark}")

        self.channel_count_box.blockSignals(True)
        self.channel_count_box.setValue(count)
        self.channel_count_box.blockSignals(False)
        if rows is None:
            self.shape_label.setText(
                "No total time: each channel holds one set of values. Set a total time to "
                "ramp values over time."
            )
        else:
            self.shape_label.setText(
                f"{rows} time steps (total time / time step + 1) x {count} channel"
                f"{'s' if count != 1 else ''}, like a MATLAB stim matrix."
            )

        program = self.program()
        problems = [] if program.name else ["Give the program a name."]
        if timing_problem:
            problems.append(timing_problem)
        problems += self.file_manager.engine.validate(program).failed_parameters
        self.problems = problems

        if problems:
            count = len(problems)
            self.validation_label.setText(
                f"Validation: Failed ({count} problem{'s' if count != 1 else ''}). "
                "Fix these to save."
            )
            self.validation_label.setStyleSheet("color: #b00020; font-weight: bold;")
            self.problems_label.setText("\n".join(f"• {p}" for p in problems))
            self.problems_label.show()
        else:
            self.validation_label.setText("Validation: Passed. Ready to save.")
            self.validation_label.setStyleSheet("color: #2d6a1f; font-weight: bold;")
            self.problems_label.hide()
        self.save_button.setEnabled(not problems)
        self.save_as_button.setEnabled(not problems)
        self.export_button.setEnabled(not problems)

        if self.path is not None:
            state = "unsaved changes" if self.dirty else "saved"
            self.save_status_label.setText(f"{self.path.name}: {state}")
        title = self.path.name if self.path else "New Program"
        self.setWindowTitle(f"COSMIIC - {title}{' *' if self.dirty else ''}")

    def save(self, ask_path: bool = False) -> bool:
        """Save the program. Asks for a file the first time (or for Save As)."""
        if self.problems:
            QMessageBox.warning(self, "Not saved", "Fix these first:\n" + "\n".join(self.problems))
            return False
        path = self.path
        if path is None or ask_path:
            PROGRAMS_FOLDER.mkdir(parents=True, exist_ok=True)
            suggested = PROGRAMS_FOLDER / f"{_file_name(self.name_edit.text())}.json"
            chosen, _ = QFileDialog.getSaveFileName(
                self, "Save program", str(suggested), "JSON Files (*.json)"
            )
            if not chosen:
                return False
            path = Path(chosen)
            if path.suffix.lower() != ".json":
                path = path.with_suffix(".json")
        try:
            self.file_manager.save(self.program(), path)
        except ProgramFileError as ex:
            QMessageBox.warning(self, "Not saved", str(ex))
            return False
        self.path = path
        self.dirty = False
        self.save_button.setText("Save")
        self.save_as_button.show()
        self._refresh()
        self.program_saved.emit(path)
        return True

    def export_mat(self) -> Path | None:
        """Save a .mat file in the stimulation-matrix layout. Only when it passes."""
        program = self.program()
        if self.problems or not self.file_manager.engine.validate(program).is_valid:
            QMessageBox.warning(self, "Not exported", "Fix these first:\n" + "\n".join(self.problems))
            return None
        PROGRAMS_FOLDER.mkdir(parents=True, exist_ok=True)
        suggested = PROGRAMS_FOLDER / f"{_file_name(program.name)}.mat"
        chosen, _ = QFileDialog.getSaveFileName(
            self, "Export MATLAB file", str(suggested), "MATLAB Files (*.mat)"
        )
        if not chosen:
            return None
        path = Path(chosen)
        if path.suffix.lower() != ".mat":
            path = path.with_suffix(".mat")
        try:
            export_mat(program, path)
        except (OSError, ValueError) as ex:
            QMessageBox.warning(self, "Not exported", f"Could not write {path.name}: {ex}")
            return None
        self.save_status_label.setText(f"Exported {path.name}")
        return path

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt name)
        if self.dirty and CONFIRM_DISCARD:
            answer = QMessageBox.question(
                self, "Unsaved changes",
                "This program has changes that aren't saved. Close anyway?",
                QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Cancel,
            )
            if answer != QMessageBox.Discard:
                event.ignore()
                return
        super().closeEvent(event)


def _file_name(name: str) -> str:
    """Turn a program name like "Wrist extension #2" into "wrist_extension_2"."""
    slug = re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")
    return slug or "new_program"
