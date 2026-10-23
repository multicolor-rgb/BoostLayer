# Boostlayer

Minimalistyczny launcher gier standalone i wrapper dla Steam, nastawiony na
izolację procesów, niski narzut i pełną kontrolę nad łańcuchem Wine/Proton.
Backend korzysta wyłącznie z biblioteki standardowej Pythona (`sqlite3`,
`urllib`, `tarfile`, `subprocess`, `shlex`, `re`). Jedyną zewnętrzną zależnością
runtime jest **PyQt6**.

Strona projektu: **<https://multicolor-rgb.github.io/boostlayer/>** (PL / EN)

## Funkcje

- **Biblioteka** — nowoczesny interfejs w stylu Epic Games Store:
  duży banner wybranej gry, siatka okładek z nakładką hover, widok listy oraz
  tryb minimalny (tray).
- **Motywy** — Epic Dark, Violet i Ember; wybór w
  Ustawieniach → Wygląd. Paleta jest neutralna, a akcent używany oszczędnie.
- **Układ** — górny pasek z globalną wyszukiwarką i ikonową szyną nawigacji
  (zwijaną do samych ikon), spójne karty, chipy i przyciski w całej aplikacji.
- **Języki** — polski (domyślny), angielski i niemiecki; wybór w
  Ustawieniach → Wygląd → Język. Zmiana działa od razu, bez restartu
  aplikacji.
- **Ikona** — biały monogram BL na czarnym tle, spójny w oknie, trayu,
  menu i pakietach AppImage/.deb (pełny zestaw PNG/SVG).
- **Biblioteka** — siatka dużych okładek z tytułem i metadanymi pod
  spodem, rząd **Kontynuuj** z ostatnio granymi grami, filtry źródła,
  sortowanie (w tym „Ostatnio grane”) i nawigacja klawiaturą.
- **Tryb konsolowy** — kinowy Big Picture: duży hero z tytułem i akcjami,
  pływająca okładka, rozmyte tło z crossfade i pozioma karuzela okładek.
  Obsługa pada (`/dev/input/js*`), kółka myszy i klawiatury; po zakończeniu
  gry standalone konsola wraca automatycznie, dla Steam działa wykrywanie
  best-effort.
- **Powiadomienia** — pływająca pigułka z ikoną i wygaszaniem zamiast
  wpisu w pasku statusu; delikatne przejścia między stronami.
- **Tray i hotkey** — stylowane menu z ostatnimi grami; `Ctrl+Alt+S`
  pokazuje/ukrywa okno (X11 przez `XGrabKey`, na Wayland lokalny fallback).
- **Minimalizacja** — po starcie gry Boostlayer minimalizuje się do paska
  zadań i pozostaje w pamięci. Gra standalone jest nadzorowana przez
  `QProcess`; po jej zakończeniu okno wraca. Dla Steam powrót przez tray lub
  `Ctrl+Alt+S`.
- **Izolacja** — osobny `WINEPREFIX` per gra, własne zmienne środowiskowe,
  argumenty i profil skalowania. Domyślnie: `~/.config/boostlayer/prefixes/`.
- **Menedżer runnerów** — Proton-GE i Wine-GE pobierane bezpośrednio z GitHub
  Releases przez `urllib`; lista pozwala wybrać najnowszą, starszą lub
  prerelease wersję. Archiwa `.tar.gz`/`.tar.xz` są rozpakowywane przez
  `tarfile` z ochroną przed path traversal. Bez tokena API aplikacja też działa.
- **Skalowanie** — AMD FSR, NIS, Integer Scaling, CRT oraz Proton FSR
  (Quality/Balanced/Performance) przez Gamescope i zmienne DXVK/Proton.
- **Limit FPS** — 0, 30, 40, 60, 90, 120, 144. MangoHud `fps_limit` oraz
  `DXVK_FRAME_RATE` jako fallback.
- **MangoHud Configurator** — moduły, pozycja 3×3 (również kliknięciem w
  podglądzie), kolory, font, tło, zaokrąglenia. `MANGOHUD_CONFIG` jest budowany
  przy każdym starcie i zawsze zawiera `custom_text=<krótki profil>`
  (np. `FSR720p`, `CRT`, `PFSR-Q`). Wymuszone jest `legacy_layout=0`, bo stary
  renderer MangoHud nie wyświetla `custom_text`.
- **Winetricks** — instalacja komponentów Windows per gra: PhysX, Visual C++,
  DirectX 9, XACT, .NET, Media Foundation i własne verb-y. Działa dla Wine/Proton
  oraz — przez `protontricks` — dla gier Steam. Można włączyć automatyczną
  instalację wybranych komponentów przed startem gry.
- **Biblioteka Steam** — zakładka **STEAM** w widoku **SKLEPY** ze wszystkimi posiadanymi grami
  (Steam Web API key), filtrem zainstalowanych i przyciskiem instalacji przez
  `steam://install/<appid>`.
- **Steam** — import `appmanifest_*.acf`, okładki z lokalnego `librarycache`,
  potem CDN. Gry Steam uruchamiane są przez klienta Steam; wrapper
  `~/.config/boostlayer/steam-wrapper.sh` jest automatycznie dopisywany do
  `LaunchOptions` w `localconfig.vdf` (z backupem i walidacją). Steam musi być
  zamknięty na czas edycji; aplikacja pyta o restart.
- **SKLEPY** — jedna zakładka z pod-stronami **STEAM | AMAZON | GOG | EPIC**.
  Steam zachowuje swój import `appmanifest_*.acf`, bibliotekę i wrapper
  LaunchOptions, a jego panel ustawień jest pierwszą zakładką w
  **Ustawienia → Sklepy**.
  Wspólny model sklepów (`store`/`store_id`, tabela `store_library`) i wspólne
  dialogi logowania, postępu oraz wyboru katalogu instalacji. Przy każdym
  **ZAINSTALUJ** aplikacja pyta o dokładny katalog gry (z propozycją
  `katalog_bazowy / tytuł`, informacją o wolnym miejscu i opcją zapamiętania
  katalogu bazowego dla sklepu).
- **Amazon Games (Prime Gaming)** — integracja przez `nile`:
  logowanie konta Amazon, synchronizacja biblioteki, pobieranie z postępem
  i anulowaniem, aktualizacje, weryfikacja plików oraz odinstalowanie. `nile`
  jest pobierany z GitHub Releases do `~/.config/boostlayer/tools` (można
  wskazać własną binarkę), a dane konta trafiają do izolowanego katalogu
  `~/.config/boostlayer/amazon/nile`. Uruchamianie wykorzystuje
  `nile launch --json`, ale sam proces gry przechodzi przez zwykły pipeline
  Boostlayera — runner, osobny `WINEPREFIX`, MangoHud, Gamescope i limit FPS.
- **GOG** — integracja przez `gogdl`: logowanie przez stronę GOG, biblioteka
  z GOG Galaxy API i metadane/okładki z GamesDB, instalacja do wybranego
  katalogu, aktualizacje i naprawa przez `gogdl`, uruchamianie z `goggame-*.info`
  przez runner Boostlayera. Tokeny trafiają do
  `~/.config/boostlayer/gog/auth.json` (0600).
- **Epic Games** — integracja przez `legendary`: logowanie kodem
  `authorizationCode`, biblioteka `legendary list --json`, instalacja
  `--base-path`/`--game-folder` do wybranego katalogu, aktualizacje, naprawa
  i odinstalowanie. Uruchamianie korzysta z `legendary launch --json`, ale
  proces gry jest prowadzony przez runner Boostlayera. Konfiguracja jest
  izolowana w `~/.config/boostlayer/epic/legendary`.
- **Okładki i rozmiary** — po zalogowaniu/synchronizacji okładki pobierają się
  w tle dla całej biblioteki i pojawiają się progresywnie w tabeli. Rozmiary
  gier są dociągane osobno (Amazon/GOG/Epic przez `nile`/`gogdl`/`legendary`,
  Steam przez `SizeOnDisk` z `appmanifest_*.acf`). Dla niezainstalowanych gier
  Steam rozmiar pozostaje nieznany. Oba prefetche można wyłączyć w
  **Ustawienia → Sklepy**.
- **Wspólna biblioteka** — zainstalowane gry Amazon/GOG/Epic trafiają
  automatycznie do głównej biblioteki z oznaczeniem sklepu i własnym runnerem,
  prefiksem, skalowaniem, limitem FPS i Winetricks.
- **Ubisoft Connect** — planowany w kolejnym etapie. Ubisoft nie udostępnia
  publicznego API/CLI do cichej instalacji, więc integracja będzie oparta na
  zarządzanym kliencie Ubisoft Connect w prefiksie Wine (bez automatycznego
  pobierania w tle).
- **Zależności** — `.deb` instaluje MangoHud i GameMode przez `Depends`;
  AppImage ma przycisk „Zainstaluj brakujące” korzystający z `pkexec`.
  Gamescope jest opcjonalny, bo nie każda dystrybucja ma go w repozytorium.
- **GameMode** — `gamemoderun` jako najbardziej zewnętrzny element łańcucha.
- **Debug** — log `~/.config/boostlayer/last_run.log`.
- **Cache** — bezpieczne czyszczenie znanych katalogów shader cache.

## Wymagania

- Linux x86_64/arm64, X11 lub Wayland.
- Python 3.10+ do uruchomienia ze źródeł.
- PyQt6: `python3 -m pip install -r requirements.txt`.
- AppImage na X11 może wymagać systemowego `libxcb-cursor0`.
- `.deb` automatycznie instaluje `mangohud` i `gamemode`.
- Gamescope jest opcjonalny i nie występuje w apt na Ubuntu 24.04; aplikacja
  pokaże komunikat zamiast dodawać nieoficjalne repozytoria.
- Dla gier 32-bitowych potrzebny jest 32-bitowy MangoHud. Ubuntu/Mint nie mają
  `mangohud:i386`; Ustawienia → Zależności → **MangoHud 32-bit** instaluje
  oficjalny build lib32 i biblioteki i386 GameMode.
- Pad w trybie konsolowym wymaga dostępu do `/dev/input/js*`. Ustawienia →
  Zależności → **Włącz obsługę pada** instaluje regułę udev `uaccess`.
  Po instalacji odłącz i podłącz kontroler ponownie.
- Na Intel GPU statystyki GPU w MangoHud wymagają `intel-gpu-tools`
  (`intel_gpu_top`); bez tego MangoHud wyłącza `gpu_stats`.
- Wine trzeba zainstalować osobno (duży pakiet, świadoma decyzja użytkownika).
- Amazon Games wymaga `nile` (pobierany automatycznie) oraz konta Amazon.
  Amazon nie przekierowuje logowania na `localhost`, więc po zalogowaniu w
  przeglądarce trzeba wkleić pełny URL przekierowania. Gry online korzystające
  z `FuelPump`, anty-cheat oraz część starszych tytułów mogą nie działać —
  to ograniczenie `nile`. Skrypty `PostInstall` z `fuel.json` nie są
  uruchamiane na Linuksie; brakujące redisty można doinstalować przez
  Winetricks.
- GOG wymaga `gogdl` (pobierany automatycznie) i konta GOG. Wersja v1 instaluje
  buildy Windows (`--os windows`); natywne wersje Linux GOG wymagają osobnej
  ścieżki uruchamiania bez Wine.
- Epic wymaga `legendary` (pobierany automatycznie) i konta Epic. Gry Epic
  wymagające Ubisoft Connect lub EA App są oznaczone jako wymagające
  zewnętrznego klienta i nie uruchomią się bez niego.
- Ubisoft Connect nie ma publicznego API do biblioteki i cichych instalacji;
  integracja będzie oparta na oficjalnym kliencie uruchamianym w Wine.
- Winetricks jest opcjonalny. Można użyć systemowego `winetricks` albo
  zainstalować lokalną kopię z Ustawień → Zależności. Dla gier Steam potrzebny
  jest `protontricks`. Winetricks może wymagać `cabextract` i `unzip`.
- Pełna biblioteka Steam wymaga internetu i Steam Web API key; klucz jest
  przechowywany lokalnie w bazie Boostlayera.
- Do budowy: `PyInstaller`, `dpkg-deb`, `appimagetool` (pobierany przez
  `build.sh`, jeśli go brak).

## Instalacja

```sh
sudo apt install ./dist/Boostlayer-0.1.0-amd64.deb
# albo bez instalacji:
chmod +x dist/Boostlayer-0.1.0-x86_64.AppImage
./dist/Boostlayer-0.1.0-x86_64.AppImage
```

## Uruchomienie ze źródeł

```sh
python3 -m venv venv
. venv/bin/activate
pip install -r requirements.txt
python main.py
```

## Użycie

1. Dodaj grę standalone (`DODAJ GRĘ`) lub zsynchronizuj Steam.
2. W Menedżerze runnerów kliknij **Pokaż / odśwież wersje**, aby wybrać
   konkretny Proton-GE/Wine-GE (także starszy lub beta), albo zainstaluj
   najnowszy. Potem wybierz runner, prefix, skalowanie i limit FPS.
3. Uruchom grę. Launcher zminimalizuje się do paska zadań; `Ctrl+Alt+S`
   przywraca lub chowa okno.
4. **Tryb konsolowy** otworzysz z menu aplikacji, tray lub przez `--console`.
   Pad jest aktywny tylko w tym widoku i jest wyłączany po starcie gry.
5. Komponenty Windows instalujesz przez menu kontekstowe gry → **Winetricks…**
   (PhysX, VC++, DirectX 9, XACT, .NET itd.). Dla gier Steam używany jest
   `protontricks`. Opcję automatycznej instalacji przed startem włączasz w
   edycji gry.
6. Dla gry Steam Boostlayer przy pierwszym uruchomieniu zapyta o zamknięcie
   Steama, dopisze wrapper do `LaunchOptions`, zrobi backup `localconfig.vdf`
   i uruchomi grę ponownie przez `steam -applaunch`. Możesz też użyć
   **Ustawienia → Steam wrapper → Zastosuj do wszystkich gier Steam**.
   Wrapper odczyta `SteamAppId`, znajdzie wpis w bazie i dołoży środowisko
   Boostlayera do oryginalnego `%command%`.

## Łańcuch uruchamiania

```text
[DEBUG LOG] → [GAMEMODERUN] → [MANGOHUD] → [GAMESCOPE + SHADER]
            → [ENV] → [WINE/PROTON] → [WINEPREFIX] → [GRA.EXE] → [ARGS]
```

Dla gry Steam wrapper ustawia `BL_DIRECT=1`, więc `launcher.sh` nie dokłada
drugiego Wine — Steam/Proton pozostaje właścicielem komendy i prefiksu.

## Dane

```text
~/.config/boostlayer/
├── data.db
├── covers/
├── prefixes/
├── runners/
├── runtime/        # 0600 pliki tymczasowe, usuwane po wczytaniu przez launcher
├── shaders/
├── steam-backups/  # kopie localconfig.vdf przed edycją LaunchOptions
├── boostlayer.log
└── last_run.log    # tylko przy włączonym debugowaniu
```

## Build

```sh
./build.sh
```

Wynik w `dist/`:

- `Boostlayer-<wersja>-x86_64.AppImage`
- `Boostlayer-<wersja>-amd64.deb`
- `SHA256SUMS`

`VERSION` jest źródłem wersji; można ją nadpisać przez `VERSION=... ./build.sh`.
Workflow `.github/workflows/release.yml` buduje oba artefakty na Ubuntu 22.04 i
publikuje release dla tagu `v*` przez `softprops/action-gh-release`.

## Release

```sh
./release.sh          # testy + tag v$(cat VERSION) + push
```

lub ręcznie:

```sh
git tag -a "v$(cat VERSION)" -m "Boostlayer $(cat VERSION)"
git push origin "v$(cat VERSION)"
```

## Licencja

MIT — zobacz `LICENSE`.

Historia i numeracja zmian: [CHANGELOG.md](CHANGELOG.md).
