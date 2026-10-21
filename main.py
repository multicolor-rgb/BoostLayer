#!/usr/bin/env python3
"""Boostlayer UI - PyQt6 presentation layer for the Wine/Proton launcher."""
from __future__ import annotations

import ctypes
import html
import json
import os
import re
import shlex
import shutil
import sys
import time
import uuid
from functools import partial
from pathlib import Path
from typing import Any

from PyQt6.QtCore import (
    QByteArray,
    QCoreApplication,
    QEvent,
    QEventLoop,
    QLibraryInfo,
    QObject,
    QPoint,
    QPointF,
    QProcess,
    QRect,
    QRectF,
    QSize,
    Qt,
    QTimer,
    QTranslator,
    QUrl,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QAction,
    QColor,
    QDesktopServices,
    QGuiApplication,
    QFont,
    QFontDatabase,
    QIcon,
    QKeySequence,
    QLinearGradient,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPalette,
    QPen,
    QPixmap,
    QShortcut,
)
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLayout,
    QLayoutItem,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QProgressDialog,
    QPushButton,
    QScrollArea,
    QSizeGrip,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QSystemTrayIcon,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

import db
from db import (
    FPS_LIMITS,
    SCALING_PROFILES,
    Database,
    config_dir,
    mangohud_config,
    scaling_label,
)
from theme import DEFAULT_THEME, THEMES, build_qss, get_theme, set_theme
from i18n import DEFAULT_LANGUAGE, LANGUAGES, get_language, set_language, tr
from console import ConsoleWindow
from core import (
    APP_NAME,
    APP_VERSION,
    LAST_RUN_LOG,
    USER_AGENT,
    DependencyGroup,
    RunnerDownloadWorker,
    RunnerInfo,
    RunnerReleasesWorker,
    SteamOptionsWorker,
    SteamSyncWorker,
    WinetricksInstallWorker,
    WinetricksPlan,
    WinetricksWorker,
    app_icon,
    build_winetricks_plan,
    choose_runner_asset,
    dependency_install_groups,
    detect_steam_root,
    discover_runners,
    ensure_crt_shader,
    ensure_launcher,
    ensure_steam_wrapper,
    exe_bits,
    find_proton_script,
    gamemode32_installed,
    gamepad_udev_script,
    human_bytes,
    latest_steam_backup,
    log,
    mangohud32_path,
    mangohud32_script,
    mangohud_library_path,
    missing_installable_tools,
    normalize_winetricks_verbs,
    package_manager,
    parse_env_vars,
    protontricks_path,
    resolve_runner,
    steam_account,
    steam_client_command,
    steam_is_running,
    steam_game_process_running,
    steam_launch_action_for_appid,
    steam_launch_option,
    steam_wrapper_path,
    tool_status,
    winetricks_applied,
    winetricks_path,
    winetricks_verbs_text,
)

QSS = """
QWidget {
    color: #DCEBF1;
    background: transparent;
    font-family: "DejaVu Sans", "Noto Sans", sans-serif;
    font-size: 10pt;
    outline: none;
}
QWidget#Root {
    background: #0E1013;
    border: 1px solid #252B32;
}
QFrame#TitleBar {
    background: #0A0C0E;
    border-bottom: 1px solid #20262D;
}
QLabel#BrandMark {
    color: #00E5FF;
    font-family: "DejaVu Sans Mono", monospace;
    font-size: 15pt;
    font-weight: 800;
    letter-spacing: 2px;
}
QLabel#BrandSub {
    color: #5D707C;
    font-family: "DejaVu Sans Mono", monospace;
    font-size: 7pt;
    letter-spacing: 2px;
}
QPushButton#WindowButton, QPushButton#CloseButton {
    background: transparent;
    border: 0;
    color: #98AAB5;
    font-size: 14pt;
    min-width: 38px;
    max-width: 38px;
    min-height: 30px;
    max-height: 30px;
}
QPushButton#WindowButton:hover {
    background: #1D242B;
    color: #FFFFFF;
}
QPushButton#CloseButton:hover {
    background: #C4213E;
    color: #FFFFFF;
}
QToolButton#TitleMenu {
    background: transparent;
    border: 0;
    color: #8EA1AC;
    font-size: 17pt;
    min-width: 38px;
    max-width: 38px;
    min-height: 30px;
}
QToolButton#TitleMenu:hover {
    background: #1D242B;
    color: #00E5FF;
}
QFrame#Sidebar {
    background: #101317;
    border-right: 1px solid #20262D;
}
QPushButton#NavButton {
    background: transparent;
    border: 0;
    border-left: 3px solid transparent;
    color: #70828D;
    text-align: left;
    padding: 12px 14px;
    font-family: "DejaVu Sans Mono", monospace;
    font-size: 9pt;
    font-weight: 700;
    letter-spacing: 1px;
}
QPushButton#NavButton:hover {
    color: #DDEFF5;
    background: #151A1F;
}
QPushButton#NavButton:checked {
    color: #00E5FF;
    background: #101C21;
    border-left: 3px solid #00E5FF;
}
QLabel#SidebarCaption {
    color: #485861;
    font-family: "DejaVu Sans Mono", monospace;
    font-size: 7pt;
    letter-spacing: 1px;
}
QLabel#SidebarLive {
    color: #42F5A7;
    font-family: "DejaVu Sans Mono", monospace;
    font-size: 8pt;
}
QLabel#PageTitle {
    color: #F2FBFF;
    font-size: 22pt;
    font-weight: 800;
    letter-spacing: 1px;
}
QLabel#PageKicker {
    color: #00E5FF;
    font-family: "DejaVu Sans Mono", monospace;
    font-size: 8pt;
    font-weight: 700;
    letter-spacing: 3px;
}
QLabel#PageSubtitle, QLabel#Muted {
    color: #72838E;
}
QLabel#SectionTitle {
    color: #E8F7FC;
    font-size: 12pt;
    font-weight: 700;
}
QLabel#StatsPill {
    color: #9DB4C0;
    background: #151B21;
    border: 1px solid #263038;
    border-radius: 11px;
    padding: 4px 10px;
    font-family: "DejaVu Sans Mono", monospace;
    font-size: 8pt;
}
QFrame#Panel {
    background: #14191E;
    border: 1px solid #252D35;
    border-radius: 10px;
}
QFrame#Card {
    background: #14191E;
    border: 1px solid #252E36;
    border-radius: 10px;
}
QFrame#Card:hover {
    border: 1px solid #00B8CC;
    background: #171E24;
}
QFrame#CompactRow {
    background: #14191E;
    border: 1px solid #232C34;
    border-radius: 8px;
}
QFrame#CompactRow:hover {
    border: 1px solid #00A6BA;
}
QLabel#CardTitle {
    color: #EAF9FE;
    font-size: 11pt;
    font-weight: 700;
}
QLabel#CardMeta {
    color: #71858F;
    font-family: "DejaVu Sans Mono", monospace;
    font-size: 8pt;
}
QLabel#Accent {
    color: #00E5FF;
}
QLabel#Good {
    color: #42F5A7;
}
QLabel#Warn {
    color: #FFB347;
}
QLabel#Bad {
    color: #FF4D6D;
}
QPushButton {
    background: #192027;
    color: #DDEBF1;
    border: 1px solid #2A343D;
    border-radius: 7px;
    padding: 8px 14px;
    font-weight: 600;
}
QPushButton:hover {
    background: #202A33;
    border-color: #3A4853;
}
QPushButton:pressed {
    background: #11171C;
}
QPushButton:disabled {
    color: #4A5962;
    background: #12171B;
    border-color: #1E262C;
}
QPushButton#PrimaryButton {
    background: #00C8E0;
    color: #031014;
    border: 1px solid #00E5FF;
    font-weight: 800;
}
QPushButton#PrimaryButton:hover {
    background: #54F0FF;
}
QPushButton#GhostButton {
    background: transparent;
    border: 1px solid #2C3942;
    color: #9EB3BE;
}
QPushButton#GhostButton:hover {
    border-color: #00C8E0;
    color: #00E5FF;
}
QPushButton#DangerButton {
    background: #251319;
    color: #FF6C87;
    border: 1px solid #54202F;
}
QPushButton#DangerButton:hover {
    background: #3A1822;
    border-color: #C4213E;
}
QPushButton#CardPlay {
    background: #102A2F;
    color: #00E5FF;
    border: 1px solid #15515D;
    border-radius: 6px;
    padding: 6px 9px;
    font-family: "DejaVu Sans Mono", monospace;
    font-size: 8pt;
    font-weight: 800;
}
QPushButton#CardPlay:hover {
    background: #00E5FF;
    color: #041014;
}
QPushButton#CardIcon {
    background: transparent;
    border: 1px solid #2A343D;
    border-radius: 6px;
    color: #8FA3AE;
    padding: 5px 8px;
    font-size: 9pt;
}
QPushButton#CardIcon:hover {
    color: #00E5FF;
    border-color: #00A7BA;
}
QPushButton#DangerIcon:hover {
    color: #FF4D6D;
    border-color: #B92341;
}
QPushButton#ViewButton {
    background: transparent;
    color: #687B86;
    border: 1px solid #242D35;
    padding: 7px 11px;
    font-family: "DejaVu Sans Mono", monospace;
    font-size: 8pt;
}
QPushButton#ViewButton:checked {
    color: #00E5FF;
    border-color: #008B9C;
    background: #0D2025;
}
QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {
    background: #0D1216;
    border: 1px solid #27323A;
    border-radius: 6px;
    padding: 7px 9px;
    color: #E5F5FA;
    selection-background-color: #007E90;
}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus,
QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {
    border: 1px solid #00B8CC;
}
QLineEdit#Search {
    padding: 9px 12px;
    background: #0B0F12;
    border: 1px solid #232D35;
}
QComboBox::drop-down {
    border: 0;
    width: 26px;
}
QComboBox QAbstractItemView {
    background: #12181D;
    color: #DCEBF1;
    border: 1px solid #2A3740;
    selection-background-color: #005B68;
    padding: 4px;
}
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
    width: 18px;
    background: #182027;
    border: 0;
}
QCheckBox {
    spacing: 9px;
    color: #C7D9E1;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid #34434D;
    border-radius: 4px;
    background: #0D1216;
}
QCheckBox::indicator:checked {
    background: #00C8E0;
    border: 1px solid #00E5FF;
}
QCheckBox::indicator:hover {
    border-color: #00A7BA;
}
QSlider::groove:horizontal {
    height: 4px;
    background: #26323A;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    width: 14px;
    margin: -6px 0;
    border-radius: 7px;
    background: #00E5FF;
}
QSlider::sub-page:horizontal {
    background: #00A6BA;
    border-radius: 2px;
}
QProgressBar {
    background: #0C1115;
    border: 1px solid #25313A;
    border-radius: 7px;
    height: 14px;
    text-align: center;
    color: #C9EAF2;
    font-family: "DejaVu Sans Mono", monospace;
    font-size: 7pt;
}
QProgressBar::chunk {
    background: #00B8CC;
    border-radius: 6px;
}
QScrollArea {
    background: transparent;
    border: 0;
}
QScrollBar:vertical {
    background: #0D1115;
    width: 10px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: #2A3740;
    min-height: 30px;
    border-radius: 4px;
}
QScrollBar::handle:vertical:hover {
    background: #00A7BA;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: #0D1115;
}
QAbstractScrollArea::corner {
    background: #0D1115;
    border: 0;
}
QScrollBar:horizontal {
    background: #0D1115;
    height: 10px;
}
QScrollBar::handle:horizontal {
    background: #2A3740;
    min-width: 30px;
    border-radius: 4px;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0;
}
QTreeWidget {
    background: #101519;
    alternate-background-color: #12181D;
    border: 1px solid #242D35;
    border-radius: 8px;
    color: #CFE1E8;
    selection-background-color: #0B323A;
    selection-color: #E9FCFF;
    padding: 4px;
}
QTreeWidget::item {
    padding: 6px;
    border-bottom: 1px solid #1B2228;
}
QTreeWidget::item:hover {
    background: #182128;
}
QHeaderView::section {
    background: #0B0F12;
    color: #6E818C;
    border: 0;
    border-bottom: 1px solid #29343C;
    padding: 7px;
    font-family: "DejaVu Sans Mono", monospace;
    font-size: 8pt;
}
QGroupBox {
    border: 1px solid #252D35;
    border-radius: 8px;
    margin-top: 14px;
    padding: 16px 12px 12px 12px;
    background: #12171B;
    font-weight: 700;
    color: #BBD3DC;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    color: #00C8E0;
    font-family: "DejaVu Sans Mono", monospace;
    font-size: 8pt;
    letter-spacing: 1px;
}
QMenu {
    background: #11171C;
    color: #D8EAF1;
    border: 1px solid #2A3740;
    padding: 6px;
}
QMenu::item {
    padding: 8px 28px 8px 14px;
    border-radius: 4px;
}
QMenu::item:selected {
    background: #0A3A42;
    color: #FFFFFF;
}
QMenu::separator {
    height: 1px;
    background: #26313A;
    margin: 6px 8px;
}
QToolTip {
    background: #0B1013;
    color: #DDF4FA;
    border: 1px solid #00A7BA;
    padding: 5px;
}
QDialog {
    background: #0E1114;
}
QDialogButtonBox QPushButton {
    min-width: 100px;
}
QFrame#StatusBar {
    background: #0A0D10;
    border-top: 1px solid #1F262D;
}
QLabel#StatusText {
    color: #70838E;
    font-family: "DejaVu Sans Mono", monospace;
    font-size: 8pt;
}
QLabel#GhostBadge {
    color: #42F5A7;
    background: #0C2119;
    border: 1px solid #1E4D3A;
    border-radius: 9px;
    padding: 3px 9px;
    font-family: "DejaVu Sans Mono", monospace;
    font-size: 7pt;
}
QSizeGrip {
    background: transparent;
    width: 16px;
    height: 16px;
}
"""


TRAY_QSS = """
QMenu#TrayMenu {
    background: #101418;
    color: #DCEBF1;
    border: 1px solid #2A343D;
    padding: 7px;
}
QMenu#TrayMenu::item {
    padding: 8px 26px 8px 12px;
    border-radius: 5px;
}
QMenu#TrayMenu::item:selected {
    background: #17313A;
    color: #FFFFFF;
}
QMenu#TrayMenu::item:disabled {
    color: #7B8D98;
}
QMenu#TrayMenu::separator {
    height: 1px;
    background: #26323A;
    margin: 6px 9px;
}
QMenu#TrayMenu::icon {
    margin-left: 8px;
}
"""


class _XEvent(ctypes.Structure):
    _fields_ = [("type", ctypes.c_int), ("padding", ctypes.c_char * 188)]


class X11GlobalHotkey(QObject):
    """Global Ctrl+Alt+S on X11 via libX11, without external packages.

    Wayland does not expose XGrabKey; MainWindow falls back to a local
    QShortcut and the tray informs the user.
    """

    activated = pyqtSignal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.available = False
        self._display: int | None = None
        self._lib: ctypes.CDLL | None = None
        self._error_handler = None
        self._last_activation = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(60)
        self._timer.timeout.connect(self._poll)

    def start(self) -> bool:
        if os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland":
            return False
        if not os.environ.get("DISPLAY"):
            return False
        try:
            lib = ctypes.CDLL("libX11.so.6")
            lib.XOpenDisplay.argtypes = [ctypes.c_char_p]
            lib.XOpenDisplay.restype = ctypes.c_void_p
            lib.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
            lib.XDefaultRootWindow.restype = ctypes.c_ulong
            lib.XStringToKeysym.argtypes = [ctypes.c_char_p]
            lib.XStringToKeysym.restype = ctypes.c_ulong
            lib.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
            lib.XKeysymToKeycode.restype = ctypes.c_uint
            lib.XGrabKey.argtypes = [
                ctypes.c_void_p,
                ctypes.c_int,
                ctypes.c_uint,
                ctypes.c_ulong,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
            ]
            lib.XGrabKey.restype = ctypes.c_int
            lib.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
            lib.XSync.restype = ctypes.c_int
            lib.XPending.argtypes = [ctypes.c_void_p]
            lib.XPending.restype = ctypes.c_int
            lib.XNextEvent.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
            lib.XNextEvent.restype = ctypes.c_int
            lib.XCloseDisplay.argtypes = [ctypes.c_void_p]
            lib.XCloseDisplay.restype = ctypes.c_int
            display = lib.XOpenDisplay(None)
            if not display:
                return False
            self._lib = lib
            self._display = display
            self._error_handler = ctypes.CFUNCTYPE(
                ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p
            )(lambda _display, _event: 0)
            lib.XSetErrorHandler(self._error_handler)
            root = lib.XDefaultRootWindow(display)
            keysym = lib.XStringToKeysym(b"s")
            keycode = lib.XKeysymToKeycode(display, keysym)
            if not keycode:
                self.stop()
                return False
            control = 1 << 2
            mod1 = 1 << 3
            lock = 1 << 1
            numlock = 1 << 4
            modifiers = [
                control | mod1,
                control | mod1 | lock,
                control | mod1 | numlock,
                control | mod1 | lock | numlock,
            ]
            for modifier in modifiers:
                # owner_events=False, GrabModeAsync, GrabModeAsync
                lib.XGrabKey(display, keycode, modifier, root, 0, 1, 1)
            lib.XSync(display, 0)
            self.available = True
            self._timer.start()
            return True
        except (OSError, AttributeError, TypeError):
            self.stop()
            return False

    def _poll(self) -> None:
        if self._display is None or self._lib is None:
            return
        try:
            while self._lib.XPending(self._display) > 0:
                event = _XEvent()
                self._lib.XNextEvent(self._display, ctypes.byref(event))
                if event.type == 2:  # KeyPress
                    now = time.monotonic()
                    if now - self._last_activation > 0.25:
                        self._last_activation = now
                        self.activated.emit()
        except Exception:
            self.stop()

    def stop(self) -> None:
        self._timer.stop()
        self.available = False
        if self._display is not None and self._lib is not None:
            try:
                self._lib.XCloseDisplay(self._display)
            except Exception:
                pass
        self._display = None
        self._lib = None


class FlowLayout(QLayout):
    """Responsive wrapping grid without an external UI dependency."""

    def __init__(
        self,
        parent: QWidget | None = None,
        margin: int = 0,
        h_spacing: int = 16,
        v_spacing: int = 16,
    ) -> None:
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self._h_spacing = h_spacing
        self._v_spacing = v_spacing
        self.setContentsMargins(margin, margin, margin, margin)

    def addItem(self, item: QLayoutItem) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int) -> QLayoutItem | None:
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self) -> Qt.Orientation:
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        return size + QSize(margins.left() + margins.right(), margins.top() + margins.bottom())

    def clear(self) -> None:
        while self.count():
            item = self.takeAt(0)
            if item is not None:
                widget = item.widget()
                if widget is not None:
                    widget.hide()
                    widget.setParent(None)
                    widget.deleteLater()

    def _do_layout(self, rect: QRect, test_only: bool) -> int:
        margins = self.contentsMargins()
        effective = rect.adjusted(
            margins.left(), margins.top(), -margins.right(), -margins.bottom()
        )
        x = effective.x()
        y = effective.y()
        line_height = 0
        for item in self._items:
            widget = item.widget()
            if widget is not None and widget.isHidden():
                continue
            hint = item.sizeHint()
            next_x = x + hint.width() + self._h_spacing
            if next_x - self._h_spacing > effective.right() and line_height > 0:
                x = effective.x()
                y += line_height + self._v_spacing
                next_x = x + hint.width() + self._h_spacing
                line_height = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x = next_x
            line_height = max(line_height, hint.height())
        return y + line_height - rect.y() + margins.bottom()


def style_scroll_area(scroll: QScrollArea, color: str = "#0E1013") -> None:
    """Force a dark viewport; Fusion's default viewport is light and ignores QSS."""
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    viewport = scroll.viewport()
    viewport.setObjectName("BoostlayerViewport")
    viewport.setStyleSheet(
        f"QWidget#BoostlayerViewport {{ background-color: {color}; }}"
    )
    viewport.setAutoFillBackground(True)
    palette = viewport.palette()
    palette.setColor(QPalette.ColorRole.Window, QColor(color))
    palette.setColor(QPalette.ColorRole.Base, QColor(color))
    viewport.setPalette(palette)


class CoverView(QWidget):
    """Rounded, aspect-filled cover with a generated fallback."""

    def __init__(
        self, title: str, pixmap: QPixmap | None = None, steam: bool = False, parent=None
    ) -> None:
        super().__init__(parent)
        self.title = title
        self.pixmap = pixmap
        self.steam = steam
        self._hover = False
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.setMinimumSize(64, 84)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def sizeHint(self) -> QSize:
        return QSize(220, 300)

    def set_pixmap(self, pixmap: QPixmap | None) -> None:
        self.pixmap = pixmap
        self.update()

    def enterEvent(self, event: QEvent) -> None:
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1.0, 1.0, -1.0, -1.0)
        path = QPainterPath()
        path.addRoundedRect(rect, 8, 8)
        painter.save()
        painter.setClipPath(path)
        if self.pixmap is not None and not self.pixmap.isNull():
            scaled = self.pixmap.scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            source_x = max(0, (scaled.width() - self.width()) // 2)
            source_y = max(0, (scaled.height() - self.height()) // 2)
            painter.drawPixmap(
                self.rect(),
                scaled,
                QRect(source_x, source_y, self.width(), self.height()),
            )
        else:
            theme = get_theme()
            gradient = QLinearGradient(0, 0, self.width(), self.height())
            gradient.setColorAt(0.0, QColor(theme.panel))
            gradient.setColorAt(0.55, QColor(theme.panel_alt))
            gradient.setColorAt(1.0, QColor(theme.background))
            painter.fillRect(self.rect(), gradient)
            grid_color = QColor(theme.accent)
            grid_color.setAlpha(36)
            painter.setPen(grid_color)
            step = 28
            for x in range(0, self.width() + step, step):
                painter.drawLine(x, 0, x, self.height())
            for y in range(0, self.height() + step, step):
                painter.drawLine(0, y, self.width(), y)
            initials = "".join(
                part[0] for part in re.split(r"\W+", self.title) if part
            )[:2].upper() or "B"
            font = QFont("DejaVu Sans", max(24, min(54, self.width() // 4)))
            font.setWeight(QFont.Weight.Black)
            painter.setFont(font)
            painter.setPen(QColor(theme.accent))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, initials)

        overlay = QLinearGradient(0, self.height() * 0.45, 0, self.height())
        overlay.setColorAt(0.0, QColor(0, 0, 0, 0))
        overlay.setColorAt(1.0, QColor(3, 8, 11, 210))
        painter.fillRect(self.rect(), overlay)
        if self.steam:
            theme = get_theme()
            badge_color = QColor(theme.accent)
            badge_color.setAlpha(130)
            painter.setPen(QColor(theme.text))
            badge = QRectF(10, 10, 65, 21)
            painter.setBrush(QColor(4, 13, 17, 200))
            painter.setPen(QPen(badge_color, 1))
            painter.drawRoundedRect(badge, 5, 5)
            painter.setFont(QFont("DejaVu Sans Mono", 7, QFont.Weight.Bold))
            painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, tr("STEAM"))
        painter.restore()

        theme = get_theme()
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(
            QPen(QColor(theme.accent) if self._hover else QColor(theme.border), 1.4)
        )
        painter.drawRoundedRect(rect, 8, 8)
        painter.end()


class TitleBar(QFrame):
    menu_requested = pyqtSignal()

    def __init__(self, window: QWidget) -> None:
        super().__init__(window)
        self._window = window
        self._drag_offset: QPoint | None = None
        self.setObjectName("TitleBar")
        self.setFixedHeight(54)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 8, 8, 8)
        layout.setSpacing(10)

        mark = QLabel(tr("BL"))
        mark.setObjectName("BrandMark")
        layout.addWidget(mark)
        labels = QVBoxLayout()
        labels.setSpacing(0)
        title = QLabel(tr("BOOSTLAYER"))
        title.setStyleSheet("font-weight:800; color:#E9FAFF; font-size:9pt; letter-spacing:2px;")
        subtitle = QLabel(tr("GAME RUNTIME CONTROL // {version}", version=APP_VERSION))
        subtitle.setObjectName("BrandSub")
        labels.addWidget(title)
        labels.addWidget(subtitle)
        layout.addLayout(labels)
        layout.addStretch(1)

        menu_button = QToolButton()
        menu_button.setObjectName("TitleMenu")
        menu_button.setText(tr("⋮"))
        menu_button.setCursor(Qt.CursorShape.PointingHandCursor)
        menu_button.clicked.connect(self.menu_requested.emit)
        layout.addWidget(menu_button)

        minimize = QPushButton(tr("—"))
        minimize.setObjectName("WindowButton")
        minimize.setToolTip(tr("Minimalizuj"))
        minimize.clicked.connect(window.showMinimized)
        layout.addWidget(minimize)

        maximize = QPushButton(tr("□"))
        maximize.setObjectName("WindowButton")
        maximize.setToolTip(tr("Maksymalizuj"))
        maximize.clicked.connect(self._toggle_maximize)
        layout.addWidget(maximize)

        close = QPushButton(tr("×"))
        close.setObjectName("CloseButton")
        close.setToolTip(tr("Zamknij"))
        close.clicked.connect(window.close)
        layout.addWidget(close)

    def _toggle_maximize(self) -> None:
        if self._window.isMaximized():
            self._window.showNormal()
        else:
            self._window.showMaximized()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self._window.windowHandle()
            moved = False
            if handle is not None and hasattr(handle, "startSystemMove"):
                try:
                    moved = bool(handle.startSystemMove())
                except (RuntimeError, TypeError):
                    moved = False
            if not moved:
                self._drag_offset = (
                    event.globalPosition().toPoint()
                    - self._window.frameGeometry().topLeft()
                )
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if (
            self._drag_offset is not None
            and event.buttons() & Qt.MouseButton.LeftButton
            and not self._window.isMaximized()
        ):
            self._window.move(event.globalPosition().toPoint() - self._drag_offset)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self._drag_offset = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._toggle_maximize()
        super().mouseDoubleClickEvent(event)


class ColorButton(QPushButton):
    color_changed = pyqtSignal(str)

    def __init__(self, color: str, title: str, parent=None) -> None:
        super().__init__(parent)
        self._title = title
        self._color = color if QColor(color).isValid() else "#00E5FF"
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(34)
        self.setMinimumWidth(120)
        self.clicked.connect(self._choose)
        self._apply_style()

    def _apply_style(self) -> None:
        color = QColor(self._color)
        text = "#061014" if color.lightness() > 150 else "#FFFFFF"
        self.setText(self._color.upper())
        self.setStyleSheet(
            f"QPushButton {{ background:{self._color}; color:{text}; "
            "border:1px solid #3A4750; border-radius:6px; "
            "font-family:'DejaVu Sans Mono'; font-weight:700; padding:6px; }"
            "QPushButton:hover { border:1px solid #FFFFFF; }"
        )

    def color(self) -> str:
        return self._color

    def set_color(self, color: str, emit: bool = False) -> None:
        if QColor(color).isValid():
            self._color = color.lower()
            self._apply_style()
            if emit:
                self.color_changed.emit(self._color)

    def _choose(self) -> None:
        chosen = QColorDialog.getColor(
            QColor(self._color), self, tr("Kolor: {name}", name=self._title)
        )
        if chosen.isValid():
            self.set_color(chosen.name(), emit=True)


class OverlayPreview(QWidget):
    """Approximate MangoHud preview rendered with QPainter (no webview)."""

    position_selected = pyqtSignal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._profile: dict[str, Any] = dict(db.DEFAULT_MANGOHUD)
        self._scaling = "native"
        self.setMinimumSize(360, 300)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(tr("Kliknij, aby zakotwiczyć HUD w jednej z dziewięciu stref."))

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        point = event.position()
        column = min(2, max(0, int(point.x() * 3 / max(1, self.width()))))
        row = min(2, max(0, int(point.y() * 3 / max(1, self.height()))))
        vertical = ("top", "middle", "bottom")[row]
        horizontal = ("left", "center", "right")[column]
        self.position_selected.emit(f"{vertical}-{horizontal}")

    def set_profile(self, profile: dict[str, Any], scaling: str = "native") -> None:
        self._profile = dict(profile)
        self._scaling = scaling
        self.update()

    @staticmethod
    def _pos_color(value: str, fallback: str) -> QColor:
        color = QColor(value)
        return color if color.isValid() else QColor(fallback)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect()
        gradient = QLinearGradient(0, 0, rect.width(), rect.height())
        gradient.setColorAt(0.0, QColor("#0A1217"))
        gradient.setColorAt(0.55, QColor("#101822"))
        gradient.setColorAt(1.0, QColor("#1C1018"))
        painter.fillRect(rect, gradient)
        painter.setPen(QPen(QColor(255, 255, 255, 10), 1))
        for x in range(0, rect.width(), 32):
            painter.drawLine(x, 0, x, rect.height())
        for y in range(0, rect.height(), 32):
            painter.drawLine(0, y, rect.width(), y)

        profile = self._profile
        rows: list[tuple[str, str, str]] = []
        if profile.get("show_fps", True):
            rows.append(("144", "FPS", "#00E5FF"))
        if profile.get("show_gpu", True):
            gpu_temp = "  61°C" if profile.get("show_temps", True) else ""
            rows.append(("GPU 74%", f"  4.2 GB{gpu_temp}", "#42F5A7"))
        if profile.get("show_cpu", True):
            cpu_temp = "  55°C" if profile.get("show_temps", True) else ""
            rows.append(("CPU 43%", f"  5.1 GHz{cpu_temp}", "#00B8FF"))
        if profile.get("show_ram", True) or profile.get("show_vram", True):
            parts = []
            if profile.get("show_ram", True):
                parts.append("RAM 12.4G")
            if profile.get("show_vram", True):
                parts.append("VRAM 7.8G")
            rows.append((" / ".join(parts), "", "#C9A7FF"))
        if profile.get("show_frametime", True):
            rows.append(("FT 6.9 ms", "", "#FFB347"))
        rows.append((tr("Scaling: {label}", label=scaling_label(self._scaling)), "", "#DCEBF1"))

        width = min(390, max(280, rect.width() - 36))
        row_height = 24
        height = row_height * len(rows) + 28
        position = str(profile.get("position", "top-left"))
        margin = 18
        if position.endswith("left"):
            x = margin
        elif position.endswith("right"):
            x = rect.width() - width - margin
        else:
            x = (rect.width() - width) // 2
        if position.startswith("top"):
            y = margin
        elif position.startswith("bottom"):
            y = rect.height() - height - margin
        else:
            y = (rect.height() - height) // 2

        alpha = int(max(0.0, min(1.0, float(profile.get("background_alpha", 0.35)))) * 255)
        panel = QRectF(x, y, width, height)
        painter.setBrush(QColor(7, 12, 15, alpha))
        painter.setPen(QPen(QColor(0, 229, 255, 90), 1))
        radius = max(0, min(20, int(profile.get("round_corners", 8))))
        painter.drawRoundedRect(panel, radius, radius)
        painter.setPen(QPen(self._pos_color(str(profile.get("accent", "#00E5FF")), "#00E5FF"), 3))
        painter.drawLine(
            QPointF(panel.left() + 1, panel.top() + 8),
            QPointF(panel.left() + 1, panel.bottom() - 8),
        )
        font_size = max(8, min(24, int(profile.get("font_size", 18)) // 2 + 2))
        painter.setFont(QFont("DejaVu Sans Mono", font_size, QFont.Weight.DemiBold))
        text_color = self._pos_color(str(profile.get("text_color", "#E6FAFF")), "#E6FAFF")
        for index, (left, right, color_value) in enumerate(rows):
            row_y = panel.top() + 14 + index * row_height
            painter.setPen(text_color)
            painter.drawText(
                QRectF(panel.left() + 14, row_y, width - 26, row_height),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                left,
            )
            if right:
                painter.setPen(self._pos_color(color_value, "#00E5FF"))
                painter.drawText(
                    QRectF(panel.left() + 14, row_y, width - 28, row_height),
                    int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                    right,
                )
            if left.startswith("FT") and profile.get("show_frametime", True):
                graph_width = 92
                graph_x = panel.right() - graph_width - 16
                for bar in range(18):
                    bar_height = 3 + ((bar * 7 + index * 3) % 12)
                    painter.setBrush(self._pos_color("#FFB347", "#FFB347"))
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.drawRect(
                        QRectF(
                            graph_x + bar * 5,
                            row_y + row_height - 7 - bar_height,
                            3,
                            bar_height,
                        )
                    )
        painter.setPen(QColor("#5F7681"))
        painter.setFont(QFont("DejaVu Sans Mono", 7))
        painter.drawText(
            QRect(12, rect.height() - 20, 220, 14),
            Qt.AlignmentFlag.AlignLeft,
            tr("PODGLĄD // MANGOHUD"),
        )
        painter.end()


class GameCard(QFrame):
    launch_requested = pyqtSignal(int)
    edit_requested = pyqtSignal(int)
    delete_requested = pyqtSignal(int)
    context_requested = pyqtSignal(int, object)

    def __init__(self, game: dict[str, Any], cover: QPixmap | None, parent=None) -> None:
        super().__init__(parent)
        self.game = game
        self.setObjectName("Card")
        self.setFixedWidth(244)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(
            lambda pos: self.context_requested.emit(
                int(self.game["id"]), self.mapToGlobal(pos)
            )
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(9, 9, 9, 10)
        layout.setSpacing(7)
        self.cover = CoverView(
            str(game.get("name", "?")), cover, bool(game.get("is_steam"))
        )
        self.cover.setFixedHeight(310)
        layout.addWidget(self.cover)
        title = QLabel(str(game.get("name", tr("Bez nazwy"))))
        title.setObjectName("CardTitle")
        title.setToolTip(str(game.get("name", "")))
        title.setMaximumHeight(24)
        layout.addWidget(title)
        bits = game.get("_bits")
        bit_suffix = f"  |  {bits}-BIT" if bits else ""
        meta = QLabel(
            f"{scaling_label(str(game.get('scaling_mode', 'native')))}  |  "
            f"{int(game.get('fps_limit', 0)) or '∞'} FPS{bit_suffix}"
        )
        meta.setObjectName("CardMeta")
        meta.setToolTip(meta.text())
        layout.addWidget(meta)
        actions = QHBoxLayout()
        actions.setSpacing(4)
        play = QPushButton(tr("▶  GRAJ"))
        play.setObjectName("CardPlay")
        play.clicked.connect(lambda: self.launch_requested.emit(int(self.game["id"])))
        actions.addWidget(play, 1)
        edit = QPushButton(tr("✎"))
        edit.setObjectName("CardIcon")
        edit.setToolTip(tr("Edytuj"))
        edit.clicked.connect(lambda: self.edit_requested.emit(int(self.game["id"])))
        actions.addWidget(edit)
        delete = QPushButton(tr("×"))
        delete.setObjectName("CardIcon")
        delete.setProperty("class", "danger")
        delete.setStyleSheet(
            "QPushButton { background:transparent; border:1px solid #2A343D; "
            "border-radius:6px; color:#8FA3AE; padding:5px 8px; }"
            "QPushButton:hover { color:#FF4D6D; border-color:#B92341; }"
        )
        delete.setToolTip(tr("Usuń z biblioteki"))
        delete.clicked.connect(lambda: self.delete_requested.emit(int(self.game["id"])))
        actions.addWidget(delete)
        layout.addLayout(actions)
        self.setFixedHeight(430)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.launch_requested.emit(int(self.game["id"]))
        super().mouseDoubleClickEvent(event)


class CompactGameRow(QFrame):
    launch_requested = pyqtSignal(int)
    edit_requested = pyqtSignal(int)
    delete_requested = pyqtSignal(int)
    context_requested = pyqtSignal(int, object)

    def __init__(self, game: dict[str, Any], cover: QPixmap | None, parent=None) -> None:
        super().__init__(parent)
        self.game = game
        self.setObjectName("CompactRow")
        self.setFixedHeight(104)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(
            lambda pos: self.context_requested.emit(
                int(self.game["id"]), self.mapToGlobal(pos)
            )
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 7, 10, 7)
        layout.setSpacing(12)
        cover_widget = CoverView(
            str(game.get("name", "?")), cover, bool(game.get("is_steam"))
        )
        cover_widget.setFixedSize(64, 88)
        layout.addWidget(cover_widget)
        info = QVBoxLayout()
        info.setSpacing(3)
        title = QLabel(str(game.get("name", tr("Bez nazwy"))))
        title.setObjectName("CardTitle")
        info.addWidget(title)
        path = QLabel(str(game.get("exe_path", "")))
        path.setObjectName("CardMeta")
        path.setToolTip(path.text())
        info.addWidget(path)
        bits = game.get("_bits")
        if game.get("is_steam"):
            source_text = f"STEAM  //  APPID {game.get('steam_appid', '?')}"
        else:
            source_text = "STANDALONE"
        if bits:
            source_text += f"  //  {bits}-BIT"
        source = QLabel(source_text)
        source.setObjectName("Accent")
        source.setStyleSheet("font-size:8pt; font-family:'DejaVu Sans Mono';")
        info.addWidget(source)
        layout.addLayout(info, 1)
        profile = QLabel(scaling_label(str(game.get("scaling_mode", "native"))))
        profile.setObjectName("Muted")
        profile.setMinimumWidth(170)
        layout.addWidget(profile)
        fps = QLabel(f"{int(game.get('fps_limit', 0)) or '∞'} FPS")
        fps.setObjectName("Accent")
        fps.setMinimumWidth(62)
        fps.setStyleSheet("font-family:'DejaVu Sans Mono'; font-weight:700;")
        layout.addWidget(fps)
        play = QPushButton(tr("▶  GRAJ"))
        play.setObjectName("CardPlay")
        play.clicked.connect(lambda: self.launch_requested.emit(int(self.game["id"])))
        layout.addWidget(play)
        edit = QPushButton(tr("✎"))
        edit.setObjectName("CardIcon")
        edit.setToolTip(tr("Edytuj"))
        edit.clicked.connect(lambda: self.edit_requested.emit(int(self.game["id"])))
        layout.addWidget(edit)
        delete = QPushButton(tr("×"))
        delete.setObjectName("CardIcon")
        delete.setToolTip(tr("Usuń"))
        delete.clicked.connect(lambda: self.delete_requested.emit(int(self.game["id"])))
        layout.addWidget(delete)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.launch_requested.emit(int(self.game["id"]))
        super().mouseDoubleClickEvent(event)


class GameDialog(QDialog):
    """Add/edit dialog.  All values are saved through bound SQL parameters."""

    def __init__(
        self,
        database: Database,
        game: dict[str, Any] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.db = database
        self.game = game
        self.winetricks_verbs = str((game or {}).get("winetricks_verbs", "") or "")
        self.winetricks_auto = bool(int((game or {}).get("winetricks_auto", 0) or 0))
        self.winetricks_state = str((game or {}).get("winetricks_state", "") or "")
        self._cover_source = str((game or {}).get("cover_path", ""))
        self.setWindowTitle(tr("Edytuj grę") if game else tr("Dodaj grę"))
        self.setModal(True)
        self.resize(760, 790)
        self.setWindowIcon(app_icon())
        outer = QVBoxLayout(self)
        outer.setContentsMargins(22, 18, 22, 18)
        outer.setSpacing(14)

        kicker = QLabel(
            tr(
                "BIBLIOTEKA // {section}",
                section=tr("EDYCJA") if game else tr("NOWY WPIS"),
            )
        )
        kicker.setObjectName("PageKicker")
        outer.addWidget(kicker)
        heading = QLabel(tr("Konfiguracja gry"))
        heading.setObjectName("PageTitle")
        outer.addWidget(heading)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        style_scroll_area(scroll, "#0E1114")
        form_host = QWidget()
        form = QFormLayout(form_host)
        form.setContentsMargins(2, 2, 12, 2)
        form.setSpacing(12)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.name_edit = QLineEdit(str((game or {}).get("name", "")))
        self.name_edit.setPlaceholderText(tr("Nazwa widoczna w bibliotece"))
        form.addRow(tr("Nazwa"), self.name_edit)

        self.exe_edit = QLineEdit(str((game or {}).get("exe_path", "")))
        self.exe_edit.setPlaceholderText(tr("/ścieżka/do/gry.exe"))
        form.addRow(tr("Plik EXE"), self._path_row(self.exe_edit, "file"))

        self.cover_edit = QLineEdit(self._cover_source)
        self.cover_edit.setPlaceholderText(tr("Opcjonalna okładka (JPG/PNG/WebP)"))
        cover_row = self._path_row(self.cover_edit, "image")
        clear_cover = QPushButton(tr("Wyczyść"))
        clear_cover.setObjectName("GhostButton")
        clear_cover.clicked.connect(lambda: self.cover_edit.clear())
        cover_row.layout().addWidget(clear_cover)
        form.addRow(tr("Okładka"), cover_row)

        self.runner_combo = QComboBox()
        self.runner_combo.addItem(tr("Automatycznie (domyślny runner)"), "")
        for runner in discover_runners():
            self.runner_combo.addItem(runner.label, runner.path)
        current_runner = str((game or {}).get("runner_path", ""))
        if current_runner:
            index = self.runner_combo.findData(current_runner)
            if index < 0:
                self.runner_combo.addItem(tr("Własny: {name}", name=current_runner), current_runner)
                index = self.runner_combo.count() - 1
            self.runner_combo.setCurrentIndex(index)
        runner_row = QWidget()
        runner_layout = QHBoxLayout(runner_row)
        runner_layout.setContentsMargins(0, 0, 0, 0)
        runner_layout.setSpacing(6)
        runner_layout.addWidget(self.runner_combo, 1)
        browse_runner = QPushButton("...")
        browse_runner.setObjectName("GhostButton")
        browse_runner.setFixedWidth(42)
        browse_runner.clicked.connect(self._browse_runner)
        runner_layout.addWidget(browse_runner)
        form.addRow(tr("Runner"), runner_row)

        self.prefix_edit = QLineEdit(str((game or {}).get("wine_prefix", "")))
        self.prefix_edit.setPlaceholderText(tr("Puste = izolowany prefix zostanie utworzony automatycznie"))
        prefix_row = self._path_row(self.prefix_edit, "dir")
        auto_prefix = QPushButton(tr("Nowy"))
        auto_prefix.setObjectName("GhostButton")
        auto_prefix.setToolTip(tr("Wygeneruj nowy, izolowany WINEPREFIX"))
        auto_prefix.clicked.connect(self._new_prefix)
        prefix_row.layout().addWidget(auto_prefix)
        form.addRow(tr("WINEPREFIX"), prefix_row)

        winetricks_row = QWidget()
        winetricks_layout = QHBoxLayout(winetricks_row)
        winetricks_layout.setContentsMargins(0, 0, 0, 0)
        winetricks_layout.setSpacing(8)
        self.winetricks_summary = QLabel("")
        self.winetricks_summary.setObjectName("Muted")
        self.winetricks_summary.setWordWrap(True)
        winetricks_layout.addWidget(self.winetricks_summary, 1)
        manage_winetricks = QPushButton(tr("Zarządzaj…"))
        manage_winetricks.setObjectName("GhostButton")
        manage_winetricks.clicked.connect(self._manage_winetricks)
        winetricks_layout.addWidget(manage_winetricks)
        self.winetricks_auto_cb = QCheckBox(tr("Auto przed startem"))
        self.winetricks_auto_cb.setChecked(self.winetricks_auto)
        winetricks_layout.addWidget(self.winetricks_auto_cb)
        form.addRow(tr("Winetricks"), winetricks_row)
        self._refresh_winetricks_summary()

        self.env_edit = QPlainTextEdit(str((game or {}).get("env_vars", "")))
        self.env_edit.setPlaceholderText(
            tr("DXVK_HUD=0\nWINE_FULLSCREEN_FSR=1\nMESA_VK_WSI_PRESENT_MODE=mailbox"))

        self.env_edit.setFixedHeight(100)
        form.addRow(tr("Zmienne env"), self.env_edit)

        self.args_edit = QLineEdit(str((game or {}).get("launch_args", "")))
        self.args_edit.setPlaceholderText(tr('-windowed -novid +fps_max 144'))
        form.addRow(tr("Argumenty"), self.args_edit)

        self.scaling_combo = QComboBox()
        for key, profile in SCALING_PROFILES.items():
            self.scaling_combo.addItem(str(profile["label"]), key)
        scaling = str((game or {}).get("scaling_mode", "native"))
        index = self.scaling_combo.findData(scaling)
        self.scaling_combo.setCurrentIndex(max(0, index))
        form.addRow(tr("Skalowanie"), self.scaling_combo)
        self.scaling_note = QLabel("")
        self.scaling_note.setObjectName("Muted")
        self.scaling_note.setWordWrap(True)
        form.addRow("", self.scaling_note)
        self.scaling_combo.currentIndexChanged.connect(self._update_scaling_note)
        self._update_scaling_note()

        self.fps_combo = QComboBox()
        for value in FPS_LIMITS:
            self.fps_combo.addItem(tr("Bez limitu") if value == 0 else f"{value} FPS", value)
        fps = int((game or {}).get("fps_limit", 0))
        index = self.fps_combo.findData(fps)
        self.fps_combo.setCurrentIndex(max(0, index))
        form.addRow(tr("Limit FPS"), self.fps_combo)

        if game and game.get("is_steam"):
            steam_host = QWidget()
            steam_layout = QVBoxLayout(steam_host)
            steam_layout.setContentsMargins(0, 0, 0, 0)
            steam_layout.setSpacing(6)
            steam_info = QLabel(
                tr(
                    "<span style='color:#00E5FF'>STEAM</span>  AppID {appid} — "
                    "wpis zaimportowany. Uruchamianie odbywa się przez klienta "
                    "Steam; wrapper aplikuje MangoHud, skalowanie i limit FPS. "
                    "Runner i WINEPREFIX są właściwościami Steam/Protona.",
                    appid=html.escape(str(game.get("steam_appid", ""))),
                )
            )
            steam_info.setWordWrap(True)
            steam_layout.addWidget(steam_info)
            copy_option = QPushButton(tr("KOPIUJ OPCJĘ URUCHAMIANIA STEAM"))
            copy_option.setObjectName("GhostButton")
            copy_option.clicked.connect(self._copy_steam_option)
            steam_layout.addWidget(copy_option, 0, Qt.AlignmentFlag.AlignLeft)
            form.addRow(tr("Źródło"), steam_host)

        note = QLabel(
            tr("Runner i prefix są izolowane per gra. Zmienne env: jedna para "
            "KEY=VALUE na linię. Argumenty są dzielone jak w POSIX shell.")
 )
        note.setObjectName("Muted")
        note.setWordWrap(True)
        form.addRow("", note)
        scroll.setWidget(form_host)
        outer.addWidget(scroll, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        save_button = buttons.button(QDialogButtonBox.StandardButton.Save)
        cancel_button = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        if save_button:
            save_button.setText(tr("ZAPISZ"))
            save_button.setObjectName("PrimaryButton")
        if cancel_button:
            cancel_button.setText(tr("ANULUJ"))
            cancel_button.setObjectName("GhostButton")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

    def _path_row(self, line_edit: QLineEdit, mode: str) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(line_edit, 1)
        button = QPushButton("...")
        button.setObjectName("GhostButton")
        button.setFixedWidth(42)
        button.clicked.connect(partial(self._browse, line_edit, mode))
        layout.addWidget(button)
        return row

    def _browse(self, line_edit: QLineEdit, mode: str) -> None:
        initial = line_edit.text().strip() or str(Path.home())
        if mode == "file":
            path, _ = QFileDialog.getOpenFileName(
                self,
                tr("Wybierz plik EXE"),
                initial,
                tr("Programy Windows (*.exe *.EXE);;Wszystkie pliki (*)"),
            )
        elif mode == "image":
            path, _ = QFileDialog.getOpenFileName(
                self,
                tr("Wybierz okładkę"),
                initial,
                tr("Obrazy (*.png *.jpg *.jpeg *.webp *.bmp);;Wszystkie pliki (*)"),
            )
        else:
            path = QFileDialog.getExistingDirectory(
                self, tr("Wybierz katalog"), initial
            )
        if path:
            line_edit.setText(path)

    def _browse_runner(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            tr("Wskaż plik wine"),
            str(db.RUNNERS_DIR),
            tr("Wine (wine wine64);;Wszystkie pliki (*)"),
        )
        if not path:
            return
        index = self.runner_combo.findData(path)
        if index < 0:
            self.runner_combo.addItem(tr("Własny: {name}", name=path), path)
            index = self.runner_combo.count() - 1
        self.runner_combo.setCurrentIndex(index)

    def _new_prefix(self) -> None:
        self.prefix_edit.setText(db.make_prefix(self.name_edit.text() or "game"))
        self.winetricks_state = ""
        self._refresh_winetricks_summary()

    def _refresh_winetricks_summary(self) -> None:
        try:
            verbs = normalize_winetricks_verbs(self.winetricks_verbs)
        except ValueError:
            verbs = []
        if verbs:
            self.winetricks_summary.setText(
                tr("Komponenty: {verbs}", verbs=" ".join(verbs))
            )
        else:
            self.winetricks_summary.setText(tr("Brak wybranych komponentów."))

    def _manage_winetricks(self) -> None:
        self.winetricks_auto = self.winetricks_auto_cb.isChecked()
        snapshot: dict[str, Any] = {
            "name": self.name_edit.text().strip() or "game",
            "exe_path": self.exe_edit.text().strip(),
            "runner_path": str(self.runner_combo.currentData() or ""),
            "wine_prefix": self.prefix_edit.text().strip(),
            "env_vars": self.env_edit.toPlainText(),
            "is_steam": int((self.game or {}).get("is_steam", 0)),
            "steam_appid": str((self.game or {}).get("steam_appid", "")),
            "winetricks_verbs": self.winetricks_verbs,
            "winetricks_auto": 1 if self.winetricks_auto else 0,
            "winetricks_state": self.winetricks_state,
        }
        if self.game and self.game.get("id"):
            snapshot["id"] = self.game["id"]
        dialog = WinetricksDialog(self.db, snapshot, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.winetricks_verbs = dialog.verbs_text()
            self.winetricks_auto = dialog.auto_install()
            self.winetricks_state = dialog.state()
            self.prefix_edit.setText(dialog.prefix_path())
            self.winetricks_auto_cb.setChecked(self.winetricks_auto)
            self._refresh_winetricks_summary()

    def _update_scaling_note(self) -> None:
        key = str(self.scaling_combo.currentData() or "native")
        profile = SCALING_PROFILES.get(key, SCALING_PROFILES["native"])
        needs_gamescope = profile.get("kind") in {"gamescope", "crt"}
        if needs_gamescope and not shutil.which("gamescope"):
            self.scaling_note.setText(
                tr("Gamescope nie jest zainstalowany na tym systemie. Profil "
                "zostanie pominięty, a gra uruchomi się natywnie. Zainstaluj "
                "Gamescope lub użyj profilu Proton FSR.")
)
        elif needs_gamescope:
            self.scaling_note.setText(
                tr("Profil wymaga Gamescope — wykryto Gamescope w PATH.")
 )
        else:
            self.scaling_note.setText("")

    def _copy_steam_option(self) -> None:
        try:
            path = ensure_steam_wrapper()
        except OSError as exc:
            QMessageBox.warning(self, tr("Steam wrapper"), str(exc))
            return
        self.db.set_setting("steam_wrapper", str(path))
        QApplication.clipboard().setText(steam_launch_option(path))
        QMessageBox.information(
            self,
            tr("Steam wrapper"),
            tr("Opcja uruchamiania została skopiowana do schowka.\n\n"
            "Wklej ją w Steam → Właściwości gry → Opcje uruchamiania."),
        )

    def _import_cover(self, path: str) -> str:
        if not path:
            return ""
        source = Path(path).expanduser()
        if not source.is_file():
            raise ValueError(tr("Wybrany plik okładki nie istnieje."))
        try:
            if source.resolve().parent == db.COVERS_DIR.resolve():
                return str(source.resolve())
        except OSError:
            pass
        pixmap = QPixmap(str(source))
        if pixmap.isNull():
            raise ValueError(tr("Nie można odczytać wybranego obrazu."))
        suffix = source.suffix.lower() if source.suffix else ".jpg"
        if suffix not in {".png", ".jpg", ".jpeg", ".webp", ".bmp"}:
            suffix = ".jpg"
        destination = db.COVERS_DIR / f"local_{uuid.uuid4().hex}{suffix}"
        shutil.copyfile(source, destination)
        return str(destination)

    def _save(self) -> None:
        try:
            name = self.name_edit.text().strip()
            exe = self.exe_edit.text().strip()
            if not name:
                raise ValueError(tr("Podaj nazwę gry."))
            if not exe:
                raise ValueError(tr("Wskaż plik EXE gry."))
            env_text = self.env_edit.toPlainText()
            parse_env_vars(env_text)
            args = self.args_edit.text().strip()
            if args:
                shlex.split(args, posix=True)
            is_steam = int((self.game or {}).get("is_steam", 0))
            prefix = self.prefix_edit.text().strip()
            if not prefix and not is_steam:
                prefix = db.make_prefix(name)
            elif prefix:
                Path(prefix).expanduser().mkdir(parents=True, exist_ok=True)
            cover = self._import_cover(self.cover_edit.text().strip())
            values = {
                "name": name,
                "exe_path": exe,
                "runner_path": str(self.runner_combo.currentData() or ""),
                "wine_prefix": prefix,
                "env_vars": env_text,
                "launch_args": args,
                "scaling_mode": str(self.scaling_combo.currentData() or "native"),
                "fps_limit": int(self.fps_combo.currentData() or 0),
                "is_steam": is_steam,
                "steam_appid": str((self.game or {}).get("steam_appid", "")),
                "cover_path": cover,
                "winetricks_verbs": self.winetricks_verbs,
                "winetricks_auto": 1 if self.winetricks_auto_cb.isChecked() else 0,
                "winetricks_state": self.winetricks_state,
            }
            if self.game:
                self.db.update_game(int(self.game["id"]), **values)
            else:
                self.db.add_game(**values)
        except Exception as exc:
            QMessageBox.warning(self, tr("Nie zapisano"), str(exc))
            return
        self.accept()
WINETRICKS_PRESETS = (
    ("physx", "PhysX (starsze gry)"),
    ("vcrun2022", "Visual C++ 2015–2022"),
    ("d3dx9", "DirectX 9"),
    ("xact", "XACT"),
    ("dotnet48", ".NET Framework 4.8"),
    ("mf", "Media Foundation"),
    ("corefonts", "Czcionki Core"),
)


class WinetricksDialog(QDialog):
    """Per-game Winetricks manager for Wine, Proton and Steam prefixes."""

    def __init__(
        self,
        database: Database,
        game: dict[str, Any],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.db = database
        self.game = dict(game)
        self._worker: WinetricksWorker | None = None
        self._install_worker: WinetricksInstallWorker | None = None
        self._active_plan: WinetricksPlan | None = None
        self.setWindowTitle(
            tr("Winetricks — {name}", name=self.game.get("name") or tr("Gra"))
        )
        self.setModal(True)
        self.resize(780, 760)
        self.setWindowIcon(app_icon())

        outer = QVBoxLayout(self)
        outer.setContentsMargins(22, 18, 22, 18)
        outer.setSpacing(12)
        kicker = QLabel(tr("NARZĘDZIA // WINETRICKS"))
        kicker.setObjectName("PageKicker")
        outer.addWidget(kicker)
        heading = QLabel(tr("Komponenty Windows"))
        heading.setObjectName("PageTitle")
        outer.addWidget(heading)
        self.mode_label = QLabel("")
        self.mode_label.setObjectName("Muted")
        self.mode_label.setWordWrap(True)
        outer.addWidget(self.mode_label)

        presets = QGroupBox(tr("KOMPONENTY"))
        presets_layout = QGridLayout(presets)
        presets_layout.setHorizontalSpacing(18)
        presets_layout.setVerticalSpacing(8)
        selected = set()
        try:
            selected = set(
                normalize_winetricks_verbs(str(self.game.get("winetricks_verbs", "")))
            )
        except ValueError:
            selected = set()
        preset_verbs = {verb for verb, _label in WINETRICKS_PRESETS}
        self.preset_checks: dict[str, QCheckBox] = {}
        for index, (verb, label) in enumerate(WINETRICKS_PRESETS):
            check = QCheckBox(tr(label))
            check.setChecked(verb in selected)
            check.toggled.connect(self._refresh_status)
            self.preset_checks[verb] = check
            presets_layout.addWidget(check, index // 2, index % 2)
        presets_layout.addWidget(QLabel(tr("Własne komponenty")), 4, 0, 1, 2)
        self.custom_edit = QLineEdit(
            " ".join(sorted(selected - preset_verbs))
        )
        self.custom_edit.setPlaceholderText(tr("np. quartz wmp10"))
        self.custom_edit.textChanged.connect(self._refresh_status)
        presets_layout.addWidget(self.custom_edit, 5, 0, 1, 2)
        outer.addWidget(presets)

        self.auto_cb = QCheckBox(
            tr("Zainstaluj wybrane komponenty przed pierwszym startem gry")
        )
        self.auto_cb.setChecked(bool(int(self.game.get("winetricks_auto", 0) or 0)))
        outer.addWidget(self.auto_cb)

        self.dep_label = QLabel("")
        self.dep_label.setObjectName("Muted")
        self.dep_label.setWordWrap(True)
        outer.addWidget(self.dep_label)
        self.status_label = QLabel("")
        self.status_label.setObjectName("Muted")
        self.status_label.setWordWrap(True)
        outer.addWidget(self.status_label)

        actions = QHBoxLayout()
        self.install_button = QPushButton(tr("ZAINSTALUJ WYBRANE"))
        self.install_button.setObjectName("PrimaryButton")
        self.install_button.clicked.connect(self._install_selected)
        actions.addWidget(self.install_button)
        self.download_button = QPushButton(tr("ZAINSTALUJ WINETRICKS"))
        self.download_button.setObjectName("GhostButton")
        self.download_button.clicked.connect(self._install_winetricks)
        actions.addWidget(self.download_button)
        refresh = QPushButton(tr("ODŚWIEŻ STATUS"))
        refresh.setObjectName("GhostButton")
        refresh.clicked.connect(self._refresh_status)
        actions.addWidget(refresh)
        actions.addStretch(1)
        close = QPushButton(tr("ZAMKNIJ"))
        close.setObjectName("GhostButton")
        close.clicked.connect(self.accept)
        actions.addWidget(close)
        outer.addLayout(actions)

        log_title = QLabel(tr("Log instalacji"))
        log_title.setObjectName("SectionTitle")
        outer.addWidget(log_title)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMinimumHeight(180)
        outer.addWidget(self.log_view, 1)

        self._refresh_status()

    def _mode_text(self) -> str:
        if int(self.game.get("is_steam", 0) or 0):
            return tr(
                "Steam AppID {appid} — prefiksem zarządza Steam, więc używany "
                "jest protontricks.",
                appid=self.game.get("steam_appid", ""),
            )
        runner = resolve_runner(
            str(self.game.get("runner_path", "")),
            str(self.db.get_setting("default_runner", "")),
        )
        prefix = str(self.game.get("wine_prefix", "") or tr("brak"))
        runner_name = runner.label if runner is not None else tr("brak")
        return tr(
            "Runner: {runner}  |  Prefiks: {prefix}",
            runner=runner_name,
            prefix=prefix,
        )

    def _ensure_prefix(self) -> None:
        if int(self.game.get("is_steam", 0) or 0):
            return
        if not str(self.game.get("wine_prefix", "") or "").strip():
            self.game["wine_prefix"] = db.make_prefix(
                str(self.game.get("name") or "game")
            )

    def selected_verbs(self) -> list[str]:
        verbs = [
            verb for verb, check in self.preset_checks.items() if check.isChecked()
        ]
        verbs.extend(normalize_winetricks_verbs(self.custom_edit.text()))
        return normalize_winetricks_verbs(verbs)

    def verbs_text(self) -> str:
        try:
            return winetricks_verbs_text(self.selected_verbs())
        except ValueError:
            return str(self.game.get("winetricks_verbs", ""))

    def auto_install(self) -> bool:
        return self.auto_cb.isChecked()

    def state(self) -> str:
        return str(self.game.get("winetricks_state", "") or "")

    def prefix_path(self) -> str:
        return str(self.game.get("wine_prefix", "") or "")

    def _save_settings(self) -> None:
        try:
            verbs = winetricks_verbs_text(self.selected_verbs())
        except ValueError:
            return
        self.game["winetricks_verbs"] = verbs
        self.game["winetricks_auto"] = 1 if self.auto_cb.isChecked() else 0
        game_id = self.game.get("id")
        if game_id:
            self.db.update_game(
                int(game_id),
                wine_prefix=self.prefix_path(),
                winetricks_verbs=verbs,
                winetricks_auto=self.game["winetricks_auto"],
                winetricks_state=self.state(),
            )

    def _refresh_status(self) -> None:
        if getattr(self, "install_button", None) is None:
            return
        self._ensure_prefix()
        self.mode_label.setText(self._mode_text())
        is_steam = bool(int(self.game.get("is_steam", 0) or 0))
        winetricks = winetricks_path()
        protontricks = protontricks_path()
        winetricks_status = (
            tr("Winetricks: {path}", path=winetricks)
            if winetricks
            else tr("Winetricks: brak. Użyj przycisku instalacji poniżej.")
        )
        if is_steam:
            protontricks_status = (
                tr("Protontricks: {path}", path=protontricks)
                if protontricks
                else tr(
                    "Protontricks: brak. Zainstaluj protontricks, aby używać "
                    "Winetricks dla gier Steam."
                )
            )
            dependency = f"{protontricks_status}\n{winetricks_status}"
        else:
            dependency = winetricks_status
        self.dep_label.setText(dependency)
        self.download_button.setVisible(not winetricks)
        self.download_button.setEnabled(self._install_worker is None)
        if self._worker is not None or self._install_worker is not None:
            return
        try:
            verbs = self.selected_verbs()
        except ValueError as exc:
            self.status_label.setText(str(exc))
            self.install_button.setEnabled(False)
            return
        if not verbs:
            self.status_label.setText(tr("Wybierz komponenty do zainstalowania."))
            self.install_button.setEnabled(False)
            return
        try:
            plan = build_winetricks_plan(self.db, self.game, verbs)
        except Exception as exc:
            self.status_label.setText(str(exc))
            self.install_button.setEnabled(False)
            return
        if winetricks_applied(self.game, plan):
            self.status_label.setText(
                tr("Wybrane komponenty są już zainstalowane w tym prefiksie.")
            )
        else:
            self.status_label.setText(
                tr("Wybrane komponenty wymagają instalacji: {verbs}", verbs=" ".join(verbs))
            )
        self.install_button.setEnabled(True)

    def _set_busy(self, busy: bool) -> None:
        self.install_button.setEnabled(not busy)
        self.download_button.setEnabled(not busy and not self.download_button.isHidden())
        for check in self.preset_checks.values():
            check.setEnabled(not busy)
        self.custom_edit.setEnabled(not busy)
        self.auto_cb.setEnabled(not busy)

    def _install_winetricks(self) -> None:
        if self._install_worker is not None:
            return
        answer = QMessageBox.question(
            self,
            tr("Winetricks"),
            tr("Pobrać oficjalny skrypt Winetricks z GitHuba?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._install_worker = WinetricksInstallWorker(self)
        self._install_worker.status.connect(self.status_label.setText)
        self._install_worker.progress.connect(
            lambda percent: self.status_label.setText(
                tr("Pobieram Winetricks... {percent}%", percent=percent)
            )
        )
        self._install_worker.result.connect(self._winetricks_installed)
        self._set_busy(True)
        self._install_worker.start()

    def _winetricks_installed(self, success: bool, message: str) -> None:
        worker = self._install_worker
        self._install_worker = None
        if worker is not None:
            worker.deleteLater()
        self._set_busy(False)
        self._refresh_status()
        if success:
            QMessageBox.information(
                self,
                tr("Winetricks"),
                tr("Winetricks został zainstalowany:\n{path}", path=message),
            )
        else:
            QMessageBox.warning(self, tr("Winetricks"), message)

    def _install_selected(self) -> None:
        if self._worker is not None:
            return
        try:
            verbs = self.selected_verbs()
            plan = build_winetricks_plan(self.db, self.game, verbs)
        except Exception as exc:
            QMessageBox.warning(self, tr("Winetricks"), str(exc))
            self._refresh_status()
            return
        self._save_settings()
        answer = QMessageBox.question(
            self,
            tr("Winetricks"),
            tr(
                "Zainstalować w tym prefiksie następujące komponenty?\n\n{verbs}",
                verbs="\n".join(f"• {verb}" for verb in verbs),
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._active_plan = plan
        self._worker = WinetricksWorker(plan, self)
        self._worker.output.connect(self.log_view.appendPlainText)
        self._worker.result.connect(self._winetricks_finished)
        self._set_busy(True)
        self.status_label.setText(tr("Instaluję komponenty Winetricks..."))
        self.log_view.clear()
        self._worker.start()

    def _winetricks_finished(self, success: bool, message: str) -> None:
        worker = self._worker
        self._worker = None
        if worker is not None:
            worker.deleteLater()
        self._set_busy(False)
        plan = self._active_plan
        self._active_plan = None
        if success and plan is not None:
            self.game["winetricks_state"] = plan.state
            self._save_settings()
            self.status_label.setText(tr("Komponenty Winetricks zostały zainstalowane."))
            QMessageBox.information(
                self,
                tr("Winetricks"),
                tr("Komponenty zostały zainstalowane.\n\nLog: {path}", path=message),
            )
        else:
            self.status_label.setText(message)
            QMessageBox.warning(self, tr("Winetricks"), message)
        self._refresh_status()

    def done(self, result: int) -> None:  # noqa: A003
        if self._worker is not None:
            self._worker.cancel()
            self._worker.wait(5000)
        if self._install_worker is not None:
            self._install_worker.wait(5000)
        self._save_settings()
        super().done(result)


class SettingsPage(QWidget):
    toast = pyqtSignal(str)
    steam_sync_requested = pyqtSignal()
    steam_wrapper_batch_requested = pyqtSignal()
    steam_restore_requested = pyqtSignal()
    clear_cache_requested = pyqtSignal()
    settings_changed = pyqtSignal()
    theme_changed = pyqtSignal(str)
    language_changed = pyqtSignal(str)

    def __init__(self, database: Database, parent=None) -> None:
        super().__init__(parent)
        self.db = database
        self._dep_process: QProcess | None = None
        self._dep_queue: list[DependencyGroup] = []
        self._dep_failures: list[str] = []
        self._m32_process: QProcess | None = None
        self._gamepad_process: QProcess | None = None
        self._winetricks_install_worker: WinetricksInstallWorker | None = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 20)
        outer.setSpacing(16)
        kicker = QLabel(tr("SYSTEM // GLOBAL"))
        kicker.setObjectName("PageKicker")
        outer.addWidget(kicker)
        heading = QLabel(tr("Ustawienia globalne"))
        heading.setObjectName("PageTitle")
        outer.addWidget(heading)
        subtitle = QLabel(
            tr("Wspólny runner, środowisko oraz polityka uruchamiania. "
            "Ustawienia per gra nadpisują runner i prefix.")
)
        subtitle.setObjectName("PageSubtitle")
        outer.addWidget(subtitle)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        style_scroll_area(scroll)
        host = QWidget()
        body = QVBoxLayout(host)
        body.setContentsMargins(0, 4, 8, 8)
        body.setSpacing(14)

        appearance, appearance_layout = self._panel(
            tr("WYGLĄD"),
            tr("Motyw interfejsu, okna konsolowego, tray i ikony aplikacji."),
        )
        appearance_form = QFormLayout()
        appearance_form.setSpacing(11)
        self.language_combo = QComboBox()
        for code, name in LANGUAGES.items():
            self.language_combo.addItem(name, code)
        appearance_form.addRow(tr("Język"), self.language_combo)
        self.theme_combo = QComboBox()
        for key, theme in THEMES.items():
            self.theme_combo.addItem(theme.name, key)
        appearance_form.addRow(tr("Motyw"), self.theme_combo)
        self.console_monitor_combo = QComboBox()
        appearance_form.addRow(tr("Monitor konsoli"), self.console_monitor_combo)
        appearance_layout.addLayout(appearance_form)
        theme_preview = QLabel(
            tr("Zmiana motywu działa od razu. Kolory MangoHud pozostają osobnym "
            "profilem nakładki.")
        )
        theme_preview.setObjectName("Muted")
        theme_preview.setWordWrap(True)
        appearance_layout.addWidget(theme_preview)
        self.theme_combo.currentIndexChanged.connect(self._theme_selected)
        self.language_combo.currentIndexChanged.connect(self._language_selected)
        body.addWidget(appearance)

        runtime, runtime_layout = self._panel(
            tr("RUNTIME"), tr("Domyślny silnik i dostępne integracje.")
        )
        form = QFormLayout()
        form.setSpacing(11)
        self.runner_combo = QComboBox()
        form.addRow(tr("Domyślny runner"), self.runner_combo)
        runtime_layout.addLayout(form)
        checks = QGridLayout()
        checks.setHorizontalSpacing(28)
        checks.setVerticalSpacing(10)
        self.gamemode_cb = QCheckBox(tr("Feral GameMode (gamemoderun)"))
        self.mangohud_cb = QCheckBox(tr("MangoHud overlay"))
        self.gamescope_cb = QCheckBox(tr("Gamescope / skalowanie"))
        self.debug_cb = QCheckBox(tr("Debug: zapis do last_run.log"))
        self.ghost_cb = QCheckBox(tr("Minimalizuj Boostlayer po starcie gry"))
        self.tray_cb = QCheckBox(tr("Zamykanie okna do tray"))
        self.hotkey_cb = QCheckBox(tr("Globalny skrót Ctrl+Alt+S (pokaż/ukryj)"))
        checks.addWidget(self.gamemode_cb, 0, 0)
        checks.addWidget(self.mangohud_cb, 0, 1)
        checks.addWidget(self.gamescope_cb, 1, 0)
        checks.addWidget(self.debug_cb, 1, 1)
        checks.addWidget(self.ghost_cb, 2, 0)
        checks.addWidget(self.tray_cb, 2, 1)
        checks.addWidget(self.hotkey_cb, 3, 0)
        runtime_layout.addLayout(checks)
        hint = QLabel(
            tr("Po starcie gry Boostlayer minimalizuje się do paska zadań i "
            "pozostaje w pamięci. Gra standalone jest nadzorowana przez "
            "QProcess; po jej zakończeniu okno wraca. Steam nie daje "
            "niezawodnego sygnału końca gry, więc wracasz przez tray lub "
            "Ctrl+Alt+S."))

        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        runtime_layout.addWidget(hint)
        body.addWidget(runtime)

        steam_panel, steam_layout = self._panel(
            tr("STEAM"), tr("Import appmanifest_*.acf i okładek z lokalnego cache/CDN.")
        )
        steam_row = QWidget()
        steam_row_layout = QHBoxLayout(steam_row)
        steam_row_layout.setContentsMargins(0, 0, 0, 0)
        steam_row_layout.setSpacing(6)
        self.steam_edit = QLineEdit()
        self.steam_edit.setPlaceholderText(
            tr("Automatyczne wykrywanie: ~/.steam/steam, ~/.local/share/Steam, Flatpak"))

        steam_row_layout.addWidget(self.steam_edit, 1)
        browse = QPushButton("...")
        browse.setObjectName("GhostButton")
        browse.setFixedWidth(42)
        browse.clicked.connect(self._browse_steam)
        steam_row_layout.addWidget(browse)
        steam_layout.addWidget(steam_row)
        steam_actions = QHBoxLayout()
        sync_button = QPushButton(tr("↻  SYNCHRONIZUJ STEAM"))
        sync_button.setObjectName("GhostButton")
        sync_button.clicked.connect(self.steam_sync_requested.emit)
        steam_actions.addWidget(sync_button)
        steam_actions.addStretch(1)
        steam_layout.addLayout(steam_actions)
        body.addWidget(steam_panel)

        wrapper_panel, wrapper_layout = self._panel(
            tr("STEAM WRAPPER"),
            tr("Nakłada MangoHud, Gamescope, GameMode i limit FPS również na gry "
            "uruchamiane z klienta Steam."),
        )
        self.wrapper_status = QLabel("")
        self.wrapper_status.setObjectName("Muted")
        self.wrapper_status.setWordWrap(True)
        self.wrapper_status.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        wrapper_layout.addWidget(self.wrapper_status)
        self.auto_wrapper_cb = QCheckBox(
            tr("Automatycznie dopisuj wrapper przy pierwszym starcie gry Steam"))

        wrapper_layout.addWidget(self.auto_wrapper_cb)
        wrapper_actions = QHBoxLayout()
        install_wrapper = QPushButton(tr("ZAINSTALUJ / ODŚWIEŻ WRAPPER"))
        install_wrapper.setObjectName("GhostButton")
        install_wrapper.clicked.connect(self._install_wrapper)
        wrapper_actions.addWidget(install_wrapper)
        copy_wrapper = QPushButton(tr("KOPIUJ OPCJĘ URUCHAMIANIA"))
        copy_wrapper.setObjectName("GhostButton")
        copy_wrapper.clicked.connect(self._copy_wrapper_option)
        wrapper_actions.addWidget(copy_wrapper)
        wrapper_actions.addStretch(1)
        wrapper_layout.addLayout(wrapper_actions)
        wrapper_batch = QHBoxLayout()
        apply_all = QPushButton(tr("ZASTOSUJ DO WSZYSTKICH GIER STEAM"))
        apply_all.setObjectName("PrimaryButton")
        apply_all.clicked.connect(self.steam_wrapper_batch_requested.emit)
        wrapper_batch.addWidget(apply_all)
        restore = QPushButton(tr("PRZYWRÓĆ OSTATNI BACKUP"))
        restore.setObjectName("GhostButton")
        restore.clicked.connect(self.steam_restore_requested.emit)
        wrapper_batch.addWidget(restore)
        wrapper_batch.addStretch(1)
        wrapper_layout.addLayout(wrapper_batch)
        wrapper_hint = QLabel(
            tr("Wpis zawiera %command%, więc Steam nadal uruchamia swojego Protona. "
            "Aby zapisać LaunchOptions, Steam musi być zamknięty; aplikacja "
            "zapyta przed zamknięciem i zrobi backup localconfig.vdf.")
)
        wrapper_hint.setObjectName("Muted")
        wrapper_hint.setWordWrap(True)
        wrapper_layout.addWidget(wrapper_hint)
        body.addWidget(wrapper_panel)

        deps_panel, deps_layout = self._panel(
            tr("ZALEŻNOŚCI"),
            tr("MangoHud i GameMode są instalowane przez pakiet .deb. "
            "W AppImage użyj przycisku instalacji (pkexec)."),
        )
        self.deps_label = QLabel()
        self.deps_label.setTextFormat(Qt.TextFormat.RichText)
        self.deps_label.setWordWrap(True)
        deps_layout.addWidget(self.deps_label)
        deps_actions = QHBoxLayout()
        refresh_deps = QPushButton(tr("ODŚWIEŻ STATUS"))
        refresh_deps.setObjectName("GhostButton")
        refresh_deps.clicked.connect(self._refresh_deps)
        deps_actions.addWidget(refresh_deps)
        self.install_deps_button = QPushButton(tr("ZAINSTALUJ BRAKUJĄCE"))
        self.install_deps_button.setObjectName("PrimaryButton")
        self.install_deps_button.clicked.connect(self._install_dependencies)
        deps_actions.addWidget(self.install_deps_button)
        self.install_m32_button = QPushButton(tr("MANGOHUD 32-BIT"))
        self.install_m32_button.setObjectName("GhostButton")
        self.install_m32_button.clicked.connect(self._install_mangohud32)
        deps_actions.addWidget(self.install_m32_button)
        self.install_winetricks_button = QPushButton(tr("ZAINSTALUJ WINETRICKS"))
        self.install_winetricks_button.setObjectName("GhostButton")
        self.install_winetricks_button.clicked.connect(self._install_winetricks)
        deps_actions.addWidget(self.install_winetricks_button)
        self.gamepad_udev_button = QPushButton(tr("WŁĄCZ OBSŁUGĘ PADA"))
        self.gamepad_udev_button.setObjectName("GhostButton")
        self.gamepad_udev_button.clicked.connect(self._install_gamepad_udev)
        deps_actions.addWidget(self.gamepad_udev_button)
        deps_actions.addStretch(1)
        deps_layout.addLayout(deps_actions)
        self.deps_output = QLabel("")
        self.deps_output.setObjectName("Muted")
        self.deps_output.setWordWrap(True)
        self.deps_output.setTextFormat(Qt.TextFormat.PlainText)
        deps_layout.addWidget(self.deps_output)
        body.addWidget(deps_panel)

        maint_panel, maint_layout = self._panel(
            tr("KONSERWACJA"), tr("Logi, konfiguracja i cache shaderów.")
        )
        self.config_label = QLabel(str(config_dir()))
        self.config_label.setObjectName("Muted")
        self.config_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        maint_layout.addWidget(self.config_label)
        maint_buttons = QHBoxLayout()
        for text, slot, style in (
            (tr("POKAŻ LAST_RUN.LOG"), self.open_log, "GhostButton"),
            (tr("OTWÓRZ KONFIGURACJĘ"), self.open_config, "GhostButton"),
            (tr("WYCZYŚĆ SHADER CACHE"), self.clear_cache_requested.emit, "DangerButton"),
        ):
            button = QPushButton(text)
            button.setObjectName(style)
            button.clicked.connect(slot)
            maint_buttons.addWidget(button)
        maint_buttons.addStretch(1)
        maint_layout.addLayout(maint_buttons)
        body.addWidget(maint_panel)
        body.addStretch(1)
        scroll.setWidget(host)
        outer.addWidget(scroll, 1)

        footer = QHBoxLayout()
        self.status_label = QLabel("")
        self.status_label.setObjectName("Muted")
        footer.addWidget(self.status_label)
        footer.addStretch(1)
        save = QPushButton(tr("ZAPISZ USTAWIENIA"))
        save.setObjectName("PrimaryButton")
        save.clicked.connect(self.save)
        footer.addWidget(save)
        outer.addLayout(footer)
        self.reload()

    def _panel(self, title: str, subtitle: str = "") -> tuple[QFrame, QVBoxLayout]:
        frame = QFrame()
        frame.setObjectName("Panel")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)
        title_label = QLabel(title)
        title_label.setObjectName("SectionTitle")
        layout.addWidget(title_label)
        if subtitle:
            sub = QLabel(subtitle)
            sub.setObjectName("Muted")
            sub.setWordWrap(True)
            layout.addWidget(sub)
        return frame, layout

    def reload(self) -> None:
        language_key = self.db.get_setting("language", DEFAULT_LANGUAGE)
        language_index = self.language_combo.findData(language_key)
        self.language_combo.blockSignals(True)
        self.language_combo.setCurrentIndex(max(0, language_index))
        self.language_combo.blockSignals(False)
        theme_key = self.db.get_setting("theme", DEFAULT_THEME)
        index = self.theme_combo.findData(theme_key)
        self.theme_combo.blockSignals(True)
        self.theme_combo.setCurrentIndex(max(0, index))
        self.theme_combo.blockSignals(False)
        self._refresh_console_monitors()
        self.gamemode_cb.setChecked(self.db.get_bool("gamemode", True))
        self.mangohud_cb.setChecked(self.db.get_bool("mangohud", True))
        self.gamescope_cb.setChecked(self.db.get_bool("gamescope", True))
        self.debug_cb.setChecked(self.db.get_bool("debug_logging", False))
        self.ghost_cb.setChecked(self.db.get_bool("ghost_mode", True))
        self.tray_cb.setChecked(self.db.get_bool("close_to_tray", True))
        self.hotkey_cb.setChecked(self.db.get_bool("global_hotkey", True))
        self.auto_wrapper_cb.setChecked(
            self.db.get_bool("auto_steam_wrapper", True)
        )
        self.steam_edit.setText(self.db.get_setting("steam_path"))
        self._refresh_wrapper_status()
        self.refresh_runners()
        self._refresh_deps()

    def refresh_runners(self) -> None:
        selected = self.db.get_setting("default_runner")
        self.runner_combo.blockSignals(True)
        self.runner_combo.clear()
        self.runner_combo.addItem(tr("Automatycznie (pierwszy dostępny)"), "")
        for runner in discover_runners():
            self.runner_combo.addItem(runner.label, runner.path)
        index = self.runner_combo.findData(selected)
        if index < 0 and selected:
            self.runner_combo.addItem(tr("Własny: {name}", name=selected), selected)
            index = self.runner_combo.count() - 1
        self.runner_combo.setCurrentIndex(max(0, index))
        self.runner_combo.blockSignals(False)

    def save(self) -> None:
        self.db.set_many(
            {
                "default_runner": str(self.runner_combo.currentData() or ""),
                "gamemode": "1" if self.gamemode_cb.isChecked() else "0",
                "mangohud": "1" if self.mangohud_cb.isChecked() else "0",
                "gamescope": "1" if self.gamescope_cb.isChecked() else "0",
                "debug_logging": "1" if self.debug_cb.isChecked() else "0",
                "ghost_mode": "1" if self.ghost_cb.isChecked() else "0",
                "close_to_tray": "1" if self.tray_cb.isChecked() else "0",
                "global_hotkey": "1" if self.hotkey_cb.isChecked() else "0",
                "auto_steam_wrapper": "1" if self.auto_wrapper_cb.isChecked() else "0",
                "theme": str(self.theme_combo.currentData() or DEFAULT_THEME),
                "language": str(self.language_combo.currentData() or DEFAULT_LANGUAGE),
                "console_monitor": str(self.console_monitor_combo.currentData() or "0"),
                "steam_path": self.steam_edit.text().strip(),
            }
        )
        self.status_label.setText(tr("Zapisano."))
        QTimer.singleShot(2200, lambda: self.status_label.setText(""))
        self.toast.emit(tr("Ustawienia globalne zapisane."))
        self.settings_changed.emit()

    def _theme_selected(self) -> None:
        key = str(self.theme_combo.currentData() or DEFAULT_THEME)
        self.db.set_setting("theme", key)
        self.theme_changed.emit(key)
        self.toast.emit(tr("Motyw: {name}", name=THEMES.get(key, get_theme()).name))

    def _language_selected(self) -> None:
        code = str(self.language_combo.currentData() or DEFAULT_LANGUAGE)
        if code == get_language():
            return
        self.db.set_setting("language", code)
        self.language_changed.emit(code)

    def _refresh_console_monitors(self) -> None:
        selected = self.db.get_setting("console_monitor", "0")
        self.console_monitor_combo.blockSignals(True)
        self.console_monitor_combo.clear()
        screens = QGuiApplication.screens()
        if not screens:
            self.console_monitor_combo.addItem(tr("Monitor główny"), "0")
        else:
            for index, screen in enumerate(screens):
                geometry = screen.geometry()
                self.console_monitor_combo.addItem(
                    tr(
                        "Monitor {number} — {width}x{height}",
                        number=index + 1,
                        width=geometry.width(),
                        height=geometry.height(),
                    ),
                    str(index),
                )
        idx = self.console_monitor_combo.findData(selected)
        self.console_monitor_combo.setCurrentIndex(max(0, idx))
        self.console_monitor_combo.blockSignals(False)

    def _browse_steam(self) -> None:
        initial = self.steam_edit.text().strip() or str(Path.home())
        folder = QFileDialog.getExistingDirectory(self, tr("Katalog Steam"), initial)
        if folder:
            self.steam_edit.setText(folder)

    def _refresh_wrapper_status(self) -> None:
        path = steam_wrapper_path()
        if path.is_file():
            self.wrapper_status.setText(f"Wrapper: {path}")
        else:
            self.wrapper_status.setText(
                tr("Wrapper nie jest jeszcze zainstalowany. Instalacja jest lokalna; "
                "automatyczny wpis LaunchOptions wymaga zamknięcia Steama.")
)

    def _install_wrapper(self) -> None:
        try:
            path = ensure_steam_wrapper()
        except OSError as exc:
            QMessageBox.warning(self, tr("Steam wrapper"), str(exc))
            return
        self.db.set_setting("steam_wrapper", str(path))
        self._refresh_wrapper_status()
        QApplication.clipboard().setText(steam_launch_option(path))
        self.toast.emit(tr("Wrapper Steam zainstalowany; opcja skopiowana do schowka."))
        self.status_label.setText(tr("Wrapper gotowy. Wklej opcję w Steam."))

    def _copy_wrapper_option(self) -> None:
        try:
            path = ensure_steam_wrapper()
        except OSError as exc:
            QMessageBox.warning(self, tr("Steam wrapper"), str(exc))
            return
        self.db.set_setting("steam_wrapper", str(path))
        self._refresh_wrapper_status()
        QApplication.clipboard().setText(steam_launch_option(path))
        self.toast.emit(tr("Opcja uruchamiania Steam skopiowana do schowka."))
        self.status_label.setText(tr("Skopiowano. Wklej w opcjach uruchamiania Steam."))

    def _refresh_deps(self) -> None:
        rows = []
        for tool in tool_status():
            if tool.installed:
                rows.append(
                    f"<span style='color:#42F5A7'>●</span> "
                    f"<b>{html.escape(tool.label)}</b> "
                    f"<span style='color:#69808B'>{html.escape(tool.path)}</span>"
                )
            else:
                rows.append(
                    f"<span style='color:#FFB347'>○</span> "
                    f"<b>{html.escape(tool.label)}</b> "
                    f"<span style='color:#69808B'>"
                    f"{tr('brak w PATH (pakiet: {package})', package=tool.package)}"
                    "</span>"
                )
        m32 = mangohud32_path()
        rows.append(
            f"<span style='color:{'#42F5A7' if m32 else '#FFB347'}'>●</span> "
            f"<b>MangoHud 32-bit</b> "
            f"<span style='color:#69808B'>"
            f"{html.escape(m32) if m32 else tr('brak — wymagany dla gier PE32')}"
            "</span>"
        )
        winetricks = winetricks_path()
        protontricks = protontricks_path()
        rows.append(
            f"<span style='color:{'#42F5A7' if winetricks else '#FFB347'}'>"
            f"{'●' if winetricks else '○'}</span> "
            f"<b>Winetricks</b> "
            f"<span style='color:#69808B'>"
            f"{html.escape(winetricks) if winetricks else tr('brak')}"
            "</span>"
        )
        rows.append(
            f"<span style='color:{'#42F5A7' if protontricks else '#FFB347'}'>"
            f"{'●' if protontricks else '○'}</span> "
            f"<b>Protontricks</b> "
            f"<span style='color:#69808B'>"
            f"{html.escape(protontricks) if protontricks else tr('brak (opcjonalnie dla gier Steam)')}"
            "</span>"
        )
        rows.append(
            f"<span style='color:#69808B'>"
            f"{tr('Menedżer pakietów: {manager}', manager=package_manager() or tr('nie wykryto'))}"
            "</span>"
        )
        self.deps_label.setText("<br>".join(rows))
        has_gamescope = bool(shutil.which("gamescope"))
        self.gamescope_cb.setEnabled(has_gamescope)
        self.gamescope_cb.setText(
            tr("Gamescope / skalowanie")
            if has_gamescope
            else tr("Gamescope / skalowanie (niedostępny)")
        )
        missing = missing_installable_tools()
        install_groups = dependency_install_groups()
        needs_install = bool(missing) or bool(install_groups)
        self.install_deps_button.setEnabled(needs_install)
        self.install_deps_button.setText(
            tr("ZAINSTALUJ BRAKUJĄCE") if needs_install else tr("NARZĘDZIA OK")
        )
        has_m32 = bool(mangohud32_path())
        self.install_m32_button.setText(
            tr("MANGOHUD 32-BIT: OK") if has_m32 else tr("ZAINSTALUJ MANGOHUD 32-BIT")
        )
        self.install_m32_button.setEnabled(
            not has_m32 and self._m32_process is None
        )
        self.install_winetricks_button.setText(
            tr("WINETRICKS: OK")
            if winetricks
            else tr("ZAINSTALUJ WINETRICKS")
        )
        self.install_winetricks_button.setEnabled(
            not winetricks and self._winetricks_install_worker is None
        )

    def _install_dependencies(self) -> None:
        if self._dep_process is not None:
            self.toast.emit(tr("Instalacja już trwa."))
            return
        missing = missing_installable_tools()
        groups = dependency_install_groups()
        if not missing and not groups:
            QMessageBox.information(
                self,
                tr("Zależności"),
                tr("MangoHud, GameMode (także 32-bit) i Gamescope są zainstalowane "
                "lub nie mają dostępnego pakietu. Wine nie jest instalowany "
                "automatycznie."),
            )
            return
        if not groups:
            manager = package_manager()
            packages = " ".join(
                dict.fromkeys(tool.package for tool in missing)
            )
            if manager == "pacman":
                manual = f"sudo pacman -S --needed {packages}"
            elif manager:
                manual = f"sudo {manager} install -y {packages}"
            else:
                manual = tr("Zainstaluj ręcznie: {packages}", packages=packages)
            QApplication.clipboard().setText(manual)
            QMessageBox.information(
                self,
                tr("Brak automatycznego instalatora"),
                tr(
                    "Nie wykryto pkexec albo menedżera pakietów.\n\n"
                    "Polecenie skopiowane do schowka:\n\n{command}",
                    command=manual,
                ),
            )
            return
        details = "\n".join(
            f"• {group.label}: {' '.join(group.packages)}" for group in groups
        )
        answer = QMessageBox.question(
            self,
            tr("Zainstalować zależności?"),
            tr(
                "Zostaną uruchomione polecenia menedżera pakietów z uprawnieniami "
                "administratora (pkexec):\n\n{details}\n\nKontynuować?",
                details=details,
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._dep_queue = list(groups)
        self._dep_failures = []
        self.install_deps_button.setEnabled(False)
        self._run_next_dependency()

    def _install_gamepad_udev(self) -> None:
        if self._gamepad_process is not None:
            self.toast.emit(tr("Instalacja reguły pada już trwa."))
            return
        answer = QMessageBox.question(
            self,
            tr("Obsługa pada"),
            tr("Dodać regułę udev, która przyzna aktywnemu użytkownikowi dostęp "
            "do /dev/input/js*?\n\nWymagane będzie pkexec. Po instalacji "
            "odłącz i podłącz pad ponownie."),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        script = gamepad_udev_script()
        if not script.is_file():
            QMessageBox.warning(
                self,
                tr("Obsługa pada"),
                tr("Brak instalatora:\n{path}", path=script),
            )
            return
        process = QProcess(self)
        self._gamepad_process = process
        self.deps_output.setText(tr("Instaluję regułę udev dla pada..."))
        process.setProgram("/bin/sh")
        process.setArguments([str(script)])
        process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        process.readyReadStandardOutput.connect(self._read_gamepad_output)
        process.finished.connect(self._gamepad_finished)
        process.errorOccurred.connect(self._gamepad_error)
        process.start()

    def _read_gamepad_output(self) -> None:
        process = self._gamepad_process
        if process is None:
            return
        text = bytes(process.readAllStandardOutput()).decode(
            "utf-8", errors="replace"
        )
        if text.strip():
            self.deps_output.setText((self.deps_output.text() + "\n" + text)[-1800:])

    def _gamepad_finished(self, code: int, _status: QProcess.ExitStatus) -> None:
        process = self._gamepad_process
        if process is None:
            return
        process.deleteLater()
        self._gamepad_process = None
        if code == 0:
            QMessageBox.information(
                self,
                tr("Obsługa pada"),
                tr("Reguła udev zainstalowana. Odłącz i podłącz pad ponownie."),
            )
        else:
            QMessageBox.warning(
                self,
                tr("Obsługa pada"),
                tr("Instalacja nie powiodła się. Sprawdź log w panelu zależności."),
            )

    def _gamepad_error(self, error: QProcess.ProcessError) -> None:
        if error != QProcess.ProcessError.FailedToStart:
            return
        process = self._gamepad_process
        if process is not None:
            process.deleteLater()
        self._gamepad_process = None
        QMessageBox.warning(
            self, tr("Obsługa pada"), tr("Nie udało się uruchomić instalatora udev.")
        )

    def _install_mangohud32(self) -> None:
        if self._m32_process is not None:
            self.toast.emit(tr("Instalacja MangoHud 32-bit już trwa."))
            return
        if mangohud32_path():
            QMessageBox.information(
                self,
                tr("MangoHud 32-bit"),
                tr("32-bitowy MangoHud jest już zainstalowany."),
            )
            return
        answer = QMessageBox.question(
            self,
            tr("MangoHud 32-bit"),
            tr("Zostanie pobrany oficjalny 32-bitowy build MangoHud i zainstalowany "
            "w /usr/lib/i386-linux-gnu/mangohud. Wymagane będzie pkexec oraz "
            "pakiety i386. Kontynuować?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        script = mangohud32_script()
        if not script.is_file():
            QMessageBox.warning(
                self,
                tr("MangoHud 32-bit"),
                tr("Brak skryptu instalatora:\n{path}", path=script),
            )
            return
        process = QProcess(self)
        self._m32_process = process
        self.install_m32_button.setEnabled(False)
        self.deps_output.setText(tr("Instaluję MangoHud 32-bit..."))
        process.setProgram("/bin/sh")
        process.setArguments([str(script)])
        process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        process.readyReadStandardOutput.connect(self._read_m32_output)
        process.finished.connect(self._m32_finished)
        process.errorOccurred.connect(self._m32_error)
        process.start()

    def _install_winetricks(self) -> None:
        if self._winetricks_install_worker is not None:
            return
        answer = QMessageBox.question(
            self,
            tr("Winetricks"),
            tr("Pobrać oficjalny skrypt Winetricks z GitHuba?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._winetricks_install_worker = WinetricksInstallWorker(self)
        self._winetricks_install_worker.status.connect(self.deps_output.setText)
        self._winetricks_install_worker.progress.connect(
            lambda percent: self.deps_output.setText(
                tr("Pobieram Winetricks... {percent}%", percent=percent)
            )
        )
        self._winetricks_install_worker.result.connect(
            self._winetricks_install_finished
        )
        self.install_winetricks_button.setEnabled(False)
        self._winetricks_install_worker.start()

    def _winetricks_install_finished(self, success: bool, message: str) -> None:
        worker = self._winetricks_install_worker
        self._winetricks_install_worker = None
        if worker is not None:
            worker.deleteLater()
        self._refresh_deps()
        if success:
            self.deps_output.setText(
                tr("Winetricks zainstalowany: {path}", path=message)
            )
            self.toast.emit(tr("Winetricks został zainstalowany."))
        else:
            self.deps_output.setText(message)
            QMessageBox.warning(self, tr("Winetricks"), message)

    def _read_m32_output(self) -> None:
        process = self._m32_process
        if process is None:
            return
        text = bytes(process.readAllStandardOutput()).decode(
            "utf-8", errors="replace"
        )
        if text.strip():
            current = self.deps_output.text()
            self.deps_output.setText((current + "\n" + text)[-2400:])

    def _m32_finished(self, code: int, _status: QProcess.ExitStatus) -> None:
        process = self._m32_process
        if process is None:
            return
        process.deleteLater()
        self._m32_process = None
        self._refresh_deps()
        if code == 0 and mangohud32_path():
            self.toast.emit(tr("MangoHud 32-bit zainstalowany."))
            QMessageBox.information(
                self,
                tr("MangoHud 32-bit"),
                tr(
                    "Zainstalowano:\n{path}\n\n"
                    "32-bitowe gry powinny teraz dostać overlay.",
                    path=mangohud32_path(),
                ),
            )
        else:
            QMessageBox.warning(
                self,
                tr("MangoHud 32-bit"),
                tr("Instalacja nie powiodła się. Sprawdź log w panelu zależności."),
            )

    def _m32_error(self, error: QProcess.ProcessError) -> None:
        if error != QProcess.ProcessError.FailedToStart:
            return
        process = self._m32_process
        if process is not None:
            process.deleteLater()
        self._m32_process = None
        self._refresh_deps()
        QMessageBox.warning(
            self, tr("MangoHud 32-bit"), tr("Nie udało się uruchomić instalatora.")
        )

    def _run_next_dependency(self) -> None:
        if not self._dep_queue:
            self._dep_process = None
            self._refresh_deps()
            self.install_deps_button.setEnabled(
                bool(missing_installable_tools()) or bool(dependency_install_groups())
            )
            if self._dep_failures:
                QMessageBox.warning(
                    self,
                    tr("Zależności"),
                    tr(
                        "Część instalacji nie powiodła się:\n\n{failures}\n\n"
                        "Na Ubuntu 24.04 pakiet gamescope może nie być dostępny "
                        "w repozytorium. Pozostałe narzędzia zainstalowały się "
                        "niezależnie.",
                        failures="\n".join(self._dep_failures),
                    ),
                )
            else:
                self.toast.emit(tr("Zależności zostały zainstalowane."))
            return
        group = self._dep_queue.pop(0)
        self.deps_output.setText(tr("Instaluję {name}...", name=group.label))
        process = QProcess(self)
        self._dep_process = process
        process.setProgram(group.argv[0])
        process.setArguments(list(group.argv[1:]))
        process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        process.readyReadStandardOutput.connect(self._read_dependency_output)
        process.finished.connect(
            lambda code, _status, current=group, proc=process: self._dependency_finished(
                current, int(code), proc
            )
        )
        process.errorOccurred.connect(
            lambda error, proc=process: self._dependency_error(proc, error)
        )
        process.start()

    def _read_dependency_output(self) -> None:
        process = self._dep_process
        if process is None:
            return
        text = bytes(process.readAllStandardOutput()).decode(
            "utf-8", errors="replace"
        )
        if text.strip():
            current = self.deps_output.text()
            self.deps_output.setText((current + "\n" + text)[-1800:])

    def _dependency_finished(
        self, group: DependencyGroup, code: int, process: QProcess
    ) -> None:
        if process is not self._dep_process:
            return
        process.deleteLater()
        self._dep_process = None
        if code != 0:
            self._dep_failures.append(f"{group.label}: kod {code}")
        QTimer.singleShot(0, self._run_next_dependency)

    def _dependency_error(
        self, process: QProcess, error: QProcess.ProcessError
    ) -> None:
        if process is not self._dep_process:
            return
        if error != QProcess.ProcessError.FailedToStart:
            return
        process.deleteLater()
        self._dep_process = None
        self._dep_failures.append(tr("Nie udało się uruchomić pkexec."))
        QTimer.singleShot(0, self._run_next_dependency)

    def open_log(self) -> None:
        if not LAST_RUN_LOG.is_file():
            QMessageBox.information(
                self,
                tr("Brak logu"),
                tr(
                    "Plik {path} nie istnieje.\n"
                    "Włącz opcję debugowania i uruchom grę.",
                    path=LAST_RUN_LOG,
                ),
            )
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(LAST_RUN_LOG)))

    def open_config(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(config_dir())))

    def set_busy(self, busy: bool) -> None:
        # Kept for symmetry with the library toolbar.
        self.steam_edit.setEnabled(not busy)


class RunnerPage(QWidget):
    toast = pyqtSignal(str)
    runners_changed = pyqtSignal()

    def __init__(self, database: Database, parent=None) -> None:
        super().__init__(parent)
        self.db = database
        self._worker: RunnerDownloadWorker | None = None
        self._versions_worker: RunnerReleasesWorker | None = None
        self._versions_key = ""
        self._releases: list[dict[str, Any]] = []
        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 20)
        outer.setSpacing(14)
        kicker = QLabel(tr("RUNTIME // GITHUB"))
        kicker.setObjectName("PageKicker")
        outer.addWidget(kicker)
        heading = QLabel(tr("Menedżer runnerów"))
        heading.setObjectName("PageTitle")
        outer.addWidget(heading)
        subtitle = QLabel(
            tr("Pobieranie Proton-GE i Wine-GE bez API wrapperów: urllib + json + "
            "tarfile. Każdy runner ląduje w izolowanym katalogu.")
 )
        subtitle.setObjectName("PageSubtitle")
        subtitle.setWordWrap(True)
        outer.addWidget(subtitle)

        download_panel = QFrame()
        download_panel.setObjectName("Panel")
        download_layout = QVBoxLayout(download_panel)
        download_layout.setContentsMargins(18, 16, 18, 16)
        download_layout.setSpacing(10)
        title = QLabel(tr("POBIERZ NAJNOWSZY"))
        title.setObjectName("SectionTitle")
        download_layout.addWidget(title)
        source_row = QHBoxLayout()
        self.source_combo = QComboBox()
        self.source_combo.addItem(tr("Proton-GE  //  GloriousEggroll/proton-ge-custom"), "proton_ge")
        self.source_combo.addItem(tr("Wine-GE  //  GloriousEggroll/wine-ge-custom"), "wine_ge")
        self.source_combo.currentIndexChanged.connect(self._reset_versions)
        source_row.addWidget(self.source_combo, 1)
        self.versions_button = QPushButton(tr("POKAŻ / ODŚWIEŻ WERSJE"))
        self.versions_button.setObjectName("GhostButton")
        self.versions_button.clicked.connect(self._load_releases)
        source_row.addWidget(self.versions_button)
        self.download_button = QPushButton(tr("POBIERZ WYBRANĄ"))
        self.download_button.setObjectName("PrimaryButton")
        self.download_button.clicked.connect(self._download)
        source_row.addWidget(self.download_button)
        download_layout.addLayout(source_row)
        version_row = QHBoxLayout()
        version_label = QLabel(tr("WERSJA"))
        version_label.setObjectName("Muted")
        version_row.addWidget(version_label)
        self.version_combo = QComboBox()
        self.version_combo.addItem(tr("Najnowszy (automatycznie)"), None)
        self.version_combo.setEnabled(False)
        version_row.addWidget(self.version_combo, 1)
        download_layout.addLayout(version_row)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setVisible(False)
        download_layout.addWidget(self.progress)
        self.download_status = QLabel(
            tr("Źródło: oficjalne GitHub Releases. Archiwa są weryfikowane pod kątem "
            "path traversal przed rozpakowaniem.")
        )
        self.download_status.setObjectName("Muted")
        self.download_status.setWordWrap(True)
        download_layout.addWidget(self.download_status)
        outer.addWidget(download_panel)

        installed_panel = QFrame()
        installed_panel.setObjectName("Panel")
        installed_layout = QVBoxLayout(installed_panel)
        installed_layout.setContentsMargins(18, 16, 18, 16)
        installed_layout.setSpacing(10)
        installed_head = QHBoxLayout()
        installed_title = QLabel(tr("ZAINSTALOWANE SILNIKI"))
        installed_title.setObjectName("SectionTitle")
        installed_head.addWidget(installed_title)
        installed_head.addStretch(1)
        refresh = QPushButton(tr("ODŚWIEŻ"))
        refresh.setObjectName("GhostButton")
        refresh.clicked.connect(self.refresh)
        installed_head.addWidget(refresh)
        open_dir = QPushButton(tr("OTWÓRZ KATALOG"))
        open_dir.setObjectName("GhostButton")
        open_dir.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(db.RUNNERS_DIR)))
        )
        installed_head.addWidget(open_dir)
        installed_layout.addLayout(installed_head)
        self.table = QTreeWidget()
        self.table.setHeaderLabels([tr("Silnik"), tr("Typ"), tr("Plik wine")])
        self.table.setRootIsDecorated(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setMinimumHeight(250)
        self.table.header().setStretchLastSection(True)
        self.table.setColumnWidth(0, 300)
        self.table.setColumnWidth(1, 90)
        self.table.doubleClicked.connect(lambda _index: self._open_selected())
        installed_layout.addWidget(self.table, 1)
        actions = QHBoxLayout()
        self.delete_button = QPushButton(tr("USUŃ WYBRANY"))
        self.delete_button.setObjectName("DangerButton")
        self.delete_button.clicked.connect(self._delete_selected)
        actions.addWidget(self.delete_button)
        actions.addStretch(1)
        self.location_label = QLabel(tr("Lokalizacja: {path}", path=db.RUNNERS_DIR))
        self.location_label.setObjectName("Muted")
        actions.addWidget(self.location_label)
        installed_layout.addLayout(actions)
        outer.addWidget(installed_panel, 1)

        default_panel = QFrame()
        default_panel.setObjectName("Panel")
        default_layout = QHBoxLayout(default_panel)
        default_layout.setContentsMargins(18, 14, 18, 14)
        default_label = QLabel(tr("DOMYŚLNY RUNNER DLA NOWYCH GIER"))
        default_label.setObjectName("SectionTitle")
        default_layout.addWidget(default_label)
        self.default_combo = QComboBox()
        default_layout.addWidget(self.default_combo, 1)
        use_button = QPushButton(tr("USTAW JAKO DOMYŚLNY"))
        use_button.setObjectName("GhostButton")
        use_button.clicked.connect(self._set_default)
        default_layout.addWidget(use_button)
        outer.addWidget(default_panel)
        self.refresh()

    def _refresh_combo(self) -> None:
        selected = self.db.get_setting("default_runner")
        self.default_combo.blockSignals(True)
        self.default_combo.clear()
        self.default_combo.addItem(tr("Automatycznie (pierwszy dostępny)"), "")
        for runner in discover_runners():
            self.default_combo.addItem(runner.label, runner.path)
        index = self.default_combo.findData(selected)
        if index < 0 and selected:
            self.default_combo.addItem(tr("Własny: {name}", name=selected), selected)
            index = self.default_combo.count() - 1
        self.default_combo.setCurrentIndex(max(0, index))
        self.default_combo.blockSignals(False)

    def refresh(self) -> None:
        self.table.clear()
        for runner in discover_runners():
            item = QTreeWidgetItem([runner.version, runner.kind.upper(), runner.path])
            item.setData(2, Qt.ItemDataRole.UserRole, runner.path)
            item.setData(1, Qt.ItemDataRole.UserRole, runner.kind)
            self.table.addTopLevelItem(item)
        self._refresh_combo()
        self.runners_changed.emit()

    def _reset_versions(self) -> None:
        self._versions_key = str(self.source_combo.currentData() or "proton_ge")
        self._releases = []
        self.version_combo.blockSignals(True)
        self.version_combo.clear()
        self.version_combo.addItem(tr("Najnowszy (automatycznie)"), None)
        self.version_combo.setEnabled(False)
        self.version_combo.blockSignals(False)

    def _load_releases(self) -> None:
        if self._versions_worker is not None:
            return
        key = str(self.source_combo.currentData() or "proton_ge")
        self._versions_key = key
        self.versions_button.setEnabled(False)
        self.download_status.setText(tr("Pobieram listę wersji z GitHub Releases..."))
        worker = RunnerReleasesWorker(key, force=True, parent=self)
        self._versions_worker = worker
        worker.result.connect(self._releases_result)
        worker.finished.connect(self._versions_finished)
        worker.start()

    def _releases_result(self, payload: object) -> None:
        data = payload if isinstance(payload, dict) else {}
        if not data.get("ok"):
            self.download_status.setText(
                tr(
                    "Nie udało się pobrać listy wersji: {error}",
                    error=data.get("error", tr("nieznany błąd")),
                )
            )
            return
        if self._versions_key != str(self.source_combo.currentData() or "proton_ge"):
            return
        releases = data.get("releases") or []
        self._releases = [item for item in releases if isinstance(item, dict)]
        self.version_combo.blockSignals(True)
        self.version_combo.clear()
        self.version_combo.addItem(tr("Najnowszy (automatycznie)"), None)
        for release in self._releases:
            tag = str(release.get("tag_name", "?"))
            date = str(release.get("published_at", ""))[:10]
            asset = choose_runner_asset(release.get("assets") or [])
            size = ""
            if asset:
                try:
                    size = human_bytes(int(asset.get("size", 0)))
                except (TypeError, ValueError):
                    size = ""
            badge = "  [BETA]" if release.get("prerelease") else ""
            label = f"{tag}{badge}"
            if date:
                label += f"  •  {date}"
            if size:
                label += f"  •  {size}"
            self.version_combo.addItem(label, release)
        self.version_combo.setCurrentIndex(0)
        self.version_combo.setEnabled(bool(self._releases))
        self.version_combo.blockSignals(False)
        self.download_status.setText(
            tr(
                "Znaleziono {count} wersji. Wybierz wersję i pobierz.",
                count=len(self._releases),
            )
        )

    def _versions_finished(self) -> None:
        worker = self._versions_worker
        self._versions_worker = None
        self.versions_button.setEnabled(True)
        if worker is not None:
            worker.deleteLater()

    def _download(self) -> None:
        if self._worker is not None:
            return
        key = str(self.source_combo.currentData() or "proton_ge")
        release = self.version_combo.currentData()
        self.download_button.setEnabled(False)
        self.source_combo.setEnabled(False)
        self.versions_button.setEnabled(False)
        self.version_combo.setEnabled(False)
        self.progress.setValue(0)
        self.progress.setVisible(True)
        worker = RunnerDownloadWorker(
            key,
            release if isinstance(release, dict) else None,
            self,
        )
        self._worker = worker
        worker.status.connect(self.download_status.setText)
        worker.progress.connect(self.progress.setValue)
        worker.result.connect(self._download_finished)
        worker.finished.connect(self._worker_finished)
        worker.start()

    def _download_finished(self, success: bool, message: str) -> None:
        self.download_status.setText(message)
        self.toast.emit(message)
        if success:
            self.progress.setValue(100)
            self.refresh()
        else:
            QMessageBox.warning(self, tr("Runner"), message)

    def _worker_finished(self) -> None:
        self.download_button.setEnabled(True)
        self.source_combo.setEnabled(True)
        self.versions_button.setEnabled(True)
        self.version_combo.setEnabled(bool(self._releases))
        self.progress.setVisible(False)
        worker = self._worker
        self._worker = None
        if worker is not None:
            worker.deleteLater()

    def _selected_path(self) -> str:
        item = self.table.currentItem()
        return str(item.data(2, Qt.ItemDataRole.UserRole)) if item else ""

    def _open_selected(self) -> None:
        path = self._selected_path()
        if path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).parent)))

    def _delete_selected(self) -> None:
        path = self._selected_path()
        if not path:
            return
        try:
            relative = Path(path).resolve().relative_to(db.RUNNERS_DIR.resolve())
        except ValueError:
            QMessageBox.warning(self, tr("Runner"), tr("Systemowego runnera nie można usunąć."))
            return
        root = db.RUNNERS_DIR / relative.parts[0]
        answer = QMessageBox.question(
            self,
            tr("Usuń runner"),
            tr(
                "Usunąć katalog\n{path}\n\nTej operacji nie można cofnąć.",
                path=root,
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            shutil.rmtree(root)
        except OSError as exc:
            QMessageBox.warning(self, tr("Runner"), tr("Nie udało się usunąć: {error}", error=exc))
            return
        self.toast.emit(tr("Usunięto runner {name}.", name=root.name))
        self.refresh()

    def _set_default(self) -> None:
        path = str(self.default_combo.currentData() or "")
        self.db.set_setting("default_runner", path)
        self.toast.emit(tr("Domyślny runner zaktualizowany."))
        self.runners_changed.emit()


class MangoPage(QWidget):
    toast = pyqtSignal(str)

    def __init__(self, database: Database, parent=None) -> None:
        super().__init__(parent)
        self.db = database
        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 20)
        outer.setSpacing(12)
        kicker = QLabel(tr("OVERLAY // MANGOHUD"))
        kicker.setObjectName("PageKicker")
        outer.addWidget(kicker)
        heading = QLabel(tr("Kreator nakładki"))
        heading.setObjectName("PageTitle")
        outer.addWidget(heading)
        subtitle = QLabel(
            tr("Wizualny edytor modułów, pozycji i kolorów. Wartości są zapisywane "
            "w tabeli settings, a MANGOHUD_CONFIG jest budowany przy każdym starcie "
            "z aktualnym profilem skalowania gry."))

        subtitle.setObjectName("PageSubtitle")
        subtitle.setWordWrap(True)
        outer.addWidget(subtitle)

        columns = QHBoxLayout()
        columns.setSpacing(14)
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        style_scroll_area(left_scroll)
        left_scroll.setMinimumWidth(330)
        left_scroll.setMaximumWidth(405)
        left_host = QWidget()
        left = QVBoxLayout(left_host)
        left.setContentsMargins(0, 0, 8, 0)
        left.setSpacing(12)

        modules_panel, modules_layout = self._panel(tr("MODUŁY"), tr("Wybierz elementy HUD."))
        self.module_checks: dict[str, QCheckBox] = {}
        for key, label in (
            ("show_fps", tr("FPS i frame time")),
            ("show_cpu", tr("CPU load / clock")),
            ("show_gpu", tr("GPU load / clock")),
            ("show_ram", tr("RAM")),
            ("show_vram", tr("VRAM")),
            ("show_temps", tr("Temperatury CPU/GPU")),
            ("show_frametime", tr("Wykres Frame Timing")),
        ):
            checkbox = QCheckBox(label)
            self.module_checks[key] = checkbox
            modules_layout.addWidget(checkbox)
        left.addWidget(modules_panel)

        layout_panel, layout_layout = self._panel(tr("POZYCJA"), tr("Zakotwiczenie panelu na ekranie."))
        self.position_combo = QComboBox()
        for label, value in (
            (tr("Lewy górny"), "top-left"),
            (tr("Górny środek"), "top-center"),
            (tr("Prawy górny"), "top-right"),
            (tr("Lewy środek"), "middle-left"),
            (tr("Środek"), "middle-center"),
            (tr("Prawy środek"), "middle-right"),
            (tr("Lewy dolny"), "bottom-left"),
            (tr("Dolny środek"), "bottom-center"),
            (tr("Prawy dolny"), "bottom-right"),
        ):
            self.position_combo.addItem(label, value)
        layout_layout.addWidget(self.position_combo)
        self.font_spin = QSpinBox()
        self.font_spin.setRange(10, 48)
        self.font_spin.setSuffix(" px")
        layout_layout.addWidget(self._labeled_row(tr("Rozmiar fontu"), self.font_spin))
        self.alpha_spin = QDoubleSpinBox()
        self.alpha_spin.setRange(0.0, 1.0)
        self.alpha_spin.setSingleStep(0.05)
        self.alpha_spin.setDecimals(2)
        layout_layout.addWidget(self._labeled_row(tr("Tło (alpha)"), self.alpha_spin))
        self.corners_spin = QSpinBox()
        self.corners_spin.setRange(0, 30)
        self.corners_spin.setSuffix(" px")
        layout_layout.addWidget(self._labeled_row(tr("Zaokrąglenie"), self.corners_spin))
        left.addWidget(layout_panel)

        colors_panel, colors_layout = self._panel(tr("KOLORY"), tr("Akcent i paleta HUD."))
        self.accent_button = ColorButton("#00E5FF", tr("Akcent"))
        self.text_button = ColorButton("#E6FAFF", tr("Tekst"))
        self.gpu_button = ColorButton("#42F5A7", tr("GPU"))
        self.cpu_button = ColorButton("#00B8FF", tr("CPU"))
        colors_grid = QGridLayout()
        colors_grid.setSpacing(8)
        colors_grid.addWidget(QLabel(tr("Akcent")), 0, 0)
        colors_grid.addWidget(self.accent_button, 0, 1)
        colors_grid.addWidget(QLabel(tr("Tekst")), 0, 2)
        colors_grid.addWidget(self.text_button, 0, 3)
        colors_grid.addWidget(QLabel(tr("GPU")), 1, 0)
        colors_grid.addWidget(self.gpu_button, 1, 1)
        colors_grid.addWidget(QLabel(tr("CPU")), 1, 2)
        colors_grid.addWidget(self.cpu_button, 1, 3)
        colors_layout.addLayout(colors_grid)
        left.addWidget(colors_panel)

        save_row = QHBoxLayout()
        reset = QPushButton(tr("RESET"))
        reset.setObjectName("GhostButton")
        reset.clicked.connect(self.reset)
        save_row.addWidget(reset)
        save = QPushButton(tr("ZAPISZ NAKŁADKĘ"))
        save.setObjectName("PrimaryButton")
        save.clicked.connect(self.save)
        save_row.addWidget(save, 1)
        left.addLayout(save_row)
        left.addStretch(1)
        left_scroll.setWidget(left_host)
        columns.addWidget(left_scroll)

        right_panel, right = self._panel(
            tr("PODGLĄD NA ŻYWO"),
            tr("Przybliżony render; końcowy HUD rysuje MangoHud."),
        )
        self.preview = OverlayPreview()
        self.preview.setMinimumHeight(300)
        right.addWidget(self.preview, 1)
        scaling_note = QLabel(
            tr("custom_text: w runtime zawsze zawiera profil skalowania wybranej gry.")
        )
        scaling_note.setObjectName("Muted")
        right.addWidget(scaling_note)
        config_title = QLabel(tr("MANGOHUD_CONFIG"))
        config_title.setObjectName("Accent")
        config_title.setStyleSheet(
            "font-family:'DejaVu Sans Mono'; font-size:8pt; font-weight:700;"
        )
        right.addWidget(config_title)
        self.config_preview = QPlainTextEdit()
        self.config_preview.setReadOnly(True)
        self.config_preview.setMaximumHeight(120)
        right.addWidget(self.config_preview)
        columns.addWidget(right_panel, 1)
        outer.addLayout(columns, 1)

        self._wire_preview()
        self.apply_profile(self.db.get_mangohud())

    def _panel(self, title: str, subtitle: str = "") -> tuple[QFrame, QVBoxLayout]:
        frame = QFrame()
        frame.setObjectName("Panel")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)
        title_label = QLabel(title)
        title_label.setObjectName("SectionTitle")
        layout.addWidget(title_label)
        if subtitle:
            sub = QLabel(subtitle)
            sub.setObjectName("Muted")
            sub.setWordWrap(True)
            layout.addWidget(sub)
        return frame, layout

    def _labeled_row(self, label: str, widget: QWidget) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        text = QLabel(label)
        text.setObjectName("Muted")
        text.setMinimumWidth(100)
        layout.addWidget(text)
        layout.addWidget(widget, 1)
        return row

    def _wire_preview(self) -> None:
        for checkbox in self.module_checks.values():
            checkbox.toggled.connect(self._update_preview)
        for widget in (
            self.position_combo,
            self.font_spin,
            self.alpha_spin,
            self.corners_spin,
        ):
            widget.currentIndexChanged.connect(self._update_preview) if isinstance(
                widget, QComboBox
            ) else widget.valueChanged.connect(self._update_preview)
        for button in (
            self.accent_button,
            self.text_button,
            self.gpu_button,
            self.cpu_button,
        ):
            button.color_changed.connect(self._update_preview)
        self.preview.position_selected.connect(self._preview_position)

    def _preview_position(self, position: str) -> None:
        index = self.position_combo.findData(position)
        if index >= 0:
            self.position_combo.setCurrentIndex(index)

    def profile_from_ui(self) -> dict[str, Any]:
        profile = dict(db.DEFAULT_MANGOHUD)
        for key, checkbox in self.module_checks.items():
            profile[key] = checkbox.isChecked()
        profile.update(
            {
                "position": str(self.position_combo.currentData() or "top-left"),
                "font_size": int(self.font_spin.value()),
                "background_alpha": float(self.alpha_spin.value()),
                "round_corners": int(self.corners_spin.value()),
                "accent": self.accent_button.color(),
                "text_color": self.text_button.color(),
                "gpu_color": self.gpu_button.color(),
                "cpu_color": self.cpu_button.color(),
            }
        )
        return profile

    def apply_profile(self, profile: dict[str, Any]) -> None:
        for key, checkbox in self.module_checks.items():
            checkbox.blockSignals(True)
            checkbox.setChecked(bool(profile.get(key, True)))
            checkbox.blockSignals(False)
        position = str(profile.get("position", "top-left"))
        index = self.position_combo.findData(position)
        self.position_combo.blockSignals(True)
        self.position_combo.setCurrentIndex(max(0, index))
        self.position_combo.blockSignals(False)
        self.font_spin.blockSignals(True)
        self.font_spin.setValue(int(profile.get("font_size", 18)))
        self.font_spin.blockSignals(False)
        self.alpha_spin.blockSignals(True)
        self.alpha_spin.setValue(float(profile.get("background_alpha", 0.35)))
        self.alpha_spin.blockSignals(False)
        self.corners_spin.blockSignals(True)
        self.corners_spin.setValue(int(profile.get("round_corners", 8)))
        self.corners_spin.blockSignals(False)
        self.accent_button.set_color(str(profile.get("accent", "#00E5FF")))
        self.text_button.set_color(str(profile.get("text_color", "#E6FAFF")))
        self.gpu_button.set_color(str(profile.get("gpu_color", "#42F5A7")))
        self.cpu_button.set_color(str(profile.get("cpu_color", "#00B8FF")))
        self._update_preview()

    def _update_preview(self) -> None:
        profile = self.profile_from_ui()
        self.preview.set_profile(profile, "fsr_1080_1440")
        self.config_preview.setPlainText(mangohud_config(profile, "fsr_1080_1440", 60))

    def save(self) -> None:
        self.db.save_mangohud(self.profile_from_ui())
        self.toast.emit(tr("Profil MangoHud zapisany."))
        self._update_preview()

    def reset(self) -> None:
        self.apply_profile(dict(db.DEFAULT_MANGOHUD))
        self.toast.emit(tr("Przywrócono domyślny profil nakładki."))


class LibraryPage(QWidget):
    launch_requested = pyqtSignal(int)
    edit_requested = pyqtSignal(int)
    delete_requested = pyqtSignal(int)
    context_requested = pyqtSignal(int, object)
    add_requested = pyqtSignal()
    sync_requested = pyqtSignal()
    big_picture_requested = pyqtSignal()
    toast = pyqtSignal(str)

    VIEWS = {"grid": 0, "compact": 1, "minimal": 2}

    def __init__(self, database: Database, parent=None) -> None:
        super().__init__(parent)
        self.db = database
        self._games: list[dict[str, Any]] = []
        self._cover_cache: dict[str, QPixmap | None] = {}
        self._dirty_views: set[str] = set()
        self._view_mode = self.db.get_setting("library_view", "grid")
        if self._view_mode not in self.VIEWS:
            self._view_mode = "grid"
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(220)
        self._search_timer.timeout.connect(self.reload)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 20)
        outer.setSpacing(14)
        header = QHBoxLayout()
        heading_box = QVBoxLayout()
        heading_box.setSpacing(2)
        kicker = QLabel(tr("LIBRARY // LOCAL"))
        kicker.setObjectName("PageKicker")
        heading_box.addWidget(kicker)
        heading = QLabel(tr("Biblioteka"))
        heading.setObjectName("PageTitle")
        heading_box.addWidget(heading)
        header.addLayout(heading_box)
        header.addStretch(1)
        self.stats_label = QLabel(tr("0 GIER // 0 STEAM"))
        self.stats_label.setObjectName("StatsPill")
        header.addWidget(self.stats_label)
        add = QPushButton(tr("＋  DODAJ GRĘ"))
        add.setObjectName("PrimaryButton")
        add.clicked.connect(self.add_requested.emit)
        header.addWidget(add)
        outer.addLayout(header)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(7)
        self.search_edit = QLineEdit()
        self.search_edit.setObjectName("Search")
        self.search_edit.setPlaceholderText(tr("Szukaj gry...  (Ctrl+F)"))
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(lambda _text: self._search_timer.start())
        toolbar.addWidget(self.search_edit, 1)
        self.sync_button = QPushButton(tr("↻  SYNCHRONIZUJ STEAM"))
        self.sync_button.setObjectName("GhostButton")
        self.sync_button.clicked.connect(self.sync_requested.emit)
        toolbar.addWidget(self.sync_button)
        self.view_group = QButtonGroup(self)
        self.view_group.setExclusive(True)
        self.view_buttons: dict[str, QPushButton] = {}
        for mode, label in (
            ("grid", tr("SIATKA")),
            ("compact", tr("KOMPAKT")),
            ("minimal", tr("MINIMAL")),
        ):
            button = QPushButton(label)
            button.setObjectName("ViewButton")
            button.setCheckable(True)
            button.setProperty("view", mode)
            button.clicked.connect(partial(self.set_view, mode))
            self.view_group.addButton(button)
            self.view_buttons[mode] = button
            toolbar.addWidget(button)
            if mode == self._view_mode:
                button.setChecked(True)
        self.console_button = QPushButton(tr("BIG PICTURE"))
        self.console_button.setObjectName("ViewButton")
        self.console_button.setCheckable(True)
        self.console_button.setToolTip(tr("Pełnoekranowy tryb konsolowy z obsługą pada"))
        self.console_button.clicked.connect(self.big_picture_requested.emit)
        self.view_group.addButton(self.console_button)
        toolbar.addWidget(self.console_button)
        outer.addLayout(toolbar)

        self.stack = QStackedWidget()
        self.grid_footer = QLabel("")
        self.compact_footer = QLabel("")
        self.grid_layout: FlowLayout
        self.compact_layout: QVBoxLayout
        self.grid_scroll, self.grid_layout = self._make_grid_view()
        self.compact_scroll, self.compact_layout = self._make_compact_view()
        self.minimal_tree = QTreeWidget()
        self.minimal_tree.setHeaderLabels([tr("GRA"), tr("ŹRÓDŁO"), tr("SKALOWANIE"), tr("FPS"), tr("RUNNER")])
        self.minimal_tree.setRootIsDecorated(False)
        self.minimal_tree.setAlternatingRowColors(True)
        self.minimal_tree.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.minimal_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.minimal_tree.customContextMenuRequested.connect(self._minimal_context)
        self.minimal_tree.itemDoubleClicked.connect(self._minimal_launch)
        self.minimal_tree.setColumnWidth(0, 330)
        self.minimal_tree.setColumnWidth(1, 150)
        self.minimal_tree.setColumnWidth(2, 210)
        self.minimal_tree.setColumnWidth(3, 70)
        self.minimal_tree.header().setStretchLastSection(True)
        self.stack.addWidget(self.grid_scroll)
        self.stack.addWidget(self.compact_scroll)
        self.stack.addWidget(self.minimal_tree)
        self.stack.setCurrentIndex(self.VIEWS[self._view_mode])
        outer.addWidget(self.stack, 1)
        self.reload()

    def _make_grid_view(self) -> tuple[QScrollArea, FlowLayout]:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        style_scroll_area(scroll)
        host = QWidget()
        layout = FlowLayout(host, margin=2, h_spacing=16, v_spacing=16)
        host.setLayout(layout)
        scroll.setWidget(host)
        return scroll, layout

    def _make_compact_view(self) -> tuple[QScrollArea, QVBoxLayout]:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        style_scroll_area(scroll)
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(2, 2, 8, 8)
        layout.setSpacing(8)
        host.setLayout(layout)
        scroll.setWidget(host)
        return scroll, layout

    def set_view(self, mode: str) -> None:
        if mode not in self.VIEWS:
            return
        self._view_mode = mode
        self.db.set_setting("library_view", mode)
        button = self.view_buttons.get(mode)
        if button is not None:
            button.setChecked(True)
        self.console_button.setChecked(False)
        self.stack.setCurrentIndex(self.VIEWS[mode])
        if mode in self._dirty_views:
            self._rebuild_view(mode)
            self._dirty_views.discard(mode)
        if mode == "minimal":
            self.toast.emit(tr("Widok minimalny: gry uruchomisz też z menu traya."))

    def set_console_active(self, active: bool) -> None:
        if active:
            self.console_button.setChecked(True)
        else:
            self.console_button.setChecked(False)
            button = self.view_buttons.get(self._view_mode)
            if button is not None:
                button.setChecked(True)

    def focus_search(self) -> None:
        self.search_edit.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.search_edit.selectAll()

    def _cover_for(self, game: dict[str, Any]) -> QPixmap | None:
        path_text = str(game.get("cover_path", "") or "")
        if not path_text:
            return None
        path = Path(path_text).expanduser()
        try:
            stat = path.stat()
        except OSError:
            return None
        key = f"{path}:{stat.st_mtime_ns}:{stat.st_size}"
        if key not in self._cover_cache:
            pixmap = QPixmap(str(path))
            self._cover_cache[key] = None if pixmap.isNull() else pixmap
        return self._cover_cache[key]

    def reload(self) -> None:
        search = self.search_edit.text().strip()
        self._games = self.db.list_games(search)
        for game in self._games:
            game["_bits"] = exe_bits(str(game.get("exe_path", "")))
        stats = self.db.stats()
        self.stats_label.setText(tr("{games} GIER // {steam} STEAM", games=stats["games"], steam=stats["steam"]))
        self._dirty_views = set(self.VIEWS)
        self._rebuild_view(self._view_mode)
        self._dirty_views.discard(self._view_mode)

    def free_resources(self) -> None:
        """Drop cover pixmaps and card widgets while the game is running."""
        self.grid_layout.clear()
        self._clear_layout(self.compact_layout)
        self.minimal_tree.clear()
        self._cover_cache.clear()
        self._dirty_views = set(self.VIEWS)

    def _clear_layout(self, layout: QVBoxLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            if item is None:
                continue
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()

    def _empty_widget(self, text: str) -> QWidget:
        frame = QFrame()
        frame.setObjectName("Panel")
        frame.setMinimumHeight(180)
        frame.setMinimumWidth(420)
        layout = QVBoxLayout(frame)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title = QLabel(text)
        title.setObjectName("SectionTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        hint = QLabel(tr("Użyj „DODAJ GRĘ” lub zsynchronizuj bibliotekę Steam."))
        hint.setObjectName("Muted")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(hint)
        return frame

    def _rebuild_view(self, mode: str) -> None:
        if mode == "grid":
            self.grid_layout.clear()
            if not self._games:
                self.grid_layout.addWidget(self._empty_widget(tr("Biblioteka jest pusta")))
                return
            for game in self._games:
                card = GameCard(game, self._cover_for(game))
                card.launch_requested.connect(self.launch_requested.emit)
                card.edit_requested.connect(self.edit_requested.emit)
                card.delete_requested.connect(self.delete_requested.emit)
                card.context_requested.connect(self.context_requested.emit)
                self.grid_layout.addWidget(card)
        elif mode == "compact":
            self._clear_layout(self.compact_layout)
            if not self._games:
                self.compact_layout.addWidget(self._empty_widget(tr("Biblioteka jest pusta")))
                self.compact_layout.addStretch(1)
                return
            for game in self._games:
                row = CompactGameRow(game, self._cover_for(game))
                row.launch_requested.connect(self.launch_requested.emit)
                row.edit_requested.connect(self.edit_requested.emit)
                row.delete_requested.connect(self.delete_requested.emit)
                row.context_requested.connect(self.context_requested.emit)
                self.compact_layout.addWidget(row)
            self.compact_layout.addStretch(1)
        else:
            self.minimal_tree.clear()
            if not self._games:
                item = QTreeWidgetItem([tr("Brak gier."), "", "", "", ""])
                item.setFlags(Qt.ItemFlag.NoItemFlags)
                self.minimal_tree.addTopLevelItem(item)
                return
            for game in self._games:
                source = (
                    f"STEAM {game.get('steam_appid', '')}"
                    if game.get("is_steam")
                    else "STANDALONE"
                )
                if game.get("_bits"):
                    source += f" / {game['_bits']}-BIT"
                runner = Path(str(game.get("runner_path", ""))).name or "AUTO"
                item = QTreeWidgetItem(
                    [
                        str(game.get("name", "")),
                        source,
                        scaling_label(str(game.get("scaling_mode", "native"))),
                        str(int(game.get("fps_limit", 0)) or "∞"),
                        runner,
                    ]
                )
                item.setData(0, Qt.ItemDataRole.UserRole, int(game["id"]))
                item.setToolTip(0, str(game.get("exe_path", "")))
                self.minimal_tree.addTopLevelItem(item)

    def _minimal_launch(self, item: QTreeWidgetItem, _column: int = 0) -> None:
        game_id = item.data(0, Qt.ItemDataRole.UserRole)
        if game_id is not None:
            self.launch_requested.emit(int(game_id))

    def _minimal_context(self, position: QPoint) -> None:
        item = self.minimal_tree.itemAt(position)
        if not item:
            return
        game_id = item.data(0, Qt.ItemDataRole.UserRole)
        if game_id is not None:
            self.context_requested.emit(
                int(game_id), self.minimal_tree.viewport().mapToGlobal(position)
            )

    def set_sync_busy(self, busy: bool) -> None:
        self.sync_button.setEnabled(not busy)
        self.search_edit.setEnabled(not busy)
def write_runtime_file(
    database: Database,
    game: dict[str, Any],
    command: list[str] | None = None,
    *,
    direct: bool = False,
    use_prefix: bool = True,
) -> Path:
    """Build the shell-quoted runtime file consumed by launcher.sh.

    ``direct`` is used by the Steam wrapper: Steam has already constructed the
    wine/proton command, so launcher.sh must not prepend another Wine binary.
    """
    if direct and not command:
        raise RuntimeError(tr("Brak komendy przekazanej przez Steam."))

    exe = Path(str(game.get("exe_path", ""))).expanduser()
    prefix: Path | None = None
    runner = None
    proton = None
    if not direct:
        if not exe.is_file():
            raise RuntimeError(tr("Plik EXE nie istnieje:\n{path}", path=exe))
        try:
            exe = exe.resolve()
        except OSError:
            pass
        runner = resolve_runner(
            str(game.get("runner_path", "")),
            str(database.get_setting("default_runner", "")),
        )
        if runner is None:
            raise RuntimeError(
                tr("Brak runnera Wine. Zainstaluj Wine albo pobierz Proton-GE/Wine-GE "
                "w Menedżerze runnerów.")
 )
        if not os.access(runner.path, os.X_OK):
            raise RuntimeError(tr("Runner nie jest wykonywalny:\n{path}", path=runner.path))
        if runner.kind == "proton":
            proton = find_proton_script(runner.path)
        if use_prefix:
            prefix_text = str(game.get("wine_prefix", "")).strip()
            if not prefix_text:
                prefix_text = db.make_prefix(str(game.get("name", "game")))
            prefix = Path(prefix_text).expanduser()
            prefix.mkdir(parents=True, exist_ok=True)
            try:
                prefix = prefix.resolve()
            except OSError:
                pass

    env = parse_env_vars(str(game.get("env_vars", "")))
    if direct:
        if game.get("steam_appid"):
            env.setdefault("SteamAppId", str(game["steam_appid"]))
            env.setdefault("SteamGameId", str(game["steam_appid"]))
        env.pop("WINEPREFIX", None)
    elif prefix:
        if runner is not None and runner.kind == "proton":
            # Proton derives WINEPREFIX from STEAM_COMPAT_DATA_PATH.  Leave it
            # unset so the Proton script can create/use <prefix>/pfx.
            env.pop("WINEPREFIX", None)
        else:
            env["WINEPREFIX"] = str(prefix)

    scaling = str(game.get("scaling_mode", "native"))
    profile = SCALING_PROFILES.get(scaling, SCALING_PROFILES["native"])
    if profile.get("kind") == "proton":
        env.setdefault("WINE_FULLSCREEN_FSR", "1")
        env.setdefault(
            "WINE_FULLSCREEN_FSR_STRENGTH", str(profile.get("fsr_strength", 2))
        )

    fps_limit = int(game.get("fps_limit", 0) or 0)
    if fps_limit > 0:
        env.setdefault("DXVK_FRAME_RATE", str(fps_limit))

    mangohud_enabled = database.get_bool("mangohud", True)
    hud = mangohud_config(database.get_mangohud(), scaling, fps_limit)
    crt_path = ""
    if scaling == "crt":
        settings_shader = database.get_setting("crt_shader").strip()
        if settings_shader and Path(settings_shader).is_file():
            crt_path = settings_shader
        else:
            crt_path = str(ensure_crt_shader())

    try:
        launch_args = shlex.split(str(game.get("launch_args", "")), posix=True)
    except ValueError as exc:
        raise RuntimeError(tr("Nieprawidłowe argumenty uruchamiania: {error}", error=exc)) from exc

    if direct:
        full_command = list(command or []) + launch_args
        workdir = ""
    else:
        full_command = [str(exe)] + launch_args
        workdir = str(exe.parent)

    game_bits = exe_bits(str(game.get("exe_path", "")))
    if game_bits is None and command:
        game_bits = exe_bits(str(command[0]))
    mangohud_lib = mangohud_library_path(game_bits)

    lines = [
        "#!/bin/sh",
        f"# Generated by Boostlayer for game {game['id']}; do not edit.",
        f"# Mode: {'steam-direct' if direct else 'wine/proton'}",
    ]
    for key, value in sorted(env.items(), key=lambda item: item[0].lower()):
        lines.append(f"export {key}={shlex.quote(str(value))}")
    runtime_values = {
        "BL_DEBUG": "1" if database.get_bool("debug_logging", False) else "0",
        "BL_GAMEMODE": "1" if database.get_bool("gamemode", True) else "0",
        "BL_MANGOHUD": "1" if mangohud_enabled else "0",
        "BL_GAMESCOPE": "1" if database.get_bool("gamescope", True) else "0",
        "BL_MANGOHUD_CONFIG": hud if mangohud_enabled else "",
        "BL_MANGOHUD_LIB": mangohud_lib if mangohud_enabled else "",
        "BL_MANGOHUD_BITS": str(game_bits or ""),
        "BL_SCALING": scaling,
        "BL_FPS": str(fps_limit),
        "BL_DIRECT": "1" if direct else "0",
        "BL_RUNNER": runner.path if runner else "",
        "BL_RUNNER_KIND": runner.kind if runner else "",
        "BL_PROTON": str(proton) if proton else "",
        "BL_PREFIX": str(prefix) if prefix else "",
        "BL_LOG": str(LAST_RUN_LOG),
        "BL_CRT_SHADER": crt_path,
        "BL_WORKDIR": workdir,
        "BL_STEAM": "1" if game.get("is_steam") else "0",
    }
    for key, value in runtime_values.items():
        lines.append(f"export {key}={shlex.quote(str(value))}")
    lines.append("set -- " + " ".join(shlex.quote(item) for item in full_command))
    lines.append("")

    db.RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    try:
        db.RUNTIME_DIR.chmod(0o700)
    except OSError:
        pass
    for old in db.RUNTIME_DIR.glob(f"launch-{int(game['id'])}-*.sh"):
        try:
            old.unlink()
        except OSError:
            pass
    runtime_path = db.RUNTIME_DIR / f"launch-{int(game['id'])}-{uuid.uuid4().hex[:10]}.sh"
    descriptor = os.open(
        runtime_path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o600,
    )
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
    return runtime_path


class MainWindow(QMainWindow):
    def __init__(self, database: Database) -> None:
        super().__init__()
        self.db = database
        self._active_process: QProcess | None = None
        self._active_game: dict[str, Any] | None = None
        self._minimized_for_game = False
        self._console_return_pending = False
        self._console_monitor = 0
        self._steam_watch_timer: QTimer | None = None
        self._steam_watch_game: dict[str, Any] | None = None
        self._steam_watch_seen = False
        self._steam_watch_misses = 0
        self._steam_watch_ticks = 0
        self._steam_game_name = ""
        self._was_window_visible = True
        self._was_maximized = False
        self._force_quit = False
        self._steam_worker: SteamSyncWorker | None = None
        self._steam_options_worker: SteamOptionsWorker | None = None
        self.console: ConsoleWindow | None = None
        self._steam_pending: tuple[
            SteamOptionsWorker,
            QProgressDialog,
            dict[str, Any] | None,
            bool,
        ] | None = None
        self._toast_generation = 0
        self._qt_translator: QTranslator | None = None
        self._install_qt_translations()
        self._launcher = ensure_launcher()
        self._crt_shader = ensure_crt_shader()
        self.setWindowTitle(f"{APP_NAME} // {APP_VERSION}")
        self.setWindowIcon(app_icon())
        self.setWindowFlags(
            Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.setMinimumSize(1020, 700)
        self.resize(1320, 830)
        self._build_ui()
        self._build_menu()
        self._build_shortcuts()
        self._build_tray()
        self._build_hotkey()
        self._restore_geometry()
        self._refresh_all()
        self._update_sidebar_state()

    # ------------------------------------------------------------------- layout
    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.titlebar = TitleBar(self)
        self.titlebar.menu_requested.connect(self._show_app_menu)
        root_layout.addWidget(self.titlebar)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(196)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(14, 20, 14, 16)
        side.setSpacing(7)
        caption = QLabel(tr("NAWIGACJA"))
        caption.setObjectName("SidebarCaption")
        side.addWidget(caption)
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        menu_items = (
            (tr("01   BIBLIOTEKA"), 0),
            (tr("02   USTAWIENIA"), 1),
            (tr("03   RUNNERY"), 2),
            (tr("04   MANGOHUD"), 3),
        )
        for label, index in menu_items:
            button = QPushButton(label)
            button.setObjectName("NavButton")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            if index == 0:
                button.setChecked(True)
            self.nav_group.addButton(button, index)
            side.addWidget(button)
        side.addStretch(1)
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setStyleSheet("color:#222A31;")
        side.addWidget(separator)
        local = QLabel(tr("LOCAL // SQLITE"))
        local.setObjectName("SidebarCaption")
        side.addWidget(local)
        self.sidebar_live = QLabel(tr("●  MINIMIZE: ON"))
        self.sidebar_live.setObjectName("SidebarLive")
        side.addWidget(self.sidebar_live)
        db_hint = QLabel(str(db.CONFIG_DIR))
        db_hint.setObjectName("SidebarCaption")
        db_hint.setWordWrap(True)
        db_hint.setToolTip(str(db.CONFIG_DIR))
        side.addWidget(db_hint)
        body.addWidget(sidebar)

        self.stack = QStackedWidget()
        self.library_page = LibraryPage(self.db)
        self.settings_page = SettingsPage(self.db)
        self.runner_page = RunnerPage(self.db)
        self.mango_page = MangoPage(self.db)
        for page in (
            self.library_page,
            self.settings_page,
            self.runner_page,
            self.mango_page,
        ):
            self.stack.addWidget(page)
        body.addWidget(self.stack, 1)
        root_layout.addLayout(body, 1)

        self.nav_group.idClicked.connect(self._switch_page)
        self.library_page.launch_requested.connect(self.start_game)
        self.library_page.edit_requested.connect(self.edit_game)
        self.library_page.delete_requested.connect(self.delete_game)
        self.library_page.context_requested.connect(self._show_game_context)
        self.library_page.add_requested.connect(self.add_game)
        self.library_page.sync_requested.connect(self.sync_steam)
        self.library_page.big_picture_requested.connect(self.open_console)
        self.library_page.toast.connect(self.toast)
        self.settings_page.toast.connect(self.toast)
        self.settings_page.steam_sync_requested.connect(self.sync_steam)
        self.settings_page.steam_wrapper_batch_requested.connect(
            self.apply_steam_wrapper_all
        )
        self.settings_page.steam_restore_requested.connect(
            self.restore_steam_backup
        )
        self.settings_page.clear_cache_requested.connect(self.clear_cache_dialog)
        self.settings_page.settings_changed.connect(self._on_settings_changed)
        self.settings_page.theme_changed.connect(self._apply_theme)
        self.settings_page.language_changed.connect(self._on_language_changed)
        self.runner_page.toast.connect(self.toast)
        self.runner_page.runners_changed.connect(self.settings_page.refresh_runners)
        self.mango_page.toast.connect(self.toast)

        status_bar = QFrame()
        status_bar.setObjectName("StatusBar")
        status_bar.setFixedHeight(32)
        status_layout = QHBoxLayout(status_bar)
        status_layout.setContentsMargins(12, 4, 6, 4)
        status_layout.setSpacing(10)
        self.status_label = QLabel(tr("GOTOWY"))
        self.status_label.setObjectName("StatusText")
        status_layout.addWidget(self.status_label, 1)
        self.ghost_badge = QLabel(tr("MINIMIZE // ON"))
        self.ghost_badge.setObjectName("GhostBadge")
        status_layout.addWidget(self.ghost_badge)
        grip = QSizeGrip(status_bar)
        status_layout.addWidget(grip, 0, Qt.AlignmentFlag.AlignBottom)
        root_layout.addWidget(status_bar)

    def _switch_page(self, index: int) -> None:
        if 0 <= index < self.stack.count():
            self.stack.setCurrentIndex(index)

    def _build_shortcuts(self) -> None:
        shortcuts = (
            ("Ctrl+N", self.add_game),
            ("Ctrl+R", self._refresh_all),
            ("Ctrl+F", self.library_page.focus_search),
            ("F5", self.sync_steam),
            ("Ctrl+L", self.show_last_run_log),
        )
        for sequence, callback in shortcuts:
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.activated.connect(callback)

    def _build_menu(self) -> None:
        self.app_menu = QMenu(self)
        add_action = QAction(tr("Dodaj grę"), self)
        add_action.setShortcut(QKeySequence("Ctrl+N"))
        add_action.triggered.connect(self.add_game)
        self.app_menu.addAction(add_action)

        sync_action = QAction(tr("Synchronizuj Steam"), self)
        sync_action.setShortcut(QKeySequence("F5"))
        sync_action.triggered.connect(self.sync_steam)
        self.app_menu.addAction(sync_action)

        minimal_action = QAction(tr("Tryb minimalny / tray"), self)
        minimal_action.triggered.connect(self._show_minimal)
        self.app_menu.addAction(minimal_action)

        console_action = QAction(tr("Tryb konsolowy (Big Picture)"), self)
        console_action.triggered.connect(self.open_console)
        self.app_menu.addAction(console_action)
        self.app_menu.addSeparator()

        cache_action = QAction(tr("Wyczyść shader cache..."), self)
        cache_action.triggered.connect(self.clear_cache_dialog)
        self.app_menu.addAction(cache_action)

        log_action = QAction(tr("Pokaż last_run.log"), self)
        log_action.setShortcut(QKeySequence("Ctrl+L"))
        log_action.triggered.connect(self.show_last_run_log)
        self.app_menu.addAction(log_action)

        config_action = QAction(tr("Otwórz katalog konfiguracji"), self)
        config_action.triggered.connect(self._open_config_dir)
        self.app_menu.addAction(config_action)
        self.app_menu.addSeparator()

        about_action = QAction(tr("O programie"), self)
        about_action.triggered.connect(self._about)
        self.app_menu.addAction(about_action)

        quit_action = QAction(tr("Zakończ"), self)
        quit_action.triggered.connect(self.quit_app)
        self.app_menu.addAction(quit_action)

    def _show_app_menu(self) -> None:
        position = self.titlebar.mapToGlobal(
            QPoint(max(0, self.titlebar.width() - 130), 50)
        )
        self.app_menu.exec(position)

    def _show_minimal(self) -> None:
        self.library_page.search_edit.clear()
        self.library_page.set_view("minimal")
        self.nav_group.button(0).setChecked(True)
        self.stack.setCurrentIndex(0)
        self.show_window()

    # ------------------------------------------------------------------- tray
    def _build_tray(self) -> None:
        self.tray: QSystemTrayIcon | None = None
        self.tray_menu: QMenu | None = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray = QSystemTrayIcon(app_icon(96), self)
        self.tray.setToolTip(f"{APP_NAME} // Game Runtime Control")
        self.tray_menu = QMenu(self)
        self.tray_menu.setObjectName("TrayMenu")
        self.tray_menu.setStyleSheet(build_qss(TRAY_QSS))
        self.tray_menu.setMinimumWidth(300)
        self.tray_menu.setToolTipsVisible(True)
        self.tray_menu.setSeparatorsCollapsible(False)
        self.tray.setContextMenu(self.tray_menu)
        self.tray.activated.connect(self._tray_activated)
        self.tray.show()
        self._refresh_tray_menu()

    def _tray_game_icon(self, game: dict[str, Any]) -> QIcon:
        cover = Path(str(game.get("cover_path", "") or "")).expanduser()
        if cover.is_file():
            icon = QIcon(str(cover))
            if not icon.isNull():
                return icon
        return app_icon(40)

    def _refresh_tray_menu(self) -> None:
        menu = getattr(self, "tray_menu", None)
        if menu is None:
            return
        menu.clear()

        header = QWidget(menu)
        header.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(9, 7, 10, 7)
        header_layout.setSpacing(10)
        icon_label = QLabel()
        icon_label.setPixmap(app_icon(40).pixmap(40, 40))
        header_layout.addWidget(icon_label)
        text_box = QVBoxLayout()
        text_box.setSpacing(1)
        title = QLabel(tr("BOOSTLAYER"))
        title.setStyleSheet(
            "color:#00E5FF; font-weight:800; letter-spacing:2px; font-size:10pt;"
        )
        subtitle = QLabel(tr("GAME RUNTIME CONTROL"))
        subtitle.setStyleSheet(
            "color:#6C808C; font-family:'DejaVu Sans Mono'; font-size:7pt;"
        )
        text_box.addWidget(title)
        text_box.addWidget(subtitle)
        header_layout.addLayout(text_box)
        header_layout.addStretch(1)
        header_action = QWidgetAction(menu)
        header_action.setDefaultWidget(header)
        menu.addAction(header_action)
        menu.addSeparator()

        if self._active_process is not None and self._active_game:
            status_name = str(self._active_game.get("name", "")).replace("&", "&&")
            status_text = tr("●  GRA: {name}", name=status_name)
        elif self._steam_game_name:
            status_name = self._steam_game_name.replace("&", "&&")
            status_text = tr("●  STEAM: {name}", name=status_name)
        else:
            status_text = tr("○  Brak aktywnej gry")
        status = menu.addAction(status_text)
        status.setEnabled(False)
        hud_on = self.db.get_bool("mangohud", True)
        hud_text = (
            tr("MangoHud: ON")
            if hud_on and shutil.which("mangohud")
            else (tr("MangoHud: BRAK") if hud_on else tr("MangoHud: OFF"))
        )
        hud = menu.addAction(hud_text)
        hud.setEnabled(False)
        gm_on = self.db.get_bool("gamemode", True)
        gm_text = (
            tr("GameMode: ON")
            if gm_on and shutil.which("gamemoderun")
            else (tr("GameMode: BRAK") if gm_on else tr("GameMode: OFF"))
        )
        gamemode = menu.addAction(gm_text)
        gamemode.setEnabled(False)

        menu.addSeparator()
        section = menu.addAction(tr("BIBLIOTEKA"))
        section.setEnabled(False)
        games = self.db.list_games()
        for game in games[:8]:
            game_name = str(game.get("name", tr("Bez nazwy"))).replace("&", "&&")
            action = menu.addAction(
                self._tray_game_icon(game),
                game_name + ("   [Steam]" if game.get("is_steam") else ""),
            )
            action.triggered.connect(
                lambda _checked=False, game_id=int(game["id"]): self.start_game(game_id)
            )
        if not games:
            empty = menu.addAction(tr("Brak gier — dodaj pierwszą w bibliotece."))
            empty.setEnabled(False)

        menu.addSeparator()
        if self.isVisible() and not self.isMinimized():
            hide_action = menu.addAction(tr("Minimalizuj Boostlayer"))
            hide_action.triggered.connect(self.showMinimized)
        else:
            show_action = menu.addAction(tr("Pokaż Boostlayer"))
            show_action.triggered.connect(self.show_window)
        minimal_action = menu.addAction(tr("Tryb minimalny"))
        minimal_action.triggered.connect(self._show_minimal)
        settings_action = menu.addAction(tr("Ustawienia"))
        settings_action.triggered.connect(self._open_settings_page)
        console_action = menu.addAction(tr("Tryb konsolowy  [Big Picture]"))
        console_action.triggered.connect(self.open_console)

        if self._active_process is not None and self._active_game:
            stop_name = str(self._active_game.get("name", "")).replace("&", "&&")
            stop = menu.addAction(tr("Zakończ grę: {name}", name=stop_name))
            stop.triggered.connect(self.stop_game)

        menu.addSeparator()
        quit_action = menu.addAction(tr("Zakończ Boostlayer"))
        quit_action.triggered.connect(self.quit_app)

    def _open_settings_page(self) -> None:
        self.nav_group.button(1).setChecked(True)
        self.stack.setCurrentIndex(1)
        self.show_window()

    def open_console(self) -> None:
        if self.console is None:
            self.console = ConsoleWindow(self.db)
            self.console.launch_requested.connect(self._console_launch)
            self.console.edit_requested.connect(self._console_edit)
            self.console.closed.connect(self._console_closed)
        self.console.reload()
        self.library_page.set_console_active(True)
        self.hide()
        self.console.open_on_screen(self.db.get_int("console_monitor", 0))

    def _console_launch(self, game_id: int) -> None:
        self._console_return_pending = True
        self._console_monitor = (
            self.console._monitor_index if self.console is not None else 0
        )
        self.start_game(game_id)
        if (
            self._active_process is None
            and self._steam_watch_game is None
            and not self._steam_game_name
        ):
            # The launch was cancelled (for example by a Winetricks prompt).
            self._console_return_pending = False

    def _return_to_console(self) -> None:
        if self.console is None:
            self.open_console()
            return
        self.library_page.set_console_active(True)
        self.hide()
        self.console.reload()
        self.console.open_on_screen(self._console_monitor)

    def _console_edit(self, game_id: int) -> None:
        self._console_return_pending = False
        if self.console is not None:
            self.console.hide()
        self.library_page.set_console_active(False)
        self.show_window()
        self.edit_game(game_id)

    def _console_closed(self) -> None:
        self._console_return_pending = False
        self.library_page.set_console_active(False)
        self.show_window()

    def _tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.show_window()

    def _build_hotkey(self) -> None:
        self._hotkey = X11GlobalHotkey(self)
        self._hotkey.activated.connect(self.toggle_window)
        self._hotkey_shortcut = QShortcut(QKeySequence("Ctrl+Alt+S"), self)
        self._hotkey_shortcut.activated.connect(self.toggle_window)
        self._hotkey_shortcut.setEnabled(False)
        self._apply_hotkey_setting()

    def _apply_hotkey_setting(self) -> None:
        enabled = self.db.get_bool("global_hotkey", True)
        if not enabled:
            self._hotkey.stop()
            self._hotkey_shortcut.setEnabled(False)
            return
        if not self._hotkey.available:
            self._hotkey.start()
        self._hotkey_shortcut.setEnabled(not self._hotkey.available)

    def toggle_window(self) -> None:
        if self.console is not None and self.console.isVisible():
            self.console.close_console()
            return
        if self.isVisible() and not self.isMinimized():
            self.showMinimized()
        else:
            self.show_window()

    def shutdown_hotkey(self) -> None:
        self._hotkey.stop()

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange:
            QTimer.singleShot(0, self._refresh_tray_menu)

    def show_window(self) -> None:
        self._minimized_for_game = False
        self.showNormal()
        self.raise_()
        self.activateWindow()
        self._update_sidebar_state()
        self._refresh_tray_menu()

    def hide_to_tray(self) -> None:
        if self.tray is not None:
            self.hide()
            self._refresh_tray_menu()
            self.tray.showMessage(
                APP_NAME,
                tr("Działa w tle. Menu traya uruchomi gry i pokaże okno."),
                QSystemTrayIcon.MessageIcon.Information,
                2600,
            )

    # ------------------------------------------------------------------ state
    def toast(self, message: str) -> None:
        self._toast_generation += 1
        generation = self._toast_generation
        self.status_label.setText(message)
        QTimer.singleShot(
            4500,
            lambda: self.status_label.setText(tr("GOTOWY"))
            if generation == self._toast_generation
            else None,
        )

    def _update_sidebar_state(self) -> None:
        minimize = self.db.get_bool("ghost_mode", True)
        if self._active_process is not None:
            self.sidebar_live.setText(tr("●  GAME: RUNNING"))
            self.ghost_badge.setText(tr("MINIMIZE // GAME ACTIVE"))
        else:
            self.sidebar_live.setText(
                tr("●  MINIMIZE: ON") if minimize else tr("○  MINIMIZE: OFF")
            )
            self.ghost_badge.setText(
                tr("MINIMIZE // ON") if minimize else tr("MINIMIZE // OFF")
            )

    def _refresh_all(self) -> None:
        self.library_page.reload()
        self.settings_page.refresh_runners()
        self.runner_page.refresh()
        if self.console is not None:
            self.console.reload()
        self._update_sidebar_state()
        self._refresh_tray_menu()
        self.toast(tr("Biblioteka odświeżona."))

    def _install_qt_translations(self) -> None:
        """Load Qt's own translations for standard dialog buttons."""
        app = QCoreApplication.instance()
        if app is None:
            return
        if self._qt_translator is not None:
            app.removeTranslator(self._qt_translator)
            self._qt_translator.deleteLater()
            self._qt_translator = None
        language = get_language()
        if language == "en":
            return
        translator = QTranslator(self)
        translations = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
        for filename in (f"qtbase_{language}.qm", f"qt_{language}.qm"):
            if translator.load(filename, translations):
                app.installTranslator(translator)
                self._qt_translator = translator
                return
        translator.deleteLater()

    def _on_language_changed(self, code: str) -> None:
        set_language(code)
        current_page = self.stack.currentIndex()
        QTimer.singleShot(0, lambda: self._rebuild_ui(current_page))

    def _rebuild_ui(self, current_page: int) -> None:
        """Rebuild the presentation layer after a live language change."""
        self._install_qt_translations()
        if self.console is not None:
            self.console.hide()
            self.console.deleteLater()
            self.console = None
        if getattr(self, "tray", None) is not None:
            self.tray.hide()
            self.tray.deleteLater()
            self.tray = None
        if getattr(self, "tray_menu", None) is not None:
            self.tray_menu.deleteLater()
            self.tray_menu = None
        if getattr(self, "app_menu", None) is not None:
            self.app_menu.deleteLater()
            self.app_menu = None
        for shortcut in self.findChildren(QShortcut):
            if shortcut is getattr(self, "_hotkey_shortcut", None):
                continue
            shortcut.deleteLater()
        if getattr(self, "nav_group", None) is not None:
            self.nav_group.deleteLater()
            self.nav_group = None
        central = self.takeCentralWidget()
        if central is not None:
            central.deleteLater()

        self._build_ui()
        self._build_menu()
        self._build_shortcuts()
        self._build_tray()
        self._refresh_all()
        self._update_sidebar_state()
        if 0 <= current_page < self.stack.count():
            self.stack.setCurrentIndex(current_page)
            button = self.nav_group.button(current_page)
            if button is not None:
                button.setChecked(True)
        self.toast(tr("Język: {name}", name=LANGUAGES[get_language()]))

    def _on_settings_changed(self) -> None:
        self.settings_page.refresh_runners()
        self._apply_theme(self.db.get_setting("theme", DEFAULT_THEME))
        self._update_sidebar_state()
        self._refresh_tray_menu()
        self._apply_hotkey_setting()
        self.toast(tr("Konfiguracja globalna zapisana."))

    def _apply_theme(self, key: str) -> None:
        theme = set_theme(key)
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(build_qss(QSS))
            app.setWindowIcon(app_icon())
        self.setWindowIcon(app_icon())
        self.library_page.reload()
        if self.tray is not None:
            self.tray.setIcon(app_icon(96))
        if getattr(self, "tray_menu", None) is not None:
            self.tray_menu.setStyleSheet(build_qss(TRAY_QSS))
        if self.console is not None:
            self.console.setWindowIcon(app_icon())
            self.console.reload()
        self._refresh_tray_menu()
        self.titlebar.update()
        log.info("Theme applied: %s", theme.name)

    # ---------------------------------------------------------------- library
    def add_game(self) -> None:
        dialog = GameDialog(self.db, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.library_page.reload()
            self._refresh_tray_menu()
            self.toast(tr("Gra dodana do biblioteki."))

    def edit_game(self, game_id: int) -> None:
        game = self.db.get_game(game_id)
        if not game:
            return
        dialog = GameDialog(self.db, game=game, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.library_page.reload()
            self._refresh_tray_menu()
            self.toast(tr("Zapisano konfigurację gry."))

    def delete_game(self, game_id: int) -> None:
        game = self.db.get_game(game_id)
        if not game:
            return
        answer = QMessageBox.question(
            self,
            tr("Usuń grę"),
            tr(
                "Usunąć „{name}” z biblioteki?\n\n"
                "WINEPREFIX pozostanie na dysku:\n{prefix}",
                name=game["name"],
                prefix=game.get("wine_prefix", ""),
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.db.delete_game(game_id)
        self.library_page.reload()
        self._refresh_tray_menu()
        self.toast(tr("Wpis usunięty z biblioteki."))

    def _show_game_context(self, game_id: int, position: QPoint) -> None:
        game = self.db.get_game(game_id)
        if not game:
            return
        menu = QMenu(self)
        launch = menu.addAction(tr("▶  Uruchom grę"))
        launch.triggered.connect(lambda: self.start_game(game_id))
        edit = menu.addAction(tr("✎  Edytuj"))
        edit.triggered.connect(lambda: self.edit_game(game_id))
        if game.get("is_steam") and game.get("steam_appid"):
            copy_option = menu.addAction(tr("⧉  Kopiuj opcję uruchamiania Steam"))
            copy_option.triggered.connect(lambda: self._copy_steam_option_for())
            repair = menu.addAction(tr("🛠  Napraw opcję uruchamiania Steam"))
            repair.triggered.connect(lambda: self.repair_steam_options(game_id))
        menu.addSeparator()
        folder = menu.addAction(tr("Otwórz katalog gry"))
        folder_target = Path(str(game.get("exe_path", ""))).expanduser()
        if folder_target.is_file():
            folder_target = folder_target.parent
        folder.triggered.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder_target)))
        )
        winetricks = menu.addAction(tr("Winetricks…"))
        winetricks.triggered.connect(lambda: self.open_winetricks(game_id))
        cache = menu.addAction(tr("Wyczyść shader cache tej gry"))
        cache.triggered.connect(lambda: self.clear_cache_for_game(game_id))
        menu.addSeparator()
        delete = menu.addAction(tr("×  Usuń z biblioteki"))
        delete.triggered.connect(lambda: self.delete_game(game_id))
        menu.exec(position)

    def open_winetricks(self, game_id: int) -> None:
        game = self.db.get_game(game_id)
        if not game:
            self.toast(tr("Nie znaleziono gry w bibliotece."))
            return
        dialog = WinetricksDialog(self.db, game, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.db.update_game(
                int(game_id),
                wine_prefix=dialog.prefix_path(),
                winetricks_verbs=dialog.verbs_text(),
                winetricks_auto=1 if dialog.auto_install() else 0,
                winetricks_state=dialog.state(),
            )
            self.library_page.reload()
            self._refresh_tray_menu()
            self.toast(tr("Konfiguracja Winetricks zapisana."))

    def _copy_steam_option_for(self) -> None:
        try:
            path = ensure_steam_wrapper()
        except OSError as exc:
            QMessageBox.warning(self, tr("Steam wrapper"), str(exc))
            return
        self.db.set_setting("steam_wrapper", str(path))
        QApplication.clipboard().setText(steam_launch_option(path))
        self.toast(tr("Opcja uruchamiania Steam skopiowana do schowka."))

    # ------------------------------------------------------------------ Steam
    def sync_steam(self) -> None:
        if self._steam_worker is not None:
            self.toast(tr("Synchronizacja Steam już trwa."))
            return
        self.library_page.set_sync_busy(True)
        self.settings_page.set_busy(True)
        self.toast(tr("Synchronizacja Steam..."))
        worker = SteamSyncWorker(self)
        self._steam_worker = worker
        worker.status.connect(self._steam_status)
        worker.result.connect(self._steam_result)
        worker.finished.connect(self._steam_finished)
        worker.start()

    def _steam_status(self, message: str) -> None:
        self.status_label.setText(message)

    def _steam_result(self, payload: object) -> None:
        data = payload if isinstance(payload, dict) else {}
        if data.get("ok"):
            self.library_page.reload()
            self.settings_page.reload()
            self._refresh_tray_menu()
            self.toast(
                tr(
                    "Steam: +{added} nowych, {updated} zaktualizowanych, "
                    "{skipped} pominiętych.",
                    added=data.get("added", 0),
                    updated=data.get("updated", 0),
                    skipped=data.get("skipped", 0),
                )
            )
        else:
            QMessageBox.warning(
                self,
                tr("Steam"),
                str(data.get("error", tr("Nieznany błąd synchronizacji."))),
            )
            self.toast(tr("Synchronizacja Steam nie powiodła się."))

    def _steam_finished(self) -> None:
        self.library_page.set_sync_busy(False)
        self.settings_page.set_busy(False)
        worker = self._steam_worker
        self._steam_worker = None
        if worker is not None:
            worker.deleteLater()

    # ------------------------------------------------------------- launch core
    def _stage_runtime(self, game: dict[str, Any]) -> Path:
        if not str(game.get("wine_prefix", "")).strip():
            prefix = db.make_prefix(str(game.get("name", "game")))
            self.db.update_game(int(game["id"]), wine_prefix=prefix)
            game = dict(game, wine_prefix=prefix)
        return write_runtime_file(self.db, game)

    def _ensure_game_prefix(self, game: dict[str, Any]) -> dict[str, Any]:
        if int(game.get("is_steam", 0) or 0):
            return game
        if not str(game.get("wine_prefix", "") or "").strip():
            prefix = db.make_prefix(str(game.get("name", "game")))
            self.db.update_game(int(game["id"]), wine_prefix=prefix)
            return dict(game, wine_prefix=prefix)
        return game

    def _dialog_parent(self) -> QWidget:
        console = getattr(self, "console", None)
        if console is not None and console.isVisible():
            return console
        return self

    def _run_winetricks_modal(self, game: dict[str, Any], plan: WinetricksPlan) -> bool:
        dialog_parent = self._dialog_parent()
        progress = QProgressDialog(
            tr("Instaluję komponenty Winetricks..."),
            tr("Anuluj"),
            0,
            0,
            dialog_parent,
        )
        progress.setWindowTitle(tr("Winetricks"))
        progress.setWindowModality(Qt.WindowModality.ApplicationModal)
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        worker = WinetricksWorker(plan, self)
        loop = QEventLoop()
        outcome: dict[str, Any] = {"success": False, "message": ""}

        def finished(success: bool, message: str) -> None:
            outcome["success"] = success
            outcome["message"] = message
            loop.quit()

        worker.result.connect(finished)
        worker.output.connect(
            lambda line: progress.setLabelText(line[-240:] or tr("Winetricks..."))
        )
        progress.canceled.connect(worker.cancel)
        worker.start()
        progress.show()
        loop.exec()
        worker.wait(5000)
        progress.close()
        progress.deleteLater()
        worker.deleteLater()
        if outcome["success"]:
            self.db.update_game(
                int(game["id"]), winetricks_state=plan.state
            )
            self.toast(tr("Komponenty Winetricks zostały zainstalowane."))
            return True
        answer = QMessageBox.warning(
            dialog_parent,
            tr("Winetricks"),
            tr(
                "Nie udało się zainstalować komponentów Winetricks.\n\n{error}\n\n"
                "Uruchomić grę mimo to?",
                error=outcome["message"],
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _maybe_prepare_winetricks(self, game: dict[str, Any]) -> bool:
        if not int(game.get("winetricks_auto", 0) or 0):
            return True
        dialog_parent = self._dialog_parent()
        try:
            verbs = normalize_winetricks_verbs(str(game.get("winetricks_verbs", "")))
        except ValueError as exc:
            QMessageBox.warning(dialog_parent, tr("Winetricks"), str(exc))
            return True
        if not verbs:
            return True
        try:
            plan = build_winetricks_plan(self.db, game, verbs)
        except Exception as exc:
            answer = QMessageBox.warning(
                dialog_parent,
                tr("Winetricks"),
                tr(
                    "Nie można przygotować Winetricks:\n\n{error}\n\n"
                    "Uruchomić grę mimo to?",
                    error=exc,
                ),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            return answer == QMessageBox.StandardButton.Yes
        if winetricks_applied(game, plan):
            return True
        answer = QMessageBox.question(
            dialog_parent,
            tr("Winetricks"),
            tr(
                "Ta gra ma włączoną automatyczną instalację komponentów.\n\n"
                "Zainstalować teraz: {verbs}?",
                verbs=" ".join(verbs),
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return False
        return self._run_winetricks_modal(game, plan)

    def start_game(self, game_id: int) -> None:
        if self._active_process is not None:
            self.toast(tr("Gra już działa. Zakończ bieżący proces przed startem kolejnej."))
            return
        game = self.db.get_game(int(game_id))
        if not game:
            self.toast(tr("Nie znaleziono gry w bibliotece."))
            return
        game = self._ensure_game_prefix(game)
        if not self._maybe_prepare_winetricks(game):
            return
        if self.console is not None and self.console.isVisible():
            self.console.hide()
        if game.get("is_steam") and game.get("steam_appid"):
            self.start_steam_game(game)
            return
        self._steam_game_name = ""
        try:
            runtime = self._stage_runtime(game)
        except Exception as exc:
            log.error("Cannot prepare launch: %s", exc)
            QMessageBox.warning(self._dialog_parent(), tr("Nie można uruchomić"), str(exc))
            return

        bits = exe_bits(str(game.get("exe_path", "")))
        if (
            bits == 32
            and self.db.get_bool("mangohud", True)
            and not mangohud32_path()
        ):
            self.toast(
                tr("Gra jest 32-bitowa, a brakuje 32-bitowego MangoHud. "
                "Użyj Ustawienia → Zależności → MangoHud 32-bit.")
            )
        if (
            bits == 32
            and self.db.get_bool("gamemode", True)
            and not gamemode32_installed()
        ):
            self.toast(
                tr("Brak 32-bitowych bibliotek GameMode — zainstaluj je w "
                "Ustawienia → Zależności.")
            )
        if self.db.get_bool("mangohud", True) and not shutil.which("mangohud"):
            self.toast(
                tr("MangoHud nie jest zainstalowany — użyj Ustawienia → Zależności.")
            )
        if self.db.get_bool("gamemode", True) and not shutil.which("gamemoderun"):
            self.toast(
                tr("GameMode nie jest zainstalowany — użyj Ustawienia → Zależności.")
            )
        if (
            str(game.get("scaling_mode", "native")) not in {"native"}
            and self.db.get_bool("gamescope", True)
            and not shutil.which("gamescope")
        ):
            self.toast(
                tr("Gamescope nie jest zainstalowany — profil skalowania zostanie "
                "pominięty. Użyj Proton FSR lub zainstaluj Gamescope.")
            )

        process = QProcess(self)
        process.setProgram("/bin/sh")
        process.setArguments([str(self._launcher), str(runtime)])
        working_dir = Path(str(game.get("exe_path", ""))).expanduser().parent
        if working_dir.is_dir():
            process.setWorkingDirectory(str(working_dir))
        process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        process.started.connect(partial(self._on_game_started, process, game))
        process.finished.connect(partial(self._on_game_finished, process))
        process.errorOccurred.connect(partial(self._on_game_error, process))
        self._active_process = process
        self._active_game = game
        self.status_label.setText(f"URUCHAMIANIE // {game.get('name', '')}")
        self._update_sidebar_state()
        log.info("Launching game id=%s name=%s runtime=%s", game_id, game.get("name"), runtime)
        process.start()

    def start_steam_game(self, game: dict[str, Any]) -> None:
        """Hand a Steam entry to Steam, injecting LaunchOptions when needed."""
        if self._steam_options_worker is not None:
            self.toast(tr("Trwa operacja na konfiguracji Steam. Poczekaj."))
            return
        appid = str(game.get("steam_appid", "")).strip()
        client = steam_client_command()
        if not client:
            QMessageBox.warning(
                self,
                tr("Steam"),
                tr("Nie znaleziono klienta Steam w PATH ani Flatpaka "
                "com.valvesoftware.Steam."),
            )
            return
        try:
            wrapper = ensure_steam_wrapper()
            option = steam_launch_option(wrapper)
            self.db.set_setting("steam_wrapper", str(wrapper))
        except OSError as exc:
            QMessageBox.warning(
                self,
                tr("Steam wrapper"),
                tr("Nie można zapisać wrappera Steam:\n{error}", error=exc),
            )
            return

        if not self.db.get_bool("auto_steam_wrapper", True):
            self._launch_steam_client(game)
            return

        action = steam_launch_action_for_appid(appid, wrapper)
        if action == "ok":
            self._launch_steam_client(game)
            return
        if action == "complex":
            QApplication.clipboard().setText(option)
            QMessageBox.information(
                self,
                tr("Steam wrapper"),
                tr("Ta gra ma już złożone LaunchOptions zawierające %command%. "
                "Boostlayer nie nadpisze ich automatycznie. Poprawna linia "
                "została skopiowana do schowka; możesz podmienić ją ręcznie."),
            )
            self._launch_steam_client(game)
            return
        if action in {"no_account", "no_config", "parse_error"}:
            QApplication.clipboard().setText(option)
            QMessageBox.warning(
                self,
                tr("Steam wrapper"),
                tr("Nie można odczytać aktywnego profilu Steam lub pliku "
                "localconfig.vdf. Opcja uruchamiania została skopiowana do "
                "schowka. Gra uruchomi się bez automatycznego wrappera."),
            )
            self._launch_steam_client(game)
            return

        if steam_is_running():
            answer = QMessageBox.question(
                self,
                tr("Zamknąć Steam?"),
                tr("Aby zapisać LaunchOptions, Steam musi zostać zamknięty. "
                "Zostanie uruchomiony ponownie razem z grą.\n\n"
                "Zamknięcie może przerwać pobieranie lub aktualizację. "
                "Kontynuować?"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                QApplication.clipboard().setText(option)
                self._launch_steam_client(game)
                self.toast(tr("Wrapper nie został zapisany; opcja jest w schowku."))
                return

        self._start_steam_options_worker(
            [appid],
            wrapper,
            launch_game=game,
            title="Steam wrapper",
        )

    def _launch_steam_client(self, game: dict[str, Any]) -> None:
        appid = str(game.get("steam_appid", "")).strip()
        client = steam_client_command()
        if not client:
            QMessageBox.warning(self, tr("Steam"), tr("Nie znaleziono klienta Steam."))
            return
        program, *arguments = client
        ok, _pid = QProcess.startDetached(
            program, arguments + ["-applaunch", appid]
        )
        if not ok:
            QMessageBox.warning(self, tr("Steam"), tr("Nie udało się uruchomić klienta Steam."))
            return
        log.info("Steam launch appid=%s client=%s", appid, client)
        self._steam_game_name = str(game.get("name", appid))
        self.status_label.setText(f"STEAM // {self._steam_game_name}")
        self._refresh_tray_menu()
        self._minimize_after_launch(game)

    def _start_steam_options_worker(
        self,
        appids: list[str],
        wrapper: Path,
        *,
        launch_game: dict[str, Any] | None = None,
        restore: bool = False,
        title: str = "Steam wrapper",
    ) -> None:
        if self._steam_options_worker is not None:
            self.toast(tr("Trwa już operacja na konfiguracji Steam."))
            return
        progress = QProgressDialog(
            tr("Przygotowuję konfigurację Steam..."), None, 0, 0, self
        )
        progress.setWindowTitle(title)
        progress.setWindowModality(Qt.WindowModality.ApplicationModal)
        progress.setCancelButton(None)
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        progress.show()
        worker = SteamOptionsWorker(
            appids, wrapper, close_steam=True, restore=restore, parent=self
        )
        self._steam_options_worker = worker
        self._steam_pending = (worker, progress, launch_game, restore)
        worker.status.connect(progress.setLabelText)
        worker.result.connect(self._on_steam_options_result)
        worker.finished.connect(self._on_steam_options_finished)
        worker.start()

    def _on_steam_options_result(self, payload: object) -> None:
        pending = self._steam_pending
        if pending is None:
            return
        self._steam_pending = None
        worker, progress, launch_game, restore = pending
        self._steam_options_done(
            worker, progress, payload, launch_game, restore
        )

    def _on_steam_options_finished(self) -> None:
        worker = self._steam_options_worker
        if worker is not None:
            self._steam_options_worker = None
            worker.deleteLater()

    def _steam_options_done(
        self,
        worker: SteamOptionsWorker,
        progress: QProgressDialog,
        payload: object,
        launch_game: dict[str, Any] | None,
        restore: bool,
    ) -> None:
        progress.close()
        progress.deleteLater()
        data = payload if isinstance(payload, dict) else {}
        if not data.get("ok"):
            error = str(data.get("error", tr("Nieznany błąd konfiguracji Steam.")))
            try:
                QApplication.clipboard().setText(
                    steam_launch_option(ensure_steam_wrapper())
                )
            except OSError:
                pass
            QMessageBox.warning(
                self,
                tr("Steam wrapper"),
                tr(
                    "{error}\n\nPoprawna opcja uruchamiania została skopiowana "
                    "do schowka.",
                    error=error,
                ),
            )
            if launch_game is not None:
                self._launch_steam_client(launch_game)
            return
        if restore:
            QMessageBox.information(
                self,
                tr("Steam backup"),
                tr(
                    "Przywrócono backup:\n{path}\n\nUruchom Steam ponownie.",
                    path=data.get("restored", ""),
                ),
            )
            self.toast(tr("Backup localconfig.vdf przywrócony."))
            return
        updated = int(data.get("updated", 0))
        skipped = int(data.get("skipped", 0))
        unchanged = int(data.get("unchanged", 0))
        message = (
            f"Steam: dopisano {updated}, bez zmian {unchanged}, "
            f"pominięto {skipped}."
        )
        self.toast(message)
        if launch_game is not None:
            self._launch_steam_client(launch_game)
        else:
            QMessageBox.information(
                self,
                tr("Steam wrapper"),
                tr(
                    "{message}\n\nUruchom Steam ponownie, aby zobaczyć zmiany.",
                    message=message,
                ),
            )

    def apply_steam_wrapper_all(self) -> None:
        games = [
            game
            for game in self.db.list_games()
            if game.get("is_steam") and str(game.get("steam_appid", "")).strip()
        ]
        if not games:
            QMessageBox.information(
                self, tr("Steam wrapper"), tr("Brak gier Steam w bibliotece.")
            )
            return
        try:
            wrapper = ensure_steam_wrapper()
        except OSError as exc:
            QMessageBox.warning(self, tr("Steam wrapper"), str(exc))
            return
        answer = QMessageBox.question(
            self,
            tr("Zastosuj wrapper do wszystkich gier Steam"),
            tr(
                "Zaktualizować LaunchOptions dla {count} gier Steam?\n\n"
                "Steam zostanie zamknięty, plik localconfig.vdf zostanie "
                "zabezpieczony backupem, a następnie Steam trzeba będzie "
                "uruchomić ponownie. Kontynuować?",
                count=len(games),
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._start_steam_options_worker(
            [str(game["steam_appid"]) for game in games],
            wrapper,
            title=tr("Steam wrapper — wszystkie gry"),
        )

    def repair_steam_options(self, game_id: int) -> None:
        game = self.db.get_game(int(game_id))
        if not game or not game.get("is_steam"):
            return
        appid = str(game.get("steam_appid", "")).strip()
        if not appid:
            return
        try:
            wrapper = ensure_steam_wrapper()
        except OSError as exc:
            QMessageBox.warning(self, tr("Steam wrapper"), str(exc))
            return
        action = steam_launch_action_for_appid(appid, wrapper)
        if action == "ok":
            QMessageBox.information(
                self,
                tr("Steam wrapper"),
                tr("LaunchOptions tej gry są już poprawne."),
            )
            return
        if action == "complex":
            QMessageBox.information(
                self,
                tr("Steam wrapper"),
                tr("Ta gra ma złożone LaunchOptions z %command%. "
                "Nie nadpisuję ich automatycznie."),
            )
            return
        if steam_is_running():
            answer = QMessageBox.question(
                self,
                tr("Zamknąć Steam?"),
                tr("Aby naprawić LaunchOptions, Steam musi zostać zamknięty. "
                "Kontynuować?"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self._start_steam_options_worker(
            [appid],
            wrapper,
            title=tr("Naprawa Steam — {name}", name=game.get("name", appid)),
        )

    def restore_steam_backup(self) -> None:
        account = steam_account()
        backup = latest_steam_backup(account.account_id if account else None)
        if backup is None:
            QMessageBox.information(
                self,
                tr("Steam backup"),
                tr(
                    "Brak backupu localconfig.vdf w {path}.",
                    path=db.CONFIG_DIR / "steam-backups",
                ),
            )
            return
        answer = QMessageBox.question(
            self,
            tr("Przywrócić backup Steam?"),
            tr(
                "Przywrócić plik:\n{path}\n\n"
                "Bieżące LaunchOptions zostaną nadpisane. Steam musi być zamknięty. "
                "Kontynuować?",
                path=backup,
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            wrapper = ensure_steam_wrapper()
        except OSError as exc:
            QMessageBox.warning(self, tr("Steam wrapper"), str(exc))
            return
        self._start_steam_options_worker(
            [], wrapper, restore=True, title="Steam backup"
        )

    def _start_steam_watch(self, game: dict[str, Any]) -> None:
        if not self._console_return_pending:
            return
        appid = str(game.get("steam_appid", "") or "").strip()
        if not appid:
            return
        self._stop_steam_watch()
        self._steam_watch_game = dict(game)
        self._steam_watch_seen = False
        self._steam_watch_misses = 0
        self._steam_watch_ticks = 0
        timer = QTimer(self)
        timer.setInterval(900)
        timer.timeout.connect(self._poll_steam_watch)
        self._steam_watch_timer = timer
        timer.start()

    def _stop_steam_watch(self) -> None:
        if self._steam_watch_timer is not None:
            self._steam_watch_timer.stop()
            self._steam_watch_timer.deleteLater()
            self._steam_watch_timer = None
        self._steam_watch_game = None
        self._steam_watch_seen = False
        self._steam_watch_misses = 0
        self._steam_watch_ticks = 0

    def _poll_steam_watch(self) -> None:
        game = self._steam_watch_game
        if game is None:
            self._stop_steam_watch()
            return
        self._steam_watch_ticks += 1
        appid = str(game.get("steam_appid", "") or "")
        running = steam_game_process_running(
            appid, str(game.get("exe_path", "") or "")
        )
        if running:
            self._steam_watch_seen = True
            self._steam_watch_misses = 0
            return
        if self._steam_watch_seen:
            self._steam_watch_misses += 1
            if self._steam_watch_misses < 3:
                return
            name = str(game.get("name", self._steam_game_name or tr("Gra")))
            self._stop_steam_watch()
            self._steam_game_name = ""
            self._refresh_tray_menu()
            self._update_sidebar_state()
            self.status_label.setText(
                tr("ZAKOŃCZONO // {name}", name=name)
            )
            if self._console_return_pending:
                self._console_return_pending = False
                self._return_to_console()
            return
        if self._steam_watch_ticks >= 240:
            # Never insist forever if Steam did not expose the game process.
            self._stop_steam_watch()

    def _minimize_after_launch(self, game: dict[str, Any]) -> None:
        if self._console_return_pending:
            if self.console is not None:
                self.console.hide()
            self.library_page.set_console_active(False)
            self._refresh_tray_menu()
            if int(game.get("is_steam", 0) or 0):
                self._start_steam_watch(game)
            return
        if not self.db.get_bool("ghost_mode", True):
            return
        self._was_window_visible = self.isVisible()
        self._was_maximized = self.isMaximized()
        self._minimized_for_game = True
        self.showMinimized()
        self._refresh_tray_menu()
        if self.tray is not None:
            self.tray.showMessage(
                tr("{app} // gra działa", app=APP_NAME),
                tr(
                    "{name} uruchomiona. Boostlayer zminimalizowany — "
                    "Ctrl+Alt+S przywraca okno.",
                    name=game.get("name", tr("Gra")),
                ),
                QSystemTrayIcon.MessageIcon.Information,
                2600,
            )

    def _on_game_started(self, process: QProcess, game: dict[str, Any]) -> None:
        if process is not self._active_process:
            return
        self.status_label.setText(tr("GRA DZIAŁA // {name}", name=game.get("name", "")))
        self._refresh_tray_menu()
        self._minimize_after_launch(game)

    def _on_game_finished(
        self, process: QProcess, exit_code: int, _exit_status: QProcess.ExitStatus
    ) -> None:
        if process is not self._active_process:
            return
        game = self._active_game or {}
        console_return = self._console_return_pending
        self._console_return_pending = False
        self._active_process = None
        self._active_game = None
        process.deleteLater()
        if console_return:
            self._minimized_for_game = False
        elif self._minimized_for_game:
            self._minimized_for_game = False
            if self._was_window_visible:
                self.show_window()
                if self._was_maximized:
                    self.showMaximized()
        debug = self.db.get_bool("debug_logging", False)
        suffix = tr(" Log: {path}", path=LAST_RUN_LOG) if debug else ""
        self.status_label.setText(
            tr(
                "ZAKOŃCZONO // {name} // kod {code}.{suffix}",
                name=game.get("name", tr("gra")),
                code=exit_code,
                suffix=suffix,
            )
        )
        self._update_sidebar_state()
        self._refresh_tray_menu()
        if self.tray is not None and not console_return:
            self.tray.showMessage(
                tr("{app} // koniec gry", app=APP_NAME),
                tr(
                    "{name} zakończona (kod {code}).",
                    name=game.get("name", tr("Gra")),
                    code=exit_code,
                ),
                QSystemTrayIcon.MessageIcon.Information,
                2600,
            )
        if console_return:
            self._return_to_console()

    def _on_game_error(self, process: QProcess, error: QProcess.ProcessError) -> None:
        if process is not self._active_process:
            return
        if error != QProcess.ProcessError.FailedToStart:
            self.status_label.setText(tr("BŁĄD PROCESU // {error}", error=error.name))
            return
        console_return = self._console_return_pending
        self._console_return_pending = False
        self._active_process = None
        self._active_game = None
        self._minimized_for_game = False
        process.deleteLater()
        if not console_return:
            self.show_window()
        self._update_sidebar_state()
        self._refresh_tray_menu()
        warning_parent = (
            self.console if console_return and self.console is not None else self
        )
        QMessageBox.warning(
            warning_parent,
            tr("Błąd uruchamiania"),
            tr("Nie udało się uruchomić launcher.sh. Sprawdź uprawnienia i log."),
        )
        if console_return:
            self._return_to_console()

    def stop_game(self) -> None:
        process = self._active_process
        if process is None:
            return
        answer = QMessageBox.question(
            self,
            tr("Zakończ grę"),
            tr("Wysłać SIGTERM do procesu gry?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        process.terminate()
        self.status_label.setText(tr("ZATRZYMYWANIE GRY..."))

    # -------------------------------------------------------------- maintenance
    def show_last_run_log(self) -> None:
        if not LAST_RUN_LOG.is_file():
            QMessageBox.information(
                self,
                tr("Brak logu"),
                tr("Włącz „Debug: zapis do last_run.log” w Ustawieniach i uruchom grę."),
            )
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(LAST_RUN_LOG)))

    def _open_config_dir(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(config_dir())))

    def clear_cache_for_game(self, game_id: int) -> None:
        removed = self.db.clear_shader_cache(game_id)
        self.toast(tr("Shader cache: usunięto {count} katalogów.", count=removed))
        QMessageBox.information(
            self,
            tr("Shader cache"),
            tr(
                "Usunięto {count} znanych katalogów cache dla wybranej gry.\n"
                "Dane gry i WINEPREFIX pozostały nienaruszone.",
                count=removed,
            ),
        )

    def clear_cache_dialog(self) -> None:
        games = self.db.list_games()
        labels = [tr("Wszystkie gry (globalnie)")] + [str(game["name"]) for game in games]
        choice, accepted = QInputDialog.getItem(
            self,
            tr("Wyczyść shader cache"),
            tr("Zakres:"),
            labels,
            0,
            False,
        )
        if not accepted:
            return
        removed = 0
        if choice == labels[0]:
            removed += self.db.clear_shader_cache(None)
            for game in games:
                removed += self.db.clear_shader_cache(int(game["id"]))
        else:
            index = labels.index(choice) - 1
            removed = self.db.clear_shader_cache(int(games[index]["id"]))
        self.toast(tr("Shader cache: usunięto {count} katalogów.", count=removed))
        QMessageBox.information(
            self,
            tr("Shader cache"),
            tr(
                "Usunięto {count} katalogów cache.\n"
                "Następne uruchomienie skompiluje shadery od nowa.",
                count=removed,
            ),
        )

    def _about(self) -> None:
        QMessageBox.about(
            self,
            tr("O {app}", app=APP_NAME),
            tr(
                "<h2 style='color:#00E5FF'>{app} {version}</h2>"
                "<p>Minimalistyczny launcher standalone i wrapper Wine/Proton.</p>"
                "<p><b>Runtime:</b> Python stdlib + PyQt6<br>"
                "<b>Dane:</b> SQLite3<br>"
                "<b>Łańcuch:</b> GameMode → MangoHud → Gamescope → Wine → Gra</p>"
                "<p style='color:#71858F'>Po starcie gry Boostlayer minimalizuje "
                "się do paska zadań i pozostaje w pamięci. Ctrl+Alt+S przywraca "
                "lub chowa okno.</p>",
                app=APP_NAME,
                version=APP_VERSION,
            ),
        )

    # ------------------------------------------------------------------ window
    def _restore_geometry(self) -> None:
        encoded = self.db.get_setting("window_geometry")
        restored = False
        if encoded:
            try:
                restored = self.restoreGeometry(
                    QByteArray.fromBase64(encoded.encode("ascii"))
                )
            except Exception:
                restored = False
        if not restored:
            self.resize(1320, 830)

    def _save_geometry(self) -> None:
        try:
            encoded = bytes(self.saveGeometry().toBase64()).decode("ascii")
            self.db.set_setting("window_geometry", encoded)
        except Exception:
            pass

    def quit_app(self) -> None:
        if (
            self._steam_pending is not None
            or (
                self._steam_options_worker is not None
                and self._steam_options_worker.isRunning()
            )
        ):
            QMessageBox.information(
                self,
                tr("Steam"),
                tr("Trwa operacja na konfiguracji Steam. Poczekaj na jej zakończenie."),
            )
            return
        if self._active_process is not None:
            answer = QMessageBox.question(
                self,
                tr("Zakończ Boostlayer"),
                tr("Gra nadal działa. Zakończyć proces gry i zamknąć launcher?"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            self._active_process.terminate()
            if not self._active_process.waitForFinished(1600):
                self._active_process.kill()
        self._force_quit = True
        self._save_geometry()
        self.close()
        QApplication.quit()

    def closeEvent(self, event) -> None:  # noqa: N802
        self._save_geometry()
        if (
            self._steam_pending is not None
            or (
                self._steam_options_worker is not None
                and self._steam_options_worker.isRunning()
            )
        ):
            QMessageBox.information(
                self,
                tr("Steam"),
                tr("Trwa operacja na konfiguracji Steam. Poczekaj na jej zakończenie."),
            )
            event.ignore()
            return
        if self._force_quit:
            event.accept()
            return
        if self._active_process is not None:
            if self.tray is not None:
                self.hide()
                self.tray.showMessage(
                    APP_NAME,
                    tr("Gra działa. Launcher pozostaje w tray."),
                    QSystemTrayIcon.MessageIcon.Information,
                    2500,
                )
            else:
                QMessageBox.information(
                    self,
                    tr("Gra działa"),
                    tr("Zakończ grę przed zamknięciem launchera."),
                )
            event.ignore()
            return
        if self.db.get_bool("close_to_tray", True) and self.tray is not None:
            self.hide()
            self.tray.showMessage(
                APP_NAME,
                tr("Boostlayer działa w tray."),
                QSystemTrayIcon.MessageIcon.Information,
                2200,
            )
            event.ignore()
            return
        event.accept()
        QApplication.quit()


def steam_exec_cli(argv: list[str]) -> int:
    """CLI used by the generated Steam launch-options wrapper.

    Syntax: boostlayer --steam-exec APPID -- <original %command% argv...>
    The original command is executed unchanged if no matching library entry
    exists, so a stale wrapper can never prevent a game from starting.
    """
    try:
        marker = argv.index("--steam-exec")
        appid = argv[marker + 1].strip() if marker + 1 < len(argv) else ""
        separator = argv.index("--", marker + 2)
        command = argv[separator + 1 :]
    except (ValueError, IndexError):
        print(
            "usage: boostlayer --steam-exec APPID -- COMMAND [ARG...]",
            file=sys.stderr,
        )
        return 64
    if not command:
        print("Boostlayer: empty Steam command.", file=sys.stderr)
        return 64

    database: Database | None = None
    try:
        database = Database()
        game = database.find_steam_game(appid) if appid else None
        if not game:
            database.close()
            database = None
            os.execvp(command[0], command)
        runtime = write_runtime_file(
            database,
            game,
            command,
            direct=True,
            use_prefix=False,
        )
        launcher = ensure_launcher()
        database.close()
        database = None
        os.execv("/bin/sh", ["/bin/sh", str(launcher), str(runtime)])
    except Exception as exc:
        log.error("Steam wrapper failed: %s", exc)
        if database is not None:
            database.close()
        # Last-resort compatibility: run the game without Boostlayer options.
        try:
            os.execvp(command[0], command)
        except OSError:
            print(f"Boostlayer: cannot execute {command[0]}: {exc}", file=sys.stderr)
            return 127
    return 0


def main() -> int:
    if "--steam-exec" in sys.argv:
        return steam_exec_cli(sys.argv)
    if "--version" in sys.argv:
        print(f"{APP_NAME} {APP_VERSION}")
        return 0
    try:
        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )
    except Exception:
        pass
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setApplicationName("boostlayer")
    app.setApplicationDisplayName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName("Boostlayer")
    app.setDesktopFileName("boostlayer")
    app.setQuitOnLastWindowClosed(False)

    database = Database()
    set_language(database.get_setting("language", DEFAULT_LANGUAGE))
    set_theme(database.get_setting("theme", DEFAULT_THEME))
    app.setWindowIcon(app_icon())
    app.setStyleSheet(build_qss(QSS))
    app.aboutToQuit.connect(database.close)

    def exception_hook(exc_type, exc_value, exc_tb):
        text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        log.error("Unhandled exception:\n%s", text)
        try:
            QMessageBox.critical(
                None,
                tr("Boostlayer — błąd"),
                tr(
                    "Wystąpił nieoczekiwany błąd:\n\n{error}\n\nSzczegóły: {path}",
                    error=exc_value,
                    path=LOG_PATH,
                ),
            )
        except Exception:
            pass
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = exception_hook
    window = MainWindow(database)
    app.aboutToQuit.connect(window.shutdown_hotkey)
    window.show()
    window._refresh_tray_menu()
    if "--console" in sys.argv:
        QTimer.singleShot(0, window.open_console)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
