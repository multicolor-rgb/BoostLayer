"""Reusable PyQt6 widgets for storefront integrations."""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Iterable

from PyQt6.QtCore import QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
    QApplication,
)

import db
import stores
from core import app_icon, human_bytes
from i18n import tr


class InstallDirDialog(QDialog):
    """Ask for the exact game install directory before a store download."""

    def __init__(
        self,
        store_label: str,
        game_title: str,
        default_path: str | Path,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._store_label = store_label
        self._game_title = game_title
        self.setWindowTitle(
            tr("Katalog instalacji — {game}", game=game_title)
        )
        self.setWindowIcon(app_icon())
        self.setModal(True)
        self.resize(680, 240)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 18, 20, 18)
        outer.setSpacing(10)
        heading = QLabel(
            tr("Gdzie zainstalować „{game}”?", game=game_title)
        )
        heading.setObjectName("SectionTitle")
        outer.addWidget(heading)
        note = QLabel(
            tr(
                "Wybierz dokładny katalog, w którym mają znaleźć się pliki gry. "
                "Katalog zostanie utworzony, jeśli nie istnieje."
            )
        )
        note.setObjectName("Muted")
        note.setWordWrap(True)
        outer.addWidget(note)

        row = QHBoxLayout()
        self.path_edit = QLineEdit(str(default_path))
        row.addWidget(self.path_edit, 1)
        browse = QPushButton("...")
        browse.setObjectName("GhostButton")
        browse.setFixedWidth(42)
        browse.clicked.connect(self._browse)
        row.addWidget(browse)
        outer.addLayout(row)

        self.free_label = QLabel("")
        self.free_label.setObjectName("Muted")
        outer.addWidget(self.free_label)
        self.remember_cb = QCheckBox(
            tr("Zapamiętaj katalog bazowy dla sklepu {store}", store=store_label)
        )
        outer.addWidget(self.remember_cb)
        outer.addStretch(1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        cancel = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        if ok:
            ok.setText(tr("Zainstaluj tutaj"))
            ok.setObjectName("PrimaryButton")
        if cancel:
            cancel.setText(tr("Anuluj"))
            cancel.setObjectName("GhostButton")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)
        self.path_edit.textChanged.connect(self._update_free_space)
        self._update_free_space()

    def _browse(self) -> None:
        initial = self.path_edit.text().strip() or str(Path.home())
        folder = QFileDialog.getExistingDirectory(
            self, tr("Katalog instalacji gry"), initial
        )
        if folder:
            self.path_edit.setText(folder)

    def _update_free_space(self) -> None:
        raw = self.path_edit.text().strip()
        if not raw:
            self.free_label.setText("")
            return
        path = Path(raw).expanduser()
        probe = path
        while not probe.exists() and probe.parent != probe:
            probe = probe.parent
        try:
            usage = shutil.disk_usage(probe)
        except OSError:
            self.free_label.setText("")
            return
        self.free_label.setText(
            tr("Wolne miejsce: {size}", size=human_bytes(usage.free))
        )

    def _accept(self) -> None:
        raw = self.path_edit.text().strip()
        if not raw:
            QMessageBox.warning(
                self, tr("Katalog instalacji"), tr("Podaj ścieżkę katalogu.")
            )
            return
        path = Path(raw).expanduser()
        if not path.is_absolute():
            QMessageBox.warning(
                self,
                tr("Katalog instalacji"),
                tr("Podaj ścieżkę bezwzględną."),
            )
            return
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path
        if resolved == Path("/") or resolved == Path.home().resolve():
            QMessageBox.warning(
                self,
                tr("Katalog instalacji"),
                tr("Nie można instalować gry bezpośrednio w tym katalogu."),
            )
            return
        if resolved.exists() and any(resolved.iterdir()):
            answer = QMessageBox.question(
                self,
                tr("Katalog nie jest pusty"),
                tr(
                    "Katalog istnieje i nie jest pusty:\n{path}\n\n"
                    "Kontynuować? Pliki gry mogą zostać nadpisane.",
                    path=resolved,
                ),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.accept()

    def selected_path(self) -> str:
        return str(Path(self.path_edit.text().strip()).expanduser())

    def remember_base(self) -> str:
        if not self.remember_cb.isChecked():
            return ""
        return str(Path(self.path_edit.text().strip()).expanduser().parent)


class StoreProgressDialog(QDialog):
    cancelled = pyqtSignal()

    def __init__(self, title: str, parent=None) -> None:
        super().__init__(parent)
        self._running = True
        self.setWindowTitle(title)
        self.setWindowIcon(app_icon())
        self.setModal(True)
        self.resize(760, 420)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 16)
        outer.setSpacing(10)
        self.heading = QLabel(title)
        self.heading.setObjectName("SectionTitle")
        outer.addWidget(self.heading)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        outer.addWidget(self.progress_bar)
        self.meta_label = QLabel("")
        self.meta_label.setObjectName("Muted")
        self.meta_label.setWordWrap(True)
        outer.addWidget(self.meta_label)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(500)
        outer.addWidget(self.log_view, 1)
        self.cancel_button = QPushButton(tr("Anuluj"))
        self.cancel_button.setObjectName("GhostButton")
        self.cancel_button.clicked.connect(self._cancel_clicked)
        outer.addWidget(self.cancel_button, 0, Qt.AlignmentFlag.AlignRight)

    def set_status(self, text: str) -> None:
        self.meta_label.setText(text)

    def append_log(self, line: str) -> None:
        self.log_view.appendPlainText(line)

    def set_progress(self, data: object) -> None:
        values = data if isinstance(data, dict) else {}
        percent = values.get("percent")
        if isinstance(percent, (int, float)):
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(int(percent))
        parts: list[str] = []
        if values.get("eta"):
            parts.append(tr("ETA: {eta}", eta=values["eta"]))
        if values.get("downloaded"):
            parts.append(tr("Pobrano: {value}", value=values["downloaded"]))
        if values.get("download_speed"):
            parts.append(tr("Sieć: {value}/s", value=values["download_speed"]))
        if values.get("disk_speed"):
            parts.append(tr("Dysk: {value}/s", value=values["disk_speed"]))
        if parts:
            self.meta_label.setText("  //  ".join(parts))

    def set_running(self, running: bool) -> None:
        self._running = running
        self.cancel_button.setText(tr("Anuluj") if running else tr("Zamknij"))
        self.cancel_button.setEnabled(True)

    def _cancel_clicked(self) -> None:
        if self._running:
            self.cancelled.emit()
            self.cancel_button.setEnabled(False)
            self.cancel_button.setText(tr("Anulowanie..."))
        else:
            self.accept()

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._running:
            self._cancel_clicked()
            event.ignore()
            return
        super().closeEvent(event)

    def reject(self) -> None:
        if self._running:
            self._cancel_clicked()
            return
        super().reject()


class StoreLoginDialog(QDialog):
    """Generic browser/paste login flow for storefront adapters."""

    def __init__(self, adapter, database: db.Database, parent=None) -> None:
        super().__init__(parent)
        self.adapter = adapter
        self.db = database
        self.user: dict[str, str] = {}
        self._payload: dict[str, Any] = {}
        self._begin_worker: stores.StoreBeginLoginWorker | None = None
        self._finish_worker: stores.StoreFinishLoginWorker | None = None
        self._binary = adapter.tool_binary(database)
        if self._binary is None:
            raise stores.StoreError(
                tr("Nie znaleziono narzędzia {store}.", store=adapter.label)
            )

        self.setWindowTitle(tr("Logowanie {store}", store=adapter.label))
        self.setWindowIcon(app_icon())
        self.setModal(True)
        self.resize(700, 380)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(22, 18, 22, 18)
        outer.setSpacing(12)
        kicker = QLabel(tr("{store} // KONTO", store=adapter.label))
        kicker.setObjectName("PageKicker")
        outer.addWidget(kicker)
        heading = QLabel(tr("Podłącz konto {store}", store=adapter.label))
        heading.setObjectName("PageTitle")
        outer.addWidget(heading)
        help_text = adapter.login_help or tr(
            "Zaloguj się w przeglądarce i wklej adres przekierowania."
        )
        info = QLabel(help_text)
        info.setObjectName("Muted")
        info.setWordWrap(True)
        outer.addWidget(info)

        url_row = QHBoxLayout()
        self.url_edit = QLineEdit()
        self.url_edit.setReadOnly(True)
        self.url_edit.setPlaceholderText(tr("Przygotowuję adres logowania..."))
        url_row.addWidget(self.url_edit, 1)
        self.open_button = QPushButton(tr("Otwórz stronę logowania"))
        self.open_button.setObjectName("GhostButton")
        self.open_button.setEnabled(False)
        self.open_button.clicked.connect(self._open_url)
        url_row.addWidget(self.open_button)
        outer.addLayout(url_row)

        self.redirect_edit = QLineEdit()
        self.redirect_edit.setPlaceholderText(
            tr("Wklej tutaj URL przekierowania lub kod autoryzacji")
        )
        self.redirect_edit.setEnabled(False)
        outer.addWidget(self.redirect_edit)
        self.status_label = QLabel(tr("Przygotowuję logowanie..."))
        self.status_label.setObjectName("Muted")
        self.status_label.setWordWrap(True)
        outer.addWidget(self.status_label)
        outer.addStretch(1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        self.ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        cancel_button = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        if self.ok_button:
            self.ok_button.setText(tr("Zaloguj"))
            self.ok_button.setObjectName("PrimaryButton")
            self.ok_button.setEnabled(False)
        if cancel_button:
            cancel_button.setText(tr("Anuluj"))
            cancel_button.setObjectName("GhostButton")
        buttons.accepted.connect(self._submit)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

        self._begin_worker = stores.StoreBeginLoginWorker(
            adapter, str(self._binary), self
        )
        self._begin_worker.result.connect(self._begin_ready)
        self._begin_worker.start()

    def _begin_ready(self, payload: object) -> None:
        data = payload if isinstance(payload, dict) else {}
        worker = self._begin_worker
        self._begin_worker = None
        if worker is not None:
            worker.deleteLater()
        if not data.get("ok"):
            self.status_label.setText(
                str(data.get("error", tr("Logowanie nie powiodło się.")))
            )
            return
        self._payload = data.get("data") or {}
        url = str(self._payload.get("url", "") or "")
        self.url_edit.setText(url)
        self.open_button.setEnabled(bool(url))
        self.redirect_edit.setEnabled(True)
        if self.ok_button:
            self.ok_button.setEnabled(True)
        self.status_label.setText(
            tr("Zaloguj się w przeglądarce, a następnie wklej URL przekierowania.")
        )
        if url:
            from PyQt6.QtGui import QDesktopServices
            from PyQt6.QtCore import QUrl

            QDesktopServices.openUrl(QUrl(url))

    def _open_url(self) -> None:
        url = self.url_edit.text().strip()
        if not url:
            return
        from PyQt6.QtGui import QDesktopServices
        from PyQt6.QtCore import QUrl

        QDesktopServices.openUrl(QUrl(url))

    def _submit(self) -> None:
        if self._finish_worker is not None:
            return
        pasted = self.redirect_edit.text().strip()
        if not pasted:
            QMessageBox.warning(
                self,
                self.adapter.label,
                tr("Wklej URL przekierowania lub kod autoryzacji."),
            )
            return
        if self.ok_button:
            self.ok_button.setEnabled(False)
        self.redirect_edit.setEnabled(False)
        self.open_button.setEnabled(False)
        self.status_label.setText(tr("Rejestruję konto..."))
        self._finish_worker = stores.StoreFinishLoginWorker(
            self.adapter, str(self._binary), self._payload, pasted, self
        )
        self._finish_worker.result.connect(self._finish_ready)
        self._finish_worker.start()

    def _finish_ready(self, payload: object) -> None:
        data = payload if isinstance(payload, dict) else {}
        worker = self._finish_worker
        self._finish_worker = None
        if worker is not None:
            worker.deleteLater()
        if not data.get("ok"):
            self.status_label.setText(
                str(data.get("error", tr("Logowanie nie powiodło się.")))
            )
            self.redirect_edit.setEnabled(True)
            self.open_button.setEnabled(True)
            if self.ok_button:
                self.ok_button.setEnabled(True)
            return
        user = data.get("user") or {}
        self.user = {
            "name": str(user.get("name", "") or ""),
            "user_id": str(user.get("user_id", "") or ""),
        }
        self.accept()

    def reject(self) -> None:
        if self._finish_worker is not None:
            self.status_label.setText(tr("Trwa logowanie. Poczekaj..."))
            return
        if self._begin_worker is not None:
            if not self._begin_worker.wait(4000):
                self.status_label.setText(tr("Przygotowuję logowanie..."))
                return
            self._begin_worker = None
        super().reject()


class StorePage(QWidget):
    sync_requested = pyqtSignal(str)
    login_requested = pyqtSignal(str)
    logout_requested = pyqtSignal(str)
    install_requested = pyqtSignal(str, str)
    launch_requested = pyqtSignal(str, str)
    uninstall_requested = pyqtSignal(str, str)
    update_requested = pyqtSignal(str, str)
    verify_requested = pyqtSignal(str, str)
    open_folder_requested = pyqtSignal(str, str)
    locate_requested = pyqtSignal(str, str)
    settings_requested = pyqtSignal(str)
    cover_updated = pyqtSignal(str, str, str)
    toast = pyqtSignal(str)

    def __init__(self, database: db.Database, adapter, parent=None) -> None:
        super().__init__(parent)
        self.db = database
        self.adapter = adapter
        self.store = adapter.id
        self._games: list[dict[str, Any]] = []
        self._selected_id = ""
        self._cover_worker: stores.StoreCoverWorker | None = None
        self._updates: set[str] = set()
        self._account_name = ""
        self._logged_in = False
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(220)
        self._search_timer.timeout.connect(self.reload)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 18, 20, 16)
        outer.setSpacing(12)
        header = QHBoxLayout()
        heading_box = QVBoxLayout()
        heading_box.setSpacing(2)
        kicker = QLabel(tr("{store}", store=adapter.label))
        kicker.setObjectName("PageKicker")
        heading_box.addWidget(kicker)
        heading = QLabel(tr("Biblioteka {store}", store=adapter.label))
        heading.setObjectName("PageTitle")
        heading_box.addWidget(heading)
        header.addLayout(heading_box)
        header.addStretch(1)
        self.stats_label = QLabel(tr("0 gier  ·  0 zainstalowanych"))
        self.stats_label.setObjectName("StatsPill")
        header.addWidget(self.stats_label)
        self.account_button = QPushButton(tr("Zaloguj się"))
        self.account_button.setObjectName("GhostButton")
        self.account_button.clicked.connect(self._account_clicked)
        header.addWidget(self.account_button)
        settings_button = QPushButton(tr("Ustawienia {store}", store=adapter.label))
        settings_button.setObjectName("GhostButton")
        settings_button.clicked.connect(lambda: self.settings_requested.emit(self.store))
        header.addWidget(settings_button)
        outer.addLayout(header)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(7)
        self.search_edit = QLineEdit()
        self.search_edit.setObjectName("Search")
        self.search_edit.setPlaceholderText(
            tr("Szukaj w bibliotece {store}...", store=adapter.label)
        )
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(lambda _text: self._search_timer.start())
        self.search_edit.hide()
        toolbar.addWidget(self.search_edit, 1)
        self.filter_combo = QComboBox()
        self.filter_combo.addItem(tr("Wszystkie gry"), None)
        self.filter_combo.addItem(tr("Zainstalowane"), 1)
        self.filter_combo.addItem(tr("Nie zainstalowane"), 0)
        self.filter_combo.currentIndexChanged.connect(self.reload)
        toolbar.addWidget(self.filter_combo)
        self.sync_button = QPushButton(tr("↻  Odśwież bibliotekę"))
        self.sync_button.setObjectName("GhostButton")
        self.sync_button.clicked.connect(lambda: self.sync_requested.emit(self.store))
        toolbar.addWidget(self.sync_button)
        outer.addLayout(toolbar)

        body = QHBoxLayout()
        body.setSpacing(14)
        self.table = QTreeWidget()
        self.table.setObjectName("StoreTable")
        self.table.setHeaderLabels([tr("Gra"), tr("Rozmiar"), tr("Status")])
        self.table.setRootIsDecorated(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.table.setIconSize(QSize(34, 46))
        self.table.setColumnWidth(0, 390)
        self.table.setColumnWidth(1, 120)
        self.table.header().setStretchLastSection(True)
        self.table.currentItemChanged.connect(self._selection_changed)
        self.table.itemDoubleClicked.connect(self._launch_item)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._context_menu)
        body.addWidget(self.table, 1)

        details = QFrame()
        details.setObjectName("Panel")
        details.setFixedWidth(360)
        details_layout = QVBoxLayout(details)
        details_layout.setContentsMargins(18, 16, 18, 16)
        details_layout.setSpacing(9)
        detail_kicker = QLabel(tr("Wybrana gra"))
        detail_kicker.setObjectName("PageKicker")
        details_layout.addWidget(detail_kicker)
        self.cover = QLabel()
        self.cover.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cover.setFixedSize(220, 300)
        self.cover.setObjectName("ConsoleCover")
        details_layout.addWidget(self.cover, 0, Qt.AlignmentFlag.AlignHCenter)
        self.title = QLabel(tr("Wybierz grę"))
        self.title.setObjectName("SectionTitle")
        self.title.setWordWrap(True)
        details_layout.addWidget(self.title)
        self.developer = QLabel("")
        self.developer.setObjectName("Muted")
        details_layout.addWidget(self.developer)
        self.status = QLabel("")
        self.status.setObjectName("Muted")
        details_layout.addWidget(self.status)
        self.size_label = QLabel("")
        self.size_label.setObjectName("Muted")
        details_layout.addWidget(self.size_label)
        self.id_label = QLabel("")
        self.id_label.setObjectName("Muted")
        self.id_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        details_layout.addWidget(self.id_label)
        self.description = QLabel("")
        self.description.setObjectName("Muted")
        self.description.setWordWrap(True)
        self.description.setMaximumHeight(110)
        details_layout.addWidget(self.description)
        details_layout.addStretch(1)
        self.install_button = QPushButton(tr("Zainstaluj"))
        self.install_button.setObjectName("PrimaryButton")
        self.install_button.clicked.connect(self._install_current)
        details_layout.addWidget(self.install_button)
        self.play_button = QPushButton(tr("▶   Graj"))
        self.play_button.setObjectName("PrimaryButton")
        self.play_button.clicked.connect(self._launch_current)
        details_layout.addWidget(self.play_button)
        maintenance = QHBoxLayout()
        self.update_button = QPushButton(tr("Aktualizuj"))
        self.update_button.setObjectName("GhostButton")
        self.update_button.clicked.connect(self._update_current)
        maintenance.addWidget(self.update_button)
        self.verify_button = QPushButton(tr("Weryfikuj"))
        self.verify_button.setObjectName("GhostButton")
        self.verify_button.clicked.connect(self._verify_current)
        maintenance.addWidget(self.verify_button)
        details_layout.addLayout(maintenance)
        self.folder_button = QPushButton(tr("Otwórz katalog gry"))
        self.folder_button.setObjectName("GhostButton")
        self.folder_button.clicked.connect(self._folder_current)
        details_layout.addWidget(self.folder_button)
        self.uninstall_button = QPushButton(tr("Odinstaluj"))
        self.uninstall_button.setObjectName("GhostButton")
        self.uninstall_button.clicked.connect(self._uninstall_current)
        details_layout.addWidget(self.uninstall_button)
        body.addWidget(details)
        outer.addLayout(body, 1)
        self.reload()

    def _filter_installed(self) -> int | None:
        value = self.filter_combo.currentData()
        return int(value) if value is not None else None

    def set_account(self, name: str, logged_in: bool) -> None:
        self._account_name = (name or "").strip()
        self._logged_in = bool(logged_in)
        if self._logged_in:
            self.account_button.setText(
                self._account_name or tr("Wyloguj")
            )
            self.account_button.setToolTip(tr("Wyloguj"))
        else:
            self.account_button.setText(tr("Zaloguj się"))
            self.account_button.setToolTip(tr("Podłącz konto"))
        self.reload()

    def set_updates(self, ids: Iterable[str]) -> None:
        self._updates = {str(item) for item in ids}
        self.reload()

    def _account_clicked(self) -> None:
        if self._logged_in:
            self.logout_requested.emit(self.store)
        else:
            self.login_requested.emit(self.store)

    def reload(self) -> None:
        search = self.search_edit.text().strip()
        self._games = self.db.list_store_library(
            self.store, search, self._filter_installed()
        )
        stats = self.db.store_library_stats(self.store)
        self.stats_label.setText(
            tr(
                "{total} gier  ·  {installed} zainstalowanych",
                total=stats["total"],
                installed=stats["installed"],
            )
        )
        current = self._selected_id
        self.table.blockSignals(True)
        self.table.clear()
        selected_item: QTreeWidgetItem | None = None
        for game in self._games:
            store_id = str(game.get("store_id", ""))
            installed = bool(game.get("installed"))
            status = tr("Zainstalowana") if installed else tr("W bibliotece")
            if installed and store_id in self._updates:
                status = tr("Aktualizacja")
            item = QTreeWidgetItem(
                [
                    str(game.get("title", "")),
                    human_bytes(int(game.get("size", 0) or 0))
                    if int(game.get("size", 0) or 0) > 0
                    else "—",
                    status,
                ]
            )
            item.setData(0, Qt.ItemDataRole.UserRole, store_id)
            cover = Path(str(game.get("cover_path", "") or "")).expanduser()
            if cover.is_file():
                icon = QIcon(str(cover))
                if not icon.isNull():
                    item.setIcon(0, icon)
            item.setToolTip(0, str(game.get("title", "")))
            item.setToolTip(2, store_id)
            self.table.addTopLevelItem(item)
            if current and store_id == current:
                selected_item = item
        self.table.blockSignals(False)
        if selected_item is not None:
            self.table.setCurrentItem(selected_item)
        elif self.table.topLevelItemCount():
            self.table.setCurrentItem(self.table.topLevelItem(0))
        else:
            self._selected_id = ""
            self.title.setText(
                tr("Brak gier w bibliotece {store}", store=self.adapter.label)
            )
            self.status.setText(
                tr(
                    "Zaloguj się do {store} i odśwież bibliotekę. "
                    "Narzędzie skonfigurujesz w Ustawieniach → Sklepy.",
                    store=self.adapter.label,
                )
            )
            self.developer.setText("")
            self.size_label.setText("")
            self.id_label.setText("")
            self.description.setText("")
            self.cover.setPixmap(app_icon(160).pixmap(160, 160))
            for button in (
                self.install_button,
                self.play_button,
                self.update_button,
                self.verify_button,
                self.folder_button,
                self.uninstall_button,
            ):
                button.hide()
        if self.table.topLevelItemCount():
            self._selection_changed(self.table.currentItem(), None)

    def _selected_game(self) -> dict[str, Any] | None:
        item = self.table.currentItem()
        if item is None:
            return None
        store_id = str(item.data(0, Qt.ItemDataRole.UserRole) or "")
        return self.db.get_store_library_game(self.store, store_id) if store_id else None

    def _selection_changed(
        self, current: QTreeWidgetItem | None, _previous: QTreeWidgetItem | None
    ) -> None:
        if current is None:
            return
        store_id = str(current.data(0, Qt.ItemDataRole.UserRole) or "")
        game = self.db.get_store_library_game(self.store, store_id)
        if game is None:
            return
        self._selected_id = store_id
        installed = bool(game.get("installed"))
        self.title.setText(str(game.get("title", "")))
        self.developer.setText(str(game.get("developer", "")))
        status = tr("Zainstalowana") if installed else tr("W bibliotece")
        if installed and store_id in self._updates:
            status = tr("Dostępna aktualizacja")
        self.status.setText(status)
        size = int(game.get("size", 0) or 0)
        self.size_label.setText(
            tr("Rozmiar: {size}", size=human_bytes(size))
            if size > 0
            else tr("Rozmiar: nieznany")
        )
        self.id_label.setText(tr("ID: {id}", id=store_id))
        self.description.setText(str(game.get("description", "") or ""))
        self.install_button.setVisible(not installed)
        self.play_button.setVisible(installed)
        self.update_button.setVisible(installed)
        self.verify_button.setVisible(installed)
        self.folder_button.setVisible(installed)
        self.uninstall_button.setVisible(installed)
        self.folder_button.setEnabled(
            bool(str(game.get("install_path", "") or "").strip())
        )
        cover = Path(str(game.get("cover_path", "") or "")).expanduser()
        if cover.is_file():
            icon = QIcon(str(cover))
            if not icon.isNull():
                self.cover.setPixmap(
                    icon.pixmap(self.cover.size()).scaled(
                        self.cover.size(),
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
                return
        self.cover.setPixmap(app_icon(160).pixmap(160, 160))
        self._load_cover(game)

    def _load_cover(self, game: dict[str, Any]) -> None:
        if self._cover_worker is not None:
            return
        if not str(game.get("cover_url", "") or "").strip():
            return
        self._cover_worker = stores.StoreCoverWorker(self.adapter, game, self)
        self._cover_worker.result.connect(self._cover_ready)
        self._cover_worker.start()

    def _cover_ready(self, store: str, store_id: str, path: str) -> None:
        worker = self._cover_worker
        self._cover_worker = None
        if worker is not None:
            worker.deleteLater()
        if path:
            self.db.set_store_cover(store, store_id, path)
            self.cover_updated.emit(store, store_id, path)
            for index in range(self.table.topLevelItemCount()):
                item = self.table.topLevelItem(index)
                if str(item.data(0, Qt.ItemDataRole.UserRole) or "") == store_id:
                    icon = QIcon(path)
                    if not icon.isNull():
                        item.setIcon(0, icon)
                    break
            if store_id == self._selected_id:
                icon = QIcon(path)
                if not icon.isNull():
                    self.cover.setPixmap(
                        icon.pixmap(self.cover.size()).scaled(
                            self.cover.size(),
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation,
                        )
                    )
        if store_id != self._selected_id and self._selected_id:
            game = self.db.get_store_library_game(self.store, self._selected_id)
            if game and not game.get("cover_path"):
                self._load_cover(game)

    def update_cover(self, store_id: str, path: str) -> None:
        if not path:
            return
        icon = QIcon(path)
        if icon.isNull():
            return
        for index in range(self.table.topLevelItemCount()):
            item = self.table.topLevelItem(index)
            if str(item.data(0, Qt.ItemDataRole.UserRole) or "") == store_id:
                item.setIcon(0, icon)
                break
        if store_id == self._selected_id:
            self.cover.setPixmap(
                icon.pixmap(self.cover.size()).scaled(
                    self.cover.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )

    def update_size(self, store_id: str, size: int) -> None:
        for index in range(self.table.topLevelItemCount()):
            item = self.table.topLevelItem(index)
            if str(item.data(0, Qt.ItemDataRole.UserRole) or "") == store_id:
                item.setText(
                    1, human_bytes(int(size or 0)) if int(size or 0) > 0 else "—"
                )
                break

    def _install_current(self) -> None:
        game = self._selected_game()
        if game is not None:
            self.install_requested.emit(self.store, str(game["store_id"]))

    def _launch_current(self) -> None:
        game = self._selected_game()
        if game is not None and game.get("installed"):
            self.launch_requested.emit(self.store, str(game["store_id"]))

    def _update_current(self) -> None:
        game = self._selected_game()
        if game is not None:
            self.update_requested.emit(self.store, str(game["store_id"]))

    def _verify_current(self) -> None:
        game = self._selected_game()
        if game is not None:
            self.verify_requested.emit(self.store, str(game["store_id"]))

    def _uninstall_current(self) -> None:
        game = self._selected_game()
        if game is not None:
            self.uninstall_requested.emit(self.store, str(game["store_id"]))

    def _folder_current(self) -> None:
        game = self._selected_game()
        if game is not None:
            self.open_folder_requested.emit(self.store, str(game["store_id"]))

    def _launch_item(self, item: QTreeWidgetItem) -> None:
        store_id = str(item.data(0, Qt.ItemDataRole.UserRole) or "")
        game = self.db.get_store_library_game(self.store, store_id) if store_id else None
        if game is None:
            return
        if game.get("installed"):
            self.launch_requested.emit(self.store, store_id)
        else:
            self.install_requested.emit(self.store, store_id)

    def _context_menu(self, position) -> None:
        item = self.table.itemAt(position)
        if item is None:
            return
        self.table.setCurrentItem(item)
        game = self._selected_game()
        if game is None:
            return
        store_id = str(game.get("store_id", ""))
        installed = bool(game.get("installed"))
        menu = QMenu(self)
        if installed:
            launch = menu.addAction(tr("▶  Uruchom grę"))
            launch.triggered.connect(
                lambda: self.launch_requested.emit(self.store, store_id)
            )
            update = menu.addAction(tr("↻  Aktualizuj"))
            update.triggered.connect(
                lambda: self.update_requested.emit(self.store, store_id)
            )
            verify = menu.addAction(tr("🛠  Weryfikuj pliki"))
            verify.triggered.connect(
                lambda: self.verify_requested.emit(self.store, store_id)
            )
            folder = menu.addAction(tr("Otwórz katalog gry"))
            folder.triggered.connect(
                lambda: self.open_folder_requested.emit(self.store, store_id)
            )
            menu.addSeparator()
            uninstall = menu.addAction(tr("×  Odinstaluj"))
            uninstall.triggered.connect(
                lambda: self.uninstall_requested.emit(self.store, store_id)
            )
        else:
            install = menu.addAction(tr("Zainstaluj"))
            install.triggered.connect(
                lambda: self.install_requested.emit(self.store, store_id)
            )
        menu.addSeparator()
        copy_id = menu.addAction(tr("⧉  Kopiuj ID"))
        copy_id.triggered.connect(lambda: QApplication.clipboard().setText(store_id))
        if self.store == "gog":
            locate = menu.addAction(tr("Wskaż folder gry"))
            locate.triggered.connect(
                lambda: self.locate_requested.emit(self.store, store_id)
            )
        menu.exec(self.table.viewport().mapToGlobal(position))

    def set_sync_busy(self, busy: bool) -> None:
        self.sync_button.setEnabled(not busy)
        self.search_edit.setEnabled(not busy)

    def focus_search(self) -> None:
        self.search_edit.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.search_edit.selectAll()

    def shutdown(self) -> None:
        if self._cover_worker is not None:
            self._cover_worker.wait(5000)
            self._cover_worker = None


class StoresPage(QWidget):
    def __init__(self, database: db.Database, steam_page: QWidget | None = None, parent=None) -> None:
        super().__init__(parent)
        self.db = database
        self.steam_page = steam_page
        self.pages: dict[str, StorePage] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.tabs = QTabWidget()
        self.tabs.setObjectName("StoreTabs")
        layout.addWidget(self.tabs)
        if self.steam_page is not None:
            self.tabs.addTab(self.steam_page, "STEAM")
        for store_id, adapter in stores.STORES.items():
            page = StorePage(database, adapter, self)
            self.pages[store_id] = page
            self.tabs.addTab(page, adapter.label)

    def reload(self) -> None:
        if self.steam_page is not None and hasattr(self.steam_page, "reload"):
            self.steam_page.reload()
        for page in self.pages.values():
            page.reload()

    def set_account(self, store: str, name: str, logged_in: bool) -> None:
        page = self.pages.get(store)
        if page is not None:
            page.set_account(name, logged_in)

    def set_updates(self, store: str, ids: Iterable[str]) -> None:
        page = self.pages.get(store)
        if page is not None:
            page.set_updates(ids)

    def set_sync_busy(self, store: str, busy: bool) -> None:
        if store == "steam" and self.steam_page is not None:
            if hasattr(self.steam_page, "set_sync_busy"):
                self.steam_page.set_sync_busy(busy)
            return
        page = self.pages.get(store)
        if page is not None:
            page.set_sync_busy(busy)

    def focus_store(self, store: str) -> None:
        if store == "steam" and self.steam_page is not None:
            self.tabs.setCurrentWidget(self.steam_page)
            return
        page = self.pages.get(store)
        if page is not None:
            self.tabs.setCurrentWidget(page)

    def shutdown(self) -> None:
        if self.steam_page is not None and hasattr(self.steam_page, "shutdown"):
            self.steam_page.shutdown()
        for page in self.pages.values():
            page.shutdown()


class StoreSettingsPanel(QWidget):
    setup_requested = pyqtSignal(str)
    login_requested = pyqtSignal(str)
    logout_requested = pyqtSignal(str)
    sync_requested = pyqtSignal(str)
    toast = pyqtSignal(str)

    def __init__(self, database: db.Database, adapter, parent=None) -> None:
        super().__init__(parent)
        self.db = database
        self.adapter = adapter
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 8, 0, 0)
        outer.setSpacing(9)
        self.status_label = QLabel("")
        self.status_label.setObjectName("Muted")
        self.status_label.setWordWrap(True)
        outer.addWidget(self.status_label)

        form = QFormLayout()
        form.setSpacing(8)
        self.dir_edit = QLineEdit()
        self.dir_edit.setPlaceholderText(tr("Domyślny katalog bazowy gier"))
        dir_row = QWidget()
        dir_layout = QHBoxLayout(dir_row)
        dir_layout.setContentsMargins(0, 0, 0, 0)
        dir_layout.setSpacing(6)
        dir_layout.addWidget(self.dir_edit, 1)
        browse_dir = QPushButton("...")
        browse_dir.setObjectName("GhostButton")
        browse_dir.setFixedWidth(42)
        browse_dir.clicked.connect(self._browse_dir)
        dir_layout.addWidget(browse_dir)
        form.addRow(tr("Katalog bazowy"), dir_row)

        self.tool_edit = QLineEdit()
        self.tool_edit.setPlaceholderText(
            tr("Puste = narzędzie pobrane przez Boostlayer")
        )
        tool_row = QWidget()
        tool_layout = QHBoxLayout(tool_row)
        tool_layout.setContentsMargins(0, 0, 0, 0)
        tool_layout.setSpacing(6)
        tool_layout.addWidget(self.tool_edit, 1)
        browse_tool = QPushButton("...")
        browse_tool.setObjectName("GhostButton")
        browse_tool.setFixedWidth(42)
        browse_tool.clicked.connect(self._browse_tool)
        tool_layout.addWidget(browse_tool)
        form.addRow(tr("Własne narzędzie"), tool_row)

        self.workers_spin = QSpinBox()
        self.workers_spin.setRange(0, 32)
        self.workers_spin.setSpecialValueText(tr("Automatycznie"))
        form.addRow(tr("Wątki pobierania"), self.workers_spin)
        outer.addLayout(form)

        actions = QHBoxLayout()
        setup = QPushButton(tr("Pobierz / aktualizuj"))
        setup.setObjectName("GhostButton")
        setup.clicked.connect(lambda: self.setup_requested.emit(self.adapter.id))
        actions.addWidget(setup)
        login = QPushButton(tr("Zaloguj się"))
        login.setObjectName("PrimaryButton")
        login.clicked.connect(lambda: self.login_requested.emit(self.adapter.id))
        actions.addWidget(login)
        logout = QPushButton(tr("Wyloguj"))
        logout.setObjectName("GhostButton")
        logout.clicked.connect(lambda: self.logout_requested.emit(self.adapter.id))
        actions.addWidget(logout)
        actions.addStretch(1)
        outer.addLayout(actions)

        sync = QPushButton(tr("↻  POBIERZ BIBLIOTEKĘ {store}", store=adapter.label))
        sync.setObjectName("PrimaryButton")
        sync.clicked.connect(self._request_sync)
        outer.addWidget(sync)
        self.reload()

    def _browse_dir(self) -> None:
        initial = self.dir_edit.text().strip() or str(Path.home())
        folder = QFileDialog.getExistingDirectory(
            self, tr("Katalog bazowy gier"), initial
        )
        if folder:
            self.dir_edit.setText(folder)

    def _browse_tool(self) -> None:
        initial = self.tool_edit.text().strip() or str(Path.home())
        path, _ = QFileDialog.getOpenFileName(
            self, tr("Wskaż narzędzie"), initial, tr("Wszystkie pliki (*)")
        )
        if path:
            self.tool_edit.setText(path)

    def _request_sync(self) -> None:
        self.save()
        self.sync_requested.emit(self.adapter.id)

    def save(self) -> None:
        self.db.set_many(
            {
                self.adapter.install_setting: self.dir_edit.text().strip(),
                self.adapter.tool_setting: self.tool_edit.text().strip(),
                f"{self.adapter.id}_max_workers": str(self.workers_spin.value()),
            }
        )

    def reload(self) -> None:
        self.dir_edit.setText(self.db.get_setting(self.adapter.install_setting, ""))
        self.tool_edit.setText(self.db.get_setting(self.adapter.tool_setting, ""))
        self.workers_spin.setValue(
            self.db.get_int(f"{self.adapter.id}_max_workers", 0)
        )
        self.refresh_status()

    def refresh_status(self) -> None:
        binary = self.adapter.tool_binary(self.db)
        parts: list[str] = []
        if binary is not None:
            version = stores.tool_version(self.adapter.version_name)
            parts.append(tr("Narzędzie: {path}", path=str(binary)))
            if version:
                parts.append(tr("wersja {version}", version=version))
            user = self.adapter.current_user()
            if user.get("name"):
                parts.append(tr("konto: {name}", name=user["name"]))
            else:
                parts.append(tr("konto: niezalogowane"))
        else:
            parts.append(
                tr("Narzędzie {store} nie jest zainstalowane", store=self.adapter.label)
            )
        stats = self.db.store_library_stats(self.adapter.id)
        parts.append(
            tr(
                "Biblioteka: {total} gier, zainstalowanych: {installed}",
                total=stats["total"],
                installed=stats["installed"],
            )
        )
        synced = self.db.get_setting(f"{self.adapter.id}_library_synced", "").strip()
        parts.append(tr("Ostatnia synchronizacja: {date}", date=synced or tr("nigdy")))
        self.status_label.setText("  //  ".join(parts))

    def set_busy(self, busy: bool) -> None:
        self.dir_edit.setEnabled(not busy)
        self.tool_edit.setEnabled(not busy)
