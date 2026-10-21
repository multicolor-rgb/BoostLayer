"""Console-style Big Picture UI and a zero-dependency Linux joystick reader."""
from __future__ import annotations

import os
import struct
import time
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QObject, QSocketNotifier, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QGuiApplication, QIcon, QKeyEvent
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from core import app_icon
from db import Database, scaling_label
from i18n import tr


def parse_js_event(data: bytes) -> tuple[int, int, int] | None:
    """Decode `struct js_event`: uint32 time, int16 value, uint8 type, uint8 number."""
    if len(data) < 8:
        return None
    _time, value, kind, number = struct.unpack_from("<IhBB", data)
    return kind, number, value


class GamepadManager(QObject):
    """Read /dev/input/js* without external Python packages."""

    button = pyqtSignal(int)
    axis = pyqtSignal(int, float)
    status = pyqtSignal(bool, str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._fd: int | None = None
        self._notifier: QSocketNotifier | None = None
        self._buffer = b""
        self._path = ""
        self._timer = QTimer(self)
        self._timer.setInterval(1600)
        self._timer.timeout.connect(self._scan)
        self._last_status: tuple[bool, str] | None = None

    def start(self) -> None:
        self._timer.start()
        self._scan()

    def stop(self) -> None:
        self._timer.stop()
        self._close()

    def _set_status(self, available: bool, text: str) -> None:
        if self._last_status != (available, text):
            self._last_status = (available, text)
            self.status.emit(available, text)

    def _close(self) -> None:
        if self._notifier is not None:
            self._notifier.setEnabled(False)
            self._notifier.deleteLater()
            self._notifier = None
        if self._fd is not None:
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None
        self._buffer = b""

    def _scan(self) -> None:
        if self._fd is not None:
            return
        candidates = sorted(Path("/dev/input").glob("js*"))
        if not candidates:
            self._set_status(False, tr("PAD: BRAK (/dev/input/js*)"))
            return
        for candidate in candidates:
            try:
                fd = os.open(candidate, os.O_RDONLY | os.O_NONBLOCK)
            except OSError:
                continue
            self._fd = fd
            self._path = str(candidate)
            self._buffer = b""
            self._notifier = QSocketNotifier(fd, QSocketNotifier.Type.Read, self)
            self._notifier.activated.connect(lambda _type: self._read())
            self._set_status(True, tr("PAD: {name}", name=candidate.name))
            return
        self._set_status(
            False,
            tr("PAD: brak dostępu do /dev/input/js* (użyj udev uaccess)"),
)

    def _read(self) -> None:
        if self._fd is None:
            return
        try:
            chunk = os.read(self._fd, 4096)
        except BlockingIOError:
            return
        except OSError:
            self._close()
            self._set_status(False, tr("PAD: rozłączony"))
            return
        if not chunk:
            self._close()
            self._set_status(False, tr("PAD: rozłączony"))
            return
        self._buffer += chunk
        while len(self._buffer) >= 8:
            event, self._buffer = self._buffer[:8], self._buffer[8:]
            parsed = parse_js_event(event)
            if parsed is None:
                continue
            kind, number, value = parsed
            if kind == 0x01:  # JS_EVENT_BUTTON
                if value:  # emit presses only, not releases
                    self.button.emit(number)
            elif kind == 0x02:  # JS_EVENT_AXIS
                self.axis.emit(number, max(-1.0, min(1.0, value / 32767.0)))


class ConsoleWindow(QMainWindow):
    launch_requested = pyqtSignal(int)
    edit_requested = pyqtSignal(int)
    closed = pyqtSignal()

    def __init__(self, database: Database, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.db = database
        self._games: list[dict[str, Any]] = []
        self._cover_size = QSize(220, 310)
        self._last_axis_at: dict[int, float] = {}
        self._monitor_index = 0
        self.setWindowTitle(tr("Boostlayer Console"))
        self.setWindowIcon(app_icon())
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setObjectName("ConsoleRoot")

        root = QWidget()
        root.setObjectName("ConsoleRoot")
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(34, 22, 34, 20)
        layout.setSpacing(16)

        header = QFrame()
        header.setObjectName("ConsoleHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(2, 0, 2, 0)
        brand = QLabel(tr("BOOSTLAYER // CONSOLE"))
        brand.setObjectName("ConsoleBrand")
        header_layout.addWidget(brand)
        header_layout.addStretch(1)
        self.pad_status = QLabel(tr("PAD: szukam..."))
        self.pad_status.setObjectName("ConsoleMuted")
        header_layout.addWidget(self.pad_status)
        close = QPushButton(tr("WYJDŹ  [B]"))
        close.setObjectName("ConsoleGhost")
        close.clicked.connect(self.close_console)
        header_layout.addWidget(close)
        layout.addWidget(header)

        body = QHBoxLayout()
        body.setSpacing(20)
        self.tiles = QListWidget()
        self.tiles.setObjectName("ConsoleTiles")
        self.tiles.setViewMode(QListView.ViewMode.IconMode)
        self.tiles.setResizeMode(QListView.ResizeMode.Adjust)
        self.tiles.setMovement(QListView.Movement.Static)
        self.tiles.setSpacing(12)
        self.tiles.setIconSize(self._cover_size)
        self.tiles.setGridSize(QSize(250, 370))
        self.tiles.setUniformItemSizes(True)
        self.tiles.setWordWrap(True)
        self.tiles.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.tiles.currentRowChanged.connect(lambda _row: self._update_details())
        self.tiles.itemDoubleClicked.connect(self._launch_item)
        body.addWidget(self.tiles, 1)

        details = QFrame()
        details.setObjectName("ConsoleDetails")
        details.setFixedWidth(350)
        details_layout = QVBoxLayout(details)
        details_layout.setContentsMargins(20, 20, 20, 20)
        details_layout.setSpacing(10)
        self.cover = QLabel()
        self.cover.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cover.setFixedSize(250, 330)
        self.cover.setObjectName("ConsoleCover")
        details_layout.addWidget(self.cover, 0, Qt.AlignmentFlag.AlignHCenter)
        self.title = QLabel(tr("Wybierz grę"))
        self.title.setObjectName("ConsoleTitle")
        self.title.setWordWrap(True)
        details_layout.addWidget(self.title)
        self.meta = QLabel("")
        self.meta.setObjectName("ConsoleMuted")
        self.meta.setWordWrap(True)
        details_layout.addWidget(self.meta)
        details_layout.addStretch(1)
        self.play = QPushButton(tr("▶  GRAJ  [A]"))
        self.play.setObjectName("ConsolePrimary")
        self.play.clicked.connect(self._launch_current)
        details_layout.addWidget(self.play)
        edit = QPushButton(tr("✎  EDYTUJ  [X]"))
        edit.setObjectName("ConsoleGhost")
        edit.clicked.connect(self._edit_current)
        details_layout.addWidget(edit)
        body.addWidget(details)
        layout.addLayout(body, 1)

        footer = QLabel(
            tr("D-PAD / LEWA GAŁKA — wybór     A — graj     B — wyjdź     "
            "X — edytuj     Y — odśwież     START — wyjdź")
        )
        footer.setObjectName("ConsoleFooter")
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(footer)

        self.gamepad = GamepadManager(self)
        self.gamepad.status.connect(self._pad_status)
        self.gamepad.button.connect(self._button)
        self.gamepad.axis.connect(self._axis)
        self.reload()

    def _icon_for(self, game: dict[str, Any]) -> QIcon:
        cover = Path(str(game.get("cover_path", "") or "")).expanduser()
        if cover.is_file():
            icon = QIcon(str(cover))
            if not icon.isNull():
                return icon
        return app_icon(160)

    def reload(self) -> None:
        selected_id = None
        item = self.tiles.currentItem()
        if item is not None:
            selected_id = item.data(Qt.ItemDataRole.UserRole)
        self._games = self.db.list_games()
        self.tiles.clear()
        for game in self._games:
            item = QListWidgetItem(self._icon_for(game), str(game.get("name", "?")))
            item.setData(Qt.ItemDataRole.UserRole, int(game["id"]))
            item.setToolTip(str(game.get("name", "")))
            item.setSizeHint(QSize(246, 366))
            self.tiles.addItem(item)
        if self._games:
            index = 0
            for i, game in enumerate(self._games):
                if selected_id is not None and int(game["id"]) == int(selected_id):
                    index = i
                    break
            self.tiles.setCurrentRow(index)
        else:
            self.title.setText(tr("Biblioteka jest pusta"))
            self.meta.setText(tr("Dodaj grę w normalnym widoku Boostlayera."))
            self.cover.setPixmap(app_icon(160).pixmap(160, 160))
        self.setFocus()

    def _current_game(self) -> dict[str, Any] | None:
        item = self.tiles.currentItem()
        if item is None:
            return None
        game_id = item.data(Qt.ItemDataRole.UserRole)
        for game in self._games:
            if int(game["id"]) == int(game_id):
                return game
        return None

    def _update_details(self) -> None:
        game = self._current_game()
        if game is None:
            return
        self.title.setText(str(game.get("name", "")))
        bits = game.get("_bits")
        if bits is None:
            from core import exe_bits

            bits = exe_bits(str(game.get("exe_path", "")))
        source = (
            f"STEAM  {game.get('steam_appid', '')}"
            if game.get("is_steam")
            else "STANDALONE"
        )
        if bits:
            source += f"  //  {bits}-BIT"
        runner = Path(str(game.get("runner_path", ""))).name or "AUTO"
        self.meta.setText(
            f"{source}\n"
            f"{tr('Skalowanie: {label}', label=scaling_label(str(game.get('scaling_mode', 'native'))))}\n"
            f"FPS: {int(game.get('fps_limit', 0)) or '∞'}\n"
            f"Runner: {runner}"
        )
        cover = Path(str(game.get("cover_path", "") or "")).expanduser()
        if cover.is_file():
            pixmap = QIcon(str(cover)).pixmap(QSize(250, 330))
            self.cover.setPixmap(pixmap)
        else:
            self.cover.setPixmap(app_icon(160).pixmap(160, 160))

    def _move(self, dx: int, dy: int) -> None:
        count = self.tiles.count()
        if count == 0:
            return
        row = self.tiles.currentRow()
        grid_width = max(1, self.tiles.gridSize().width())
        columns = max(1, self.tiles.viewport().width() // grid_width)
        new_row = row + dx + dy * columns
        self.tiles.setCurrentRow(max(0, min(count - 1, new_row)))
        self.setFocus()

    def _launch_current(self) -> None:
        game = self._current_game()
        if game is not None:
            self.launch_requested.emit(int(game["id"]))

    def _launch_item(self, item: QListWidgetItem) -> None:
        self.launch_requested.emit(int(item.data(Qt.ItemDataRole.UserRole)))

    def _edit_current(self) -> None:
        game = self._current_game()
        if game is not None:
            self.edit_requested.emit(int(game["id"]))

    def _pad_status(self, available: bool, text: str) -> None:
        self.pad_status.setText(text)
        self.pad_status.setProperty("available", available)
        self.pad_status.style().unpolish(self.pad_status)
        self.pad_status.style().polish(self.pad_status)

    def _button(self, number: int) -> None:
        if number == 0:
            self._launch_current()
        elif number in {1, 6, 7}:
            self.close_console()
        elif number == 2:
            self._edit_current()
        elif number == 3:
            self.reload()
        elif number == 4:
            self._move(-1, 0)
        elif number == 5:
            self._move(1, 0)

    def _axis(self, number: int, value: float) -> None:
        if abs(value) < 0.55:
            self._last_axis_at.pop(number, None)
            return
        now = time.monotonic()
        if now - self._last_axis_at.get(number, 0.0) < 0.16:
            return
        self._last_axis_at[number] = now
        if number in {0, 6}:
            self._move(1 if value > 0 else -1, 0)
        elif number in {1, 7}:
            self._move(0, 1 if value > 0 else -1)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        key = event.key()
        if key in {Qt.Key.Key_Left, Qt.Key.Key_A}:
            self._move(-1, 0)
        elif key in {Qt.Key.Key_Right, Qt.Key.Key_D}:
            self._move(1, 0)
        elif key in {Qt.Key.Key_Up, Qt.Key.Key_W}:
            self._move(0, -1)
        elif key in {Qt.Key.Key_Down, Qt.Key.Key_S}:
            self._move(0, 1)
        elif key in {Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space}:
            self._launch_current()
        elif key in {Qt.Key.Key_Escape, Qt.Key.Key_Backspace}:
            self.close_console()
        elif key == Qt.Key.Key_F5:
            self.reload()
        else:
            super().keyPressEvent(event)

    def open_on_screen(self, screen_index: int = 0) -> None:
        screens = QGuiApplication.screens()
        if screens:
            self._monitor_index = max(0, min(len(screens) - 1, int(screen_index)))
            self.setGeometry(screens[self._monitor_index].geometry())
        self.showFullScreen()
        self.raise_()
        self.activateWindow()
        self.setFocus()

    def close_console(self) -> None:
        self.hide()
        self.closed.emit()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self.gamepad.start()
        self.reload()
        self.setFocus()

    def hideEvent(self, event) -> None:  # noqa: N802
        self.gamepad.stop()
        super().hideEvent(event)

    def closeEvent(self, event) -> None:  # noqa: N802
        self.gamepad.stop()
        event.ignore()
        self.close_console()
