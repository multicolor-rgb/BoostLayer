"""Boostlayer colour themes and stylesheet token replacement.

The interface follows the visual language of modern game launchers: flat dark
surfaces, a neutral typographic scale and a single accent colour used sparingly.
Stylesheets are written with ``${token}`` placeholders which are resolved from
the active :class:`Theme` by :func:`build_qss`.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Theme:
    key: str
    name: str
    background: str
    background_dark: str
    surface: str
    surface_alt: str
    surface_hover: str
    border: str
    border_strong: str
    accent: str
    accent_hover: str
    accent_dim: str
    accent_soft: str
    accent_soft_strong: str
    on_accent: str
    text: str
    muted: str
    dim: str
    danger: str
    danger_soft: str
    success: str
    success_soft: str
    warning: str

    # -- compatibility aliases used by older widgets ---------------------
    @property
    def panel(self) -> str:
        return self.surface

    @property
    def panel_alt(self) -> str:
        return self.surface_alt

    @property
    def accent_soft_color(self) -> str:
        return self.accent_soft

    @property
    def accent2(self) -> str:
        return self.warning

    @property
    def text_muted(self) -> str:
        return self.muted


THEMES: dict[str, Theme] = {
    "epic": Theme(
        key="epic",
        name="Epic Dark",
        background="#121212",
        background_dark="#0A0A0B",
        surface="#1A1A1C",
        surface_alt="#212124",
        surface_hover="#26262A",
        border="#2C2C30",
        border_strong="#3A3A40",
        accent="#0F8BFF",
        accent_hover="#3BA1FF",
        accent_dim="#0B6AC4",
        accent_soft="rgba(15, 139, 255, 0.16)",
        accent_soft_strong="rgba(15, 139, 255, 0.28)",
        on_accent="#FFFFFF",
        text="#F2F2F3",
        muted="#9A9AA0",
        dim="#6E6E75",
        danger="#F2555A",
        danger_soft="rgba(242, 85, 90, 0.16)",
        success="#4ADE80",
        success_soft="rgba(74, 222, 128, 0.16)",
        warning="#F5A623",
    ),
    "heroic": Theme(
        key="heroic",
        name="Heroic Violet",
        background="#0F0F13",
        background_dark="#09090C",
        surface="#17171C",
        surface_alt="#1E1E25",
        surface_hover="#24242C",
        border="#2A2A33",
        border_strong="#383842",
        accent="#A26BF7",
        accent_hover="#B98CFF",
        accent_dim="#7C4FD6",
        accent_soft="rgba(162, 107, 247, 0.16)",
        accent_soft_strong="rgba(162, 107, 247, 0.30)",
        on_accent="#FFFFFF",
        text="#F3F1F7",
        muted="#98939F",
        dim="#6B6675",
        danger="#F2555A",
        danger_soft="rgba(242, 85, 90, 0.16)",
        success="#4ADE80",
        success_soft="rgba(74, 222, 128, 0.16)",
        warning="#F5A623",
    ),
    "ember": Theme(
        key="ember",
        name="Ember",
        background="#141210",
        background_dark="#0B0908",
        surface="#1C1917",
        surface_alt="#24201D",
        surface_hover="#2B2622",
        border="#332C27",
        border_strong="#453B34",
        accent="#FF7A45",
        accent_hover="#FF9668",
        accent_dim="#CC5D31",
        accent_soft="rgba(255, 122, 69, 0.16)",
        accent_soft_strong="rgba(255, 122, 69, 0.30)",
        on_accent="#1A0D07",
        text="#F5F0EC",
        muted="#A2968C",
        dim="#746A62",
        danger="#F2555A",
        danger_soft="rgba(242, 85, 90, 0.16)",
        success="#4ADE80",
        success_soft="rgba(74, 222, 128, 0.16)",
        warning="#F5A623",
    ),
}

DEFAULT_THEME = "epic"
_ACTIVE = THEMES[DEFAULT_THEME]


def set_theme(key: str) -> Theme:
    global _ACTIVE
    _ACTIVE = THEMES.get((key or "").lower(), THEMES[DEFAULT_THEME])
    return _ACTIVE


def get_theme() -> Theme:
    return _ACTIVE


def _icon_dir() -> Path:
    candidates = [
        Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)),
        Path(__file__).resolve().parent,
    ]
    for base in candidates:
        folder = base / "assets" / "ui"
        if folder.is_dir():
            return folder
    return candidates[0] / "assets" / "ui"


def theme_tokens(theme: Theme | None = None) -> dict[str, str]:
    """Return the style token table for *theme* (active theme by default)."""
    theme = theme or get_theme()
    icons = _icon_dir()
    tokens = {
        "bg": theme.background,
        "bg_dark": theme.background_dark,
        "surface": theme.surface,
        "surface_alt": theme.surface_alt,
        "surface_hover": theme.surface_hover,
        "border": theme.border,
        "border_strong": theme.border_strong,
        "accent": theme.accent,
        "accent_hover": theme.accent_hover,
        "accent_dim": theme.accent_dim,
        "accent_soft": theme.accent_soft,
        "accent_soft_strong": theme.accent_soft_strong,
        "on_accent": theme.on_accent,
        "text": theme.text,
        "muted": theme.muted,
        "dim": theme.dim,
        "danger": theme.danger,
        "danger_soft": theme.danger_soft,
        "success": theme.success,
        "success_soft": theme.success_soft,
        "warning": theme.warning,
        "icon_check": str(icons / "check.svg"),
        "icon_chevron_down": str(icons / "chevron-down.svg"),
        "icon_chevron_up": str(icons / "chevron-up.svg"),
        "radius": "8px",
        "radius_lg": "12px",
        "radius_xl": "16px",
    }
    return tokens


_TOKEN_RE = re.compile(r"\$\{(\w+)\}")


def _resolve(base: str, theme: Theme) -> str:
    tokens = theme_tokens(theme)
    return _TOKEN_RE.sub(
        lambda match: tokens.get(match.group(1), match.group(0)),
        base,
    )


CONSOLE_QSS = """
QWidget#ConsoleRoot {
    background: transparent;
}
QWidget#ConsoleHeroArea, QWidget#ConsoleHeroContent {
    background: transparent;
}
QLabel#ConsoleBrand {
    color: ${text};
    font-size: 14pt;
    font-weight: 800;
}
QLabel#ConsoleKicker {
    color: ${accent};
    font-size: 8.5pt;
    font-weight: 700;
    letter-spacing: 1.6px;
}
QLabel#ConsoleClock {
    color: ${text};
    font-size: 13pt;
    font-weight: 700;
    padding: 0 12px;
}
QLabel#ConsolePad {
    color: ${muted};
    background: rgba(20, 20, 24, 0.7);
    border: 1px solid ${border};
    border-radius: 10px;
    padding: 6px 12px;
    font-size: 8.5pt;
}
QLabel#ConsolePad[available="true"] {
    color: ${success};
    border-color: ${success};
}
QLabel#ConsoleMuted {
    color: ${muted};
    font-size: 11pt;
}
QLabel#ConsoleTitle {
    color: #FFFFFF;
    font-size: 40pt;
    font-weight: 800;
    letter-spacing: -0.5px;
}
QLabel#ConsoleCover {
    background: ${surface};
    border: 1px solid rgba(255, 255, 255, 0.10);
    border-radius: 18px;
}
QListWidget#ConsoleTiles {
    background: transparent;
    border: 0;
    outline: none;
}
QListWidget#ConsoleTiles::item {
    background: transparent;
    border: 0;
    padding: 0;
    margin: 0;
}
QLabel#ConsoleChip {
    color: ${text};
    background: rgba(255, 255, 255, 0.07);
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 9px;
    padding: 6px 12px;
    font-size: 9.5pt;
    font-weight: 600;
}
QFrame#ConsoleFooterBar {
    background: rgba(10, 10, 12, 0.72);
    border: 1px solid ${border};
    border-radius: 12px;
}
QLabel#ConsoleKey {
    color: ${on_accent};
    background: ${accent};
    border-radius: 6px;
    padding: 3px 9px;
    font-size: 9pt;
    font-weight: 800;
}
QLabel#ConsoleKeyLabel {
    color: ${muted};
    font-size: 9.5pt;
}
QPushButton#ConsolePrimary {
    background: ${accent};
    color: ${on_accent};
    border: 1px solid ${accent};
    border-radius: 12px;
    padding: 15px 34px;
    font-size: 13pt;
    font-weight: 800;
}
QPushButton#ConsolePrimary:hover {
    background: ${accent_hover};
    border-color: ${accent_hover};
}
QPushButton#ConsoleGhost {
    background: rgba(20, 20, 24, 0.6);
    color: ${text};
    border: 1px solid rgba(255, 255, 255, 0.18);
    border-radius: 12px;
    padding: 14px 24px;
    font-size: 11pt;
    font-weight: 700;
}
QPushButton#ConsoleGhost:hover {
    border-color: ${accent};
    color: ${accent};
}
"""


def build_qss(base: str) -> str:
    return _resolve(base, get_theme()) + _resolve(CONSOLE_QSS, get_theme())


def build_tray_qss(base: str) -> str:
    return build_qss(base)
