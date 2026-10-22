"""Console-style Big Picture UI and a zero-dependency Linux joystick reader."""
from __future__ import annotations

import os
import struct
import time
from pathlib import Path
from typing import Any

from PyQt6.QtCore import (
    QEasingCurve,
    QObject,
    QPropertyAnimation,
    QRect,
    QRectF,
    QSocketNotifier,
    QSize,
    Qt,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QGuiApplication,
    QIcon,
    QKeyEvent,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PyQt6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from core import app_icon
from db import Database, scaling_label
from i18n import tr
from theme import get_theme

SOURCE_ROLE = int(Qt.ItemDataRole.UserRole) + 1


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


class ConsoleGameDelegate(QStyledItemDelegate):
    """Cinematic game tile: rounded art, glow, title and source badge."""

    def sizeHint(self, option: QStyleOptionViewItem, index) -> QSize:  # noqa: N802
        return QSize(258, 384)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        theme = get_theme()
        rect = QRectF(option.rect.adjusted(7, 7, -7, -7))
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        card = QPainterPath()
        card.addRoundedRect(rect, 15, 15)
        if selected:
            glow = QPainterPath()
            glow.addRoundedRect(rect.adjusted(-3, -3, 3, 3), 18, 18)
            glow_color = QColor(theme.accent)
            glow_color.setAlpha(55)
            painter.fillPath(glow, glow_color)
        painter.fillPath(
            card,
            QColor(theme.panel_alt if selected else theme.panel),
        )
        border = theme.accent if selected else (theme.accent_dim if hovered else theme.border)
        painter.setPen(QPen(QColor(border), 2.0 if selected else 1.0))
        painter.drawPath(card)

        cover_rect = QRectF(rect.left() + 13, rect.top() + 13, rect.width() - 26, rect.height() - 72)
        cover_path = QPainterPath()
        cover_path.addRoundedRect(cover_rect, 10, 10)
        painter.save()
        painter.setClipPath(cover_path)
        icon = index.data(Qt.ItemDataRole.DecorationRole)
        pixmap = icon.pixmap(QSize(420, 540)) if isinstance(icon, QIcon) else QPixmap()
        if pixmap.isNull():
            pixmap = app_icon(180).pixmap(180, 180)
        scaled = pixmap.scaled(
            cover_rect.size().toSize(),
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        source_x = max(0, (scaled.width() - int(cover_rect.width())) // 2)
        source_y = max(0, (scaled.height() - int(cover_rect.height())) // 2)
        painter.setOpacity(1.0 if selected else 0.88)
        painter.drawPixmap(
            cover_rect.toRect(),
            scaled,
            QRect(source_x, source_y, int(cover_rect.width()), int(cover_rect.height())),
        )
        painter.setOpacity(1.0)
        overlay = QLinearGradient(0, cover_rect.top(), 0, cover_rect.bottom())
        overlay.setColorAt(0.62, QColor(0, 0, 0, 0))
        overlay.setColorAt(1.0, QColor(0, 0, 0, 175))
        painter.fillRect(cover_rect, overlay)
        painter.restore()

        source = str(index.data(SOURCE_ROLE) or "")
        if source:
            badge_font = QFont("DejaVu Sans Mono", 7, QFont.Weight.Bold)
            painter.setFont(badge_font)
            metrics = QFontMetrics(badge_font)
            badge_width = metrics.horizontalAdvance(source) + 16
            badge_rect = QRectF(
                cover_rect.left() + 9,
                cover_rect.top() + 9,
                badge_width,
                20,
            )
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(5, 13, 17, 200))
            painter.drawRoundedRect(badge_rect, 5, 5)
            painter.setPen(QColor(theme.accent))
            painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, source)

        title = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        title_font = QFont("DejaVu Sans", 10, QFont.Weight.DemiBold)
        painter.setFont(title_font)
        painter.setPen(QColor(theme.text if selected else theme.muted))
        metrics = QFontMetrics(title_font)
        title_text = metrics.elidedText(title, Qt.TextElideMode.ElideRight, int(rect.width() - 28))
        painter.drawText(
            QRectF(rect.left() + 14, rect.bottom() - 47, rect.width() - 28, 30),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            title_text,
        )
        painter.restore()


class ConsoleWindow(QMainWindow):
    launch_requested = pyqtSignal(int)
    edit_requested = pyqtSignal(int)
    closed = pyqtSignal()

    def __init__(self, database: Database, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.db = database
        self._games: list[dict[str, Any]] = []
        self._cover_size = QSize(232, 318)
        self._backdrop_source: QPixmap | None = None
        self._details_animation: QPropertyAnimation | None = None
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
        root.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        root.setAutoFillBackground(False)
        self.setCentralWidget(root)
        self.backdrop = QLabel(root)
        self.backdrop.setObjectName("ConsoleBackdrop")
        self.backdrop.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._backdrop_effect = QGraphicsOpacityEffect(self.backdrop)
        self._backdrop_effect.setOpacity(0.36)
        self.backdrop.setGraphicsEffect(self._backdrop_effect)
        self.shade = QFrame(root)
        self.shade.setObjectName("ConsoleShade")
        self.shade.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(34, 22, 34, 20)
        layout.setSpacing(16)

        header = QFrame()
        header.setObjectName("ConsoleHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(16, 8, 16, 8)
        brand_box = QVBoxLayout()
        brand_box.setSpacing(0)
        brand = QLabel(tr("BOOSTLAYER // BIG PICTURE"))
        brand.setObjectName("ConsoleBrand")
        brand_box.addWidget(brand)
        brand_hint = QLabel(tr("KONSOLA GIER"))
        brand_hint.setObjectName("ConsoleKicker")
        brand_box.addWidget(brand_hint)
        header_layout.addLayout(brand_box)
        header_layout.addStretch(1)
        self.clock = QLabel("")
        self.clock.setObjectName("ConsoleClock")
        header_layout.addWidget(self.clock)
        self.pad_status = QLabel(tr("PAD: szukam..."))
        self.pad_status.setObjectName("ConsolePad")
        header_layout.addWidget(self.pad_status)
        close = QPushButton(tr("WYJDŹ  [B]"))
        close.setObjectName("ConsoleGhost")
        close.clicked.connect(self.close_console)
        header_layout.addWidget(close)
        layout.addWidget(header)
        self._clock_timer = QTimer(self)
        self._clock_timer.setInterval(1000)
        self._clock_timer.timeout.connect(self._update_clock)
        self._update_clock()

        body = QHBoxLayout()
        body.setSpacing(20)
        self.tiles = QListWidget()
        self.tiles.setObjectName("ConsoleTiles")
        self.tiles.setViewMode(QListView.ViewMode.IconMode)
        self.tiles.setResizeMode(QListView.ResizeMode.Adjust)
        self.tiles.setMovement(QListView.Movement.Static)
        self.tiles.setSpacing(14)
        self.tiles.setIconSize(self._cover_size)
        self.tiles.setGridSize(QSize(258, 384))
        self.tiles.setUniformItemSizes(True)
        self.tiles.setWordWrap(True)
        self.tiles.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.tiles.setMouseTracking(True)
        self.tiles.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.tiles.viewport().setMouseTracking(True)
        self.tiles.viewport().setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.tiles.setItemDelegate(ConsoleGameDelegate(self.tiles))
        self.tiles.currentRowChanged.connect(lambda _row: self._update_details())
        self.tiles.itemDoubleClicked.connect(self._launch_item)
        body.addWidget(self.tiles, 1)

        details = QFrame()
        details.setObjectName("ConsoleDetails")
        details.setFixedWidth(380)
        details_layout = QVBoxLayout(details)
        details_layout.setContentsMargins(22, 20, 22, 20)
        details_layout.setSpacing(9)
        self.detail_kicker = QLabel(tr("WYBRANA GRA"))
        self.detail_kicker.setObjectName("ConsoleKicker")
        details_layout.addWidget(self.detail_kicker)
        self.cover = QLabel()
        self.cover.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cover.setFixedSize(270, 350)
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
        self.chips_frame = QFrame()
        self.chips_frame.setObjectName("ConsoleChips")
        chips = QGridLayout(self.chips_frame)
        chips.setContentsMargins(0, 4, 0, 0)
        chips.setHorizontalSpacing(6)
        chips.setVerticalSpacing(6)
        self.source_chip = QLabel("")
        self.scaling_chip = QLabel("")
        self.fps_chip = QLabel("")
        self.runner_chip = QLabel("")
        for chip in (
            self.source_chip,
            self.scaling_chip,
            self.fps_chip,
            self.runner_chip,
        ):
            chip.setObjectName("ConsoleChip")
        chips.addWidget(self.source_chip, 0, 0)
        chips.addWidget(self.fps_chip, 0, 1)
        chips.addWidget(self.scaling_chip, 1, 0)
        chips.addWidget(self.runner_chip, 1, 1)
        details_layout.addWidget(self.chips_frame)
        details_layout.addStretch(1)
        self.play = QPushButton(tr("▶  GRAJ  [A]"))
        self.play.setObjectName("ConsolePrimary")
        self.play.clicked.connect(self._launch_current)
        details_layout.addWidget(self.play)
        edit = QPushButton(tr("✎  EDYTUJ  [X]"))
        edit.setObjectName("ConsoleGhost")
        edit.clicked.connect(self._edit_current)
        details_layout.addWidget(edit)
        self._details_effect = QGraphicsOpacityEffect(details)
        details.setGraphicsEffect(self._details_effect)
        body.addWidget(details)
        layout.addLayout(body, 1)

        footer = QFrame()
        footer.setObjectName("ConsoleFooterBar")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(16, 6, 16, 6)
        footer_layout.setSpacing(8)
        footer_layout.addStretch(1)
        for key, label in (
            ("A", tr("Graj")),
            ("B", tr("Wyjdź")),
            ("X", tr("Edytuj")),
            ("Y", tr("Odśwież")),
            ("START", tr("Wyjdź")),
        ):
            key_label = QLabel(key)
            key_label.setObjectName("ConsoleKey")
            footer_layout.addWidget(key_label)
            text_label = QLabel(label)
            text_label.setObjectName("ConsoleKeyLabel")
            footer_layout.addWidget(text_label)
            footer_layout.addSpacing(14)
        footer_layout.addStretch(1)
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
            store = str(game.get("store", "") or "").upper()
            item.setData(
                SOURCE_ROLE,
                store
                or (
                    "AMAZON"
                    if game.get("is_amazon")
                    else ("STEAM" if game.get("is_steam") else "STANDALONE")
                ),
            )
            item.setToolTip(str(game.get("name", "")))
            item.setSizeHint(QSize(254, 380))
            self.tiles.addItem(item)
        if self._games:
            index = 0
            for i, game in enumerate(self._games):
                if selected_id is not None and int(game["id"]) == int(selected_id):
                    index = i
                    break
            self.tiles.setCurrentRow(index)
            self._update_details()
        else:
            self.title.setText(tr("Biblioteka jest pusta"))
            self.meta.setText(tr("Dodaj grę w normalnym widoku Boostlayera."))
            self.cover.setPixmap(app_icon(160).pixmap(160, 160))
            self.chips_frame.setVisible(False)
            self.detail_kicker.setText(tr("BIBLIOTEKA"))
            self._set_backdrop(None)
        self.setFocus()

    def _set_backdrop(self, pixmap: QPixmap | None) -> None:
        self._backdrop_source = pixmap
        self._refresh_backdrop()

    def _refresh_backdrop(self) -> None:
        if not hasattr(self, "backdrop"):
            return
        size = self.backdrop.size()
        if size.width() <= 0 or size.height() <= 0:
            return
        if self._backdrop_source is None or self._backdrop_source.isNull():
            self.backdrop.clear()
            return
        scaled = self._backdrop_source.scaled(
            size,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.backdrop.setPixmap(scaled)

    def _update_clock(self) -> None:
        if hasattr(self, "clock"):
            self.clock.setText(time.strftime("%H:%M"))

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
        store = str(game.get("store", "") or "").upper()
        source = (
            store
            or (
                "AMAZON"
                if game.get("is_amazon")
                else ("STEAM" if game.get("is_steam") else tr("STANDALONE"))
            )
        )
        if bits:
            source += f"  ·  {bits}-BIT"
        runner = Path(str(game.get("runner_path", ""))).name or "AUTO"
        fps = int(game.get("fps_limit", 0)) or 0
        self.meta.setText(tr("Naciśnij A, aby uruchomić, lub X, aby edytować."))
        self.detail_kicker.setText(tr("WYBRANA GRA"))
        self.source_chip.setText(source)
        self.scaling_chip.setText(
            scaling_label(str(game.get("scaling_mode", "native")))
        )
        self.fps_chip.setText(
            tr("{fps} FPS", fps=fps) if fps else tr("Bez limitu")
        )
        self.runner_chip.setText(tr("Runner: {name}", name=runner[:20]))
        self.runner_chip.setToolTip(runner)
        self.chips_frame.setVisible(True)
        cover = Path(str(game.get("cover_path", "") or "")).expanduser()
        pixmap: QPixmap | None = None
        if cover.is_file():
            icon = QIcon(str(cover))
            if not icon.isNull():
                pixmap = icon.pixmap(QSize(270, 350))
        if pixmap is None or pixmap.isNull():
            pixmap = app_icon(180).pixmap(180, 180)
        self.cover.setPixmap(
            pixmap.scaled(
                self.cover.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        self._set_backdrop(pixmap)
        effect = getattr(self, "_details_effect", None)
        if effect is not None:
            if self._details_animation is not None:
                self._details_animation.stop()
            effect.setOpacity(0.55)
            animation = QPropertyAnimation(effect, b"opacity", self)
            animation.setDuration(190)
            animation.setStartValue(0.55)
            animation.setEndValue(1.0)
            animation.setEasingCurve(QEasingCurve.Type.OutCubic)
            animation.start()
            self._details_animation = animation

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

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if hasattr(self, "backdrop"):
            self.backdrop.setGeometry(0, 0, self.width(), self.height())
            self.shade.setGeometry(0, 0, self.width(), self.height())
            self._refresh_backdrop()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._update_clock()
        self._clock_timer.start()
        self._refresh_backdrop()
        self.gamepad.start()
        self.reload()
        self.setFocus()

    def hideEvent(self, event) -> None:  # noqa: N802
        self._clock_timer.stop()
        self.gamepad.stop()
        super().hideEvent(event)

    def closeEvent(self, event) -> None:  # noqa: N802
        self.gamepad.stop()
        event.ignore()
        self.close_console()
