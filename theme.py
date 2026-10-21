"""Boostlayer colour themes and stylesheet token replacement.

The original QSS was written around the Cyber Cyan palette.  We keep that
stylesheet as the structural source and replace its colour literals with the
active theme, then append a few component overrides for elements that need a
stronger accent.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Theme:
    key: str
    name: str
    background: str
    background_dark: str
    panel: str
    panel_alt: str
    border: str
    accent: str
    accent_soft: str
    accent_dim: str
    accent2: str
    danger: str
    success: str
    text: str
    muted: str


THEMES: dict[str, Theme] = {
    "cyber": Theme(
        "cyber", "Cyber Cyan", "#0E1013", "#0A0C0E", "#101418", "#14191E",
        "#2A343D", "#00E5FF", "#00C8E0", "#00A7BA", "#2FD6E8",
        "#FF335F", "#42F5A7", "#DCEBF1", "#69808B",
    ),
    "crimson": Theme(
        "crimson", "Crimson", "#130E11", "#0D090B", "#1A1115", "#211318",
        "#452832", "#FF335F", "#E32A54", "#B92341", "#FF7890",
        "#FF335F", "#42F5A7", "#F2E6EA", "#95717D",
    ),
    "amber": Theme(
        "amber", "Amber", "#13100B", "#0D0A07", "#1B1610", "#231B12",
        "#4A3822", "#FFB347", "#E89A31", "#C77A22", "#FFD166",
        "#FF5C5C", "#8FE388", "#F5EEE2", "#9A866B",
    ),
    "emerald": Theme(
        "emerald", "Emerald", "#0B1310", "#070D0B", "#101B17", "#14231D",
        "#28483C", "#42F5A7", "#2ED38E", "#20A971", "#7CFFD0",
        "#FF5C7A", "#42F5A7", "#E3F7EE", "#6F9384",
    ),
    "violet": Theme(
        "violet", "Violet", "#100E16", "#0A080F", "#17131F", "#1E182A",
        "#3E3158", "#B388FF", "#9A6EF0", "#7D54CF", "#D6BBFF",
        "#FF4D8D", "#42F5A7", "#EEE9F8", "#837695",
    ),
    "graphite": Theme(
        "graphite", "Graphite", "#101214", "#090B0C", "#171A1D", "#1E2226",
        "#3A4248", "#9AA8B0", "#7E8D96", "#65737C", "#C0CCD2",
        "#D66A72", "#8BC9A9", "#E4EAED", "#78858D",
    ),
}

DEFAULT_THEME = "cyber"
_ACTIVE = THEMES[DEFAULT_THEME]


def set_theme(key: str) -> Theme:
    global _ACTIVE
    _ACTIVE = THEMES.get((key or "").lower(), THEMES[DEFAULT_THEME])
    return _ACTIVE


def get_theme() -> Theme:
    return _ACTIVE


_COLOR_MAP = {
    "#0E1013": "background",
    "#0A0C0E": "background_dark",
    "#0D1115": "panel",
    "#0E1114": "panel",
    "#101418": "panel",
    "#11171C": "panel",
    "#12171B": "panel",
    "#12181D": "panel_alt",
    "#14191E": "panel_alt",
    "#1D242B": "panel_alt",
    "#20262D": "border",
    "#252B32": "border",
    "#252D35": "border",
    "#242D35": "border",
    "#26323A": "border",
    "#2A343D": "border",
    "#00E5FF": "accent",
    "#00C8E0": "accent_soft",
    "#00A7BA": "accent_dim",
    "#00B8CC": "accent_soft",
    "#00B8FF": "accent",
    "#FF335F": "danger",
    "#FF4D6D": "danger",
    "#C4213E": "danger",
    "#B92341": "danger",
    "#FFB347": "accent2",
    "#42F5A7": "success",
    "#DCEBF1": "text",
    "#E6FAFF": "text",
    "#E9FAFF": "text",
    "#69808B": "muted",
    "#5D707C": "muted",
    "#71858F": "muted",
    "#8FA3AE": "muted",
    "#98AAB5": "muted",
    "#7B8D98": "muted",
}


def build_qss(base: str) -> str:
    theme = get_theme()
    pattern = re.compile(
        "|".join(re.escape(token) for token in sorted(_COLOR_MAP, key=len, reverse=True)),
        re.IGNORECASE,
    )
    result = pattern.sub(
        lambda match: getattr(theme, _COLOR_MAP[match.group(0).upper()]),
        base,
    )
    result += f"""
QWidget#Root {{
    background: {theme.background};
    border: 1px solid {theme.border};
}}
QFrame#TitleBar {{
    background: {theme.background_dark};
    border-bottom: 1px solid {theme.border};
}}
QLabel#BrandMark, QLabel#Accent, QLabel#PageKicker, QLabel#SectionTitle {{
    color: {theme.accent};
}}
QPushButton#PrimaryButton {{
    background: {theme.accent};
    color: {theme.background_dark};
    border: 1px solid {theme.accent};
}}
QPushButton#PrimaryButton:hover {{
    background: {theme.accent_soft};
    border-color: {theme.accent_soft};
}}
QPushButton#DangerButton {{
    color: {theme.danger};
    border-color: {theme.danger};
}}
QPushButton#DangerButton:hover {{
    background: {theme.danger};
    color: {theme.background_dark};
}}
QProgressBar::chunk {{
    background: {theme.accent};
}}
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
    background: {theme.border};
}}
QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {{
    background: {theme.accent_dim};
}}
QWidget#ConsoleRoot {{
    background: {theme.background};
}}
QFrame#ConsoleHeader {{
    background: {theme.background_dark};
    border: 1px solid {theme.border};
    border-radius: 8px;
}}
QLabel#ConsoleBrand {{
    color: {theme.accent};
    font-family: "DejaVu Sans Mono", monospace;
    font-size: 12pt;
    font-weight: 800;
    letter-spacing: 3px;
}}
QLabel#ConsoleMuted, QLabel#ConsoleFooter {{
    color: {theme.muted};
    font-family: "DejaVu Sans Mono", monospace;
}}
QLabel#ConsoleTitle {{
    color: {theme.text};
    font-size: 19pt;
    font-weight: 800;
}}
QLabel#ConsoleCover {{
    background: {theme.panel};
    border: 1px solid {theme.border};
    border-radius: 8px;
}}
QListWidget#ConsoleTiles {{
    background: transparent;
    border: 0;
    outline: none;
    padding: 4px;
}}
QListWidget#ConsoleTiles::item {{
    color: {theme.text};
    background: {theme.panel};
    border: 1px solid {theme.border};
    border-radius: 9px;
    padding: 7px;
    margin: 4px;
}}
QListWidget#ConsoleTiles::item:selected {{
    color: {theme.text};
    background: {theme.panel_alt};
    border: 2px solid {theme.accent};
}}
QFrame#ConsoleDetails {{
    background: {theme.panel};
    border: 1px solid {theme.border};
    border-radius: 10px;
}}
QPushButton#ConsolePrimary {{
    background: {theme.accent};
    color: {theme.background_dark};
    border: 1px solid {theme.accent};
    border-radius: 7px;
    padding: 12px;
    font-weight: 800;
}}
QPushButton#ConsolePrimary:hover {{
    background: {theme.accent_soft};
}}
QPushButton#ConsoleGhost {{
    background: transparent;
    color: {theme.muted};
    border: 1px solid {theme.border};
    border-radius: 7px;
    padding: 8px 12px;
}}
QPushButton#ConsoleGhost:hover {{
    color: {theme.text};
    border-color: {theme.accent};
}}
"""
    return result


def build_tray_qss(base: str) -> str:
    return build_qss(base)
