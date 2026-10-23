"""Console-style Big Picture UI and a zero-dependency Linux joystick reader."""
from __future__ import annotations

import os
import struct
import time
from pathlib import Path
from typing import Any

from PyQt6.QtCore import (
    QEasingCurve,
    QEvent,
    QObject,
    QPropertyAnimation,
    QRect,
    QRectF,
    QSocketNotifier,
    QSize,
    Qt,
    QTimer,
    QVariantAnimation,
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
    QRadialGradient,
)
from PyQt6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
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
    """Carousel tile: the selected cover grows with a glow, neighbours recede."""

    COVER_W = 192
    COVER_H = 256

    def sizeHint(self, option: QStyleOptionViewItem, index) -> QSize:  # noqa: N802
        return QSize(212, 318)

    def _pixmap_for(self, index) -> QPixmap:
        icon = index.data(Qt.ItemDataRole.DecorationRole)
        pixmap = icon.pixmap(QSize(480, 640)) if isinstance(icon, QIcon) else QPixmap()
        if pixmap.isNull():
            pixmap = app_icon(256).pixmap(256, 256)
        return pixmap

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        theme = get_theme()
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        base = QRectF(option.rect)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        grow = 12.0 if selected else 0.0
        left = base.left() + (base.width() - self.COVER_W) / 2.0
        cover = QRectF(left, base.top() + 8, self.COVER_W, self.COVER_H).adjusted(
            -grow * 0.75, -grow, grow * 0.75, grow
        )
        radius = 16.0

        if selected:
            accent = QColor(theme.accent)
            for step in range(4, 0, -1):
                halo = cover.adjusted(-step * 4, -step * 4, step * 4, step * 4)
                color = QColor(accent)
                color.setAlpha(18 + (4 - step) * 14)
                path = QPainterPath()
                path.addRoundedRect(halo, radius + step * 4, radius + step * 4)
                painter.fillPath(path, color)

        clip = QPainterPath()
        clip.addRoundedRect(cover, radius, radius)
        painter.setOpacity(1.0 if selected else 0.62)
        painter.save()
        painter.setClipPath(clip)
        pixmap = self._pixmap_for(index)
        scaled = pixmap.scaled(
            cover.size().toSize(),
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        source_x = max(0, (scaled.width() - int(cover.width())) // 2)
        source_y = max(0, (scaled.height() - int(cover.height())) // 2)
        painter.drawPixmap(
            cover.toRect(),
            scaled,
            QRect(source_x, source_y, int(cover.width()), int(cover.height())),
        )
        shade = QLinearGradient(0, cover.top(), 0, cover.bottom())
        shade.setColorAt(0.55, QColor(0, 0, 0, 0))
        shade.setColorAt(1.0, QColor(0, 0, 0, 165))
        painter.fillRect(cover, shade)
        painter.restore()

        border = QColor(theme.accent) if selected else QColor(255, 255, 255, 30)
        painter.setPen(QPen(border, 2.2 if selected else 1.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(clip)

        source = str(index.data(SOURCE_ROLE) or "")
        if source:
            badge_font = QFont("DejaVu Sans", 7, QFont.Weight.Bold)
            painter.setFont(badge_font)
            badge_width = QFontMetrics(badge_font).horizontalAdvance(source) + 16
            badge = QRectF(cover.left() + 10, cover.top() + 10, badge_width, 20)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(0, 0, 0, 170))
            painter.drawRoundedRect(badge, 6, 6)
            painter.setPen(QColor(255, 255, 255, 230))
            painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, source)

        title = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        font = QFont("DejaVu Sans")
        font.setPixelSize(16 if selected else 14)
        font.setWeight(QFont.Weight.DemiBold if selected else QFont.Weight.Normal)
        painter.setFont(font)
        painter.setPen(QColor(theme.text if selected else theme.muted))
        text_rect = QRectF(base.left() + 6, cover.bottom() + 10, base.width() - 12, 26)
        elided = QFontMetrics(font).elidedText(title, Qt.TextElideMode.ElideRight, int(text_rect.width()))
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, elided)
        painter.restore()


class ConsoleBackdrop(QWidget):
    """Cinematic background: a blurred cover that cross-fades on selection."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._current: QPixmap | None = None
        self._previous: QPixmap | None = None
        self._progress = 1.0
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(520)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutSine)
        self._anim.valueChanged.connect(self._on_progress)

    def set_source(self, pixmap: QPixmap | None) -> None:
        self._previous = self._current
        self._current = pixmap
        self._anim.stop()
        self._anim.start()

    def _on_progress(self, value) -> None:
        self._progress = float(value)
        self.update()

    def _draw(self, painter: QPainter, pixmap: QPixmap, opacity: float) -> None:
        scaled = pixmap.scaled(
            self.size(),
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        x = max(0, (scaled.width() - self.width()) // 2)
        y = max(0, (scaled.height() - self.height()) // 2)
        painter.setOpacity(max(0.0, min(1.0, opacity)))
        painter.drawPixmap(self.rect(), scaled, QRect(x, y, self.width(), self.height()))
        painter.setOpacity(1.0)

    def paintEvent(self, event) -> None:  # noqa: N802
        theme = get_theme()
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(theme.background_dark))
        if self._previous is not None and self._progress < 1.0:
            self._draw(painter, self._previous, 1.0 - self._progress)
        if self._current is not None:
            self._draw(painter, self._current, self._progress)
        width, height = float(self.width()), float(self.height())
        left = QLinearGradient(0, 0, width, 0)
        left.setColorAt(0.0, QColor(8, 8, 10, 232))
        left.setColorAt(0.5, QColor(8, 8, 10, 150))
        left.setColorAt(1.0, QColor(8, 8, 10, 96))
        painter.fillRect(self.rect(), left)
        bottom = QLinearGradient(0, height * 0.5, 0, height)
        bottom.setColorAt(0.0, QColor(0, 0, 0, 0))
        bottom.setColorAt(1.0, QColor(theme.background_dark))
        painter.fillRect(self.rect(), bottom)
        glow = QRadialGradient(width * 0.78, height * 0.34, width * 0.42)
        accent = QColor(theme.accent)
        accent.setAlpha(64)
        glow.setColorAt(0.0, accent)
        accent.setAlpha(0)
        glow.setColorAt(1.0, accent)
        painter.fillRect(self.rect(), glow)
        painter.end()


class ConsoleWindow(QMainWindow):
    launch_requested = pyqtSignal(int)
    edit_requested = pyqtSignal(int)
    closed = pyqtSignal()

    def __init__(self, database: Database, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.db = database
        self._games: list[dict[str, Any]] = []
        self._monitor_index = 0
        self._last_axis_at: dict[int, float] = {}
        self._backdrops: dict[int, QPixmap | None] = {}
        self._cover_source: QPixmap | None = None
        self._cover_ratio = 0.75
        self._scroll_anim: QPropertyAnimation | None = None
        self._hero_anim: QPropertyAnimation | None = None
        self.setWindowTitle(tr("Boostlayer Console"))
        self.setWindowIcon(app_icon())
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setObjectName("ConsoleRoot")

        root = QWidget()
        root.setObjectName("ConsoleRoot")
        self.setCentralWidget(root)
        self.backdrop = ConsoleBackdrop(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(44, 26, 44, 22)
        layout.setSpacing(0)

        top = QHBoxLayout()
        top.setSpacing(14)
        brand_box = QVBoxLayout()
        brand_box.setSpacing(0)
        brand = QLabel(tr("Big Picture"))
        brand.setObjectName("ConsoleBrand")
        brand_box.addWidget(brand)
        brand_hint = QLabel(tr("Konsola gier"))
        brand_hint.setObjectName("ConsoleKicker")
        brand_box.addWidget(brand_hint)
        top.addLayout(brand_box)
        top.addStretch(1)
        self.clock = QLabel("")
        self.clock.setObjectName("ConsoleClock")
        top.addWidget(self.clock)
        self.pad_status = QLabel(tr("PAD: szukam..."))
        self.pad_status.setObjectName("ConsolePad")
        top.addWidget(self.pad_status)
        close = QPushButton(tr("Wyjdź  [B]"))
        close.setObjectName("ConsoleGhost")
        close.clicked.connect(self.close_console)
        top.addWidget(close)
        layout.addLayout(top)
        self._clock_timer = QTimer(self)
        self._clock_timer.setInterval(1000)
        self._clock_timer.timeout.connect(self._update_clock)
        self._update_clock()

        self.hero_container = QWidget()
        self.hero_container.setObjectName("ConsoleHeroArea")
        hero_box = QHBoxLayout(self.hero_container)
        hero_box.setContentsMargins(0, 22, 0, 44)
        hero_box.setSpacing(40)
        self.hero_content = QWidget()
        self.hero_content.setObjectName("ConsoleHeroContent")
        text_col = QVBoxLayout(self.hero_content)
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(12)
        text_col.addStretch(1)
        self.detail_kicker = QLabel(tr("Wybrana gra"))
        self.detail_kicker.setObjectName("ConsoleKicker")
        text_col.addWidget(self.detail_kicker)
        self.title = QLabel(tr("Wybierz grę"))
        self.title.setObjectName("ConsoleTitle")
        self.title.setWordWrap(True)
        text_col.addWidget(self.title)
        self.meta = QLabel("")
        self.meta.setObjectName("ConsoleMuted")
        self.meta.setWordWrap(True)
        text_col.addWidget(self.meta)
        self.chips_frame = QWidget()
        chips = QHBoxLayout(self.chips_frame)
        chips.setContentsMargins(0, 2, 0, 0)
        chips.setSpacing(8)
        self.source_chip = QLabel("")
        self.scaling_chip = QLabel("")
        self.fps_chip = QLabel("")
        self.runner_chip = QLabel("")
        for chip in (self.source_chip, self.fps_chip, self.scaling_chip, self.runner_chip):
            chip.setObjectName("ConsoleChip")
            chips.addWidget(chip)
        chips.addStretch(1)
        text_col.addWidget(self.chips_frame)
        text_col.addSpacing(18)
        buttons = QHBoxLayout()
        buttons.setSpacing(12)
        self.play = QPushButton(tr("Graj  [A]"))
        self.play.setObjectName("ConsolePrimary")
        self.play.setCursor(Qt.CursorShape.PointingHandCursor)
        self.play.clicked.connect(self._launch_current)
        buttons.addWidget(self.play)
        self.edit = QPushButton(tr("Edytuj  [X]"))
        self.edit.setObjectName("ConsoleGhost")
        self.edit.setCursor(Qt.CursorShape.PointingHandCursor)
        self.edit.clicked.connect(self._edit_current)
        buttons.addWidget(self.edit)
        buttons.addStretch(1)
        text_col.addLayout(buttons)
        text_col.addStretch(1)
        hero_box.addWidget(self.hero_content, 1)

        self.cover = QLabel()
        self.cover.setObjectName("ConsoleCover")
        self.cover.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._cover_glow = QGraphicsDropShadowEffect(self.cover)
        self._cover_glow.setBlurRadius(64)
        self._cover_glow.setOffset(0, 18)
        self._cover_glow.setColor(QColor(0, 0, 0, 200))
        self.cover.setGraphicsEffect(self._cover_glow)
        hero_box.addWidget(self.cover, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.hero_container, 1)

        self._hero_effect = QGraphicsOpacityEffect(self.hero_content)
        self.hero_content.setGraphicsEffect(self._hero_effect)

        self.tiles = QListWidget()
        self.tiles.setObjectName("ConsoleTiles")
        self.tiles.setViewMode(QListView.ViewMode.IconMode)
        self.tiles.setFlow(QListView.Flow.LeftToRight)
        self.tiles.setWrapping(False)
        self.tiles.setResizeMode(QListView.ResizeMode.Adjust)
        self.tiles.setMovement(QListView.Movement.Static)
        self.tiles.setSpacing(22)
        self.tiles.setUniformItemSizes(True)
        self.tiles.setWordWrap(False)
        self.tiles.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.tiles.setMouseTracking(True)
        self.tiles.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.tiles.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.tiles.setItemDelegate(ConsoleGameDelegate(self.tiles))
        self.tiles.setFixedHeight(356)
        self.tiles.currentRowChanged.connect(lambda _row: self._update_details())
        self.tiles.itemDoubleClicked.connect(self._launch_item)
        self.tiles.viewport().installEventFilter(self)
        layout.addWidget(self.tiles)

        footer = QFrame()
        footer.setObjectName("ConsoleFooterBar")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(16, 6, 16, 6)
        footer_layout.setSpacing(8)
        footer_layout.addStretch(1)
        for key, label in (
            ("←  →", tr("Wybierz")),
            ("A", tr("Graj")),
            ("B", tr("Wyjdź")),
            ("X", tr("Edytuj")),
            ("Y", tr("Odśwież")),
        ):
            key_label = QLabel(key)
            key_label.setObjectName("ConsoleKey")
            footer_layout.addWidget(key_label)
            text_label = QLabel(label)
            text_label.setObjectName("ConsoleKeyLabel")
            footer_layout.addWidget(text_label)
            footer_layout.addSpacing(14)
        footer_layout.addStretch(1)
        layout.addSpacing(10)
        layout.addWidget(footer)

        self.gamepad = GamepadManager(self)
        self.gamepad.status.connect(self._pad_status)
        self.gamepad.button.connect(self._button)
        self.gamepad.axis.connect(self._axis)
        self.reload()

    # ------------------------------------------------------------ content
    def _icon_for(self, game: dict[str, Any]) -> QIcon:
        cover = Path(str(game.get("cover_path", "") or "")).expanduser()
        if cover.is_file():
            icon = QIcon(str(cover))
            if not icon.isNull():
                return icon
        return app_icon(160)

    @staticmethod
    def _source_label(game: dict[str, Any]) -> str:
        store = str(game.get("store", "") or "").upper()
        if store:
            return store
        if game.get("is_amazon"):
            return "AMAZON"
        if game.get("is_steam"):
            return "STEAM"
        return ""

    def reload(self) -> None:
        selected_id = None
        item = self.tiles.currentItem()
        if item is not None:
            selected_id = item.data(Qt.ItemDataRole.UserRole)
        self._games = self.db.list_games()
        self._backdrops.clear()
        self.tiles.clear()
        for game in self._games:
            item = QListWidgetItem(self._icon_for(game), str(game.get("name", "?")))
            item.setData(Qt.ItemDataRole.UserRole, int(game["id"]))
            item.setData(SOURCE_ROLE, self._source_label(game))
            item.setToolTip(str(game.get("name", "")))
            self.tiles.addItem(item)
        has_games = bool(self._games)
        self.tiles.setVisible(has_games)
        self.play.setVisible(has_games)
        self.edit.setVisible(has_games)
        if has_games:
            index = 0
            for i, game in enumerate(self._games):
                if selected_id is not None and int(game["id"]) == int(selected_id):
                    index = i
                    break
            self.tiles.setCurrentRow(index)
            self._update_details()
            self._center_tiles()
            QTimer.singleShot(0, lambda: self._scroll_to_current(animated=False))
        else:
            self._show_empty()
        self.setFocus()

    def _show_empty(self) -> None:
        self.title.setText(tr("Biblioteka jest pusta"))
        self.meta.setText(tr("Dodaj grę w normalnym widoku Boostlayera."))
        self.chips_frame.setVisible(False)
        self.play.setVisible(False)
        self.edit.setVisible(False)
        self._cover_source = None
        self.cover.setPixmap(app_icon(256).pixmap(256, 256).scaled(
            self.cover.size(), Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation))
        self.backdrop.set_source(None)

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

    def _load_cover(self, game: dict[str, Any]) -> QPixmap | None:
        path = Path(str(game.get("cover_path", "") or "")).expanduser()
        if path.is_file():
            pixmap = QPixmap(str(path))
            if not pixmap.isNull():
                return pixmap
        return None

    def _backdrop_for(self, game: dict[str, Any]) -> QPixmap | None:
        game_id = int(game["id"])
        if game_id not in self._backdrops:
            source = self._load_cover(game)
            self._backdrops[game_id] = (
                source.scaled(
                    QSize(64, 88),
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation,
                )
                if source is not None
                else None
            )
        return self._backdrops[game_id]

    def _fit_cover(self) -> None:
        height = max(230, min(470, self.hero_container.height() - 60))
        self.cover.setFixedSize(int(height * self._cover_ratio), height)
        self._refresh_cover()

    def _center_tiles(self) -> None:
        count = self.tiles.count()
        content = count * 234 - 22 if count else 0
        margin = max(0, (self.tiles.width() - content) // 2)
        self.tiles.setViewportMargins(margin, 0, 0, 0)

    def _refresh_cover(self) -> None:
        if self._cover_source is None:
            return
        self.cover.setPixmap(
            self._cover_source.scaled(
                self.cover.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def _update_details(self) -> None:
        game = self._current_game()
        if game is None:
            return
        self.title.setText(str(game.get("name", "")))
        bits = game.get("_bits")
        if bits is None:
            from core import exe_bits

            bits = exe_bits(str(game.get("exe_path", "")))
        source = self._source_label(game) or tr("Standalone")
        if bits:
            source += f"  ·  {bits}-bit"
        runner = Path(str(game.get("runner_path", ""))).name or "AUTO"
        fps = int(game.get("fps_limit", 0)) or 0
        self.meta.setText(tr("Naciśnij A, aby uruchomić, lub X, aby edytować."))
        self.source_chip.setText(source)
        self.scaling_chip.setText(scaling_label(str(game.get("scaling_mode", "native"))))
        self.fps_chip.setText(tr("{fps} FPS", fps=fps) if fps else tr("Bez limitu"))
        self.runner_chip.setText(tr("Runner: {name}", name=runner[:24]))
        self.runner_chip.setToolTip(runner)
        self.chips_frame.setVisible(True)
        self._cover_source = self._load_cover(game) or app_icon(256).pixmap(256, 256)
        if self._cover_source.height():
            self._cover_ratio = max(0.55, min(0.8, self._cover_source.width() / self._cover_source.height()))
        self._fit_cover()
        self.backdrop.set_source(self._backdrop_for(game))
        self._animate_hero()
        self._scroll_to_current(animated=True)

    def _animate_hero(self) -> None:
        if self._hero_anim is not None:
            self._hero_anim.stop()
        self._hero_effect.setOpacity(0.25)
        animation = QPropertyAnimation(self._hero_effect, b"opacity", self)
        animation.setDuration(280)
        animation.setStartValue(0.25)
        animation.setEndValue(1.0)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        animation.start()
        self._hero_anim = animation

    def _scroll_to_current(self, animated: bool = True) -> None:
        item = self.tiles.currentItem()
        if item is None:
            return
        rect = self.tiles.visualItemRect(item)
        bar = self.tiles.horizontalScrollBar()
        target = bar.value() + rect.center().x() - self.tiles.viewport().width() // 2
        target = max(bar.minimum(), min(bar.maximum(), target))
        if self._scroll_anim is not None:
            self._scroll_anim.stop()
        if not animated:
            bar.setValue(target)
            return
        animation = QPropertyAnimation(bar, b"value", self)
        animation.setDuration(300)
        animation.setStartValue(bar.value())
        animation.setEndValue(target)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        animation.start()
        self._scroll_anim = animation

    def _move(self, dx: int) -> None:
        count = self.tiles.count()
        if count == 0:
            return
        row = self.tiles.currentRow()
        self.tiles.setCurrentRow(max(0, min(count - 1, row + dx)))
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
            self._move(-1)
        elif number == 5:
            self._move(1)

    def _axis(self, number: int, value: float) -> None:
        if abs(value) < 0.55:
            self._last_axis_at.pop(number, None)
            return
        now = time.monotonic()
        if now - self._last_axis_at.get(number, 0.0) < 0.16:
            return
        self._last_axis_at[number] = now
        if number in {0, 6}:
            self._move(1 if value > 0 else -1)

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if watched is self.tiles.viewport() and event.type() == QEvent.Type.Wheel:
            delta = event.angleDelta().y() or event.angleDelta().x()
            if delta:
                self._move(-1 if delta > 0 else 1)
            return True
        return super().eventFilter(watched, event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        key = event.key()
        if key in {Qt.Key.Key_Left, Qt.Key.Key_A}:
            self._move(-1)
        elif key in {Qt.Key.Key_Right, Qt.Key.Key_D}:
            self._move(1)
        elif key in {Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space}:
            self._launch_current()
        elif key == Qt.Key.Key_X:
            self._edit_current()
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
            self._fit_cover()
            self._center_tiles()
            QTimer.singleShot(0, lambda: self._scroll_to_current(animated=False))

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._update_clock()
        self._clock_timer.start()
        self.backdrop.setGeometry(0, 0, self.width(), self.height())
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
