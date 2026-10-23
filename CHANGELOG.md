# Historia zmian Boostlayer

Numeracja odpowiada tagom `build-01` … `build-15`.
**Najwyższy numer = najnowsza zmiana.**

| # | Data | Zmiana | Gałąź |
|---|------|--------|-------|
| 15 | 2026-10-23 | Siatka 2.0, rząd „Kontynuuj” i kinowa konsola (hero + karuzela) | `feature/epic-heroic-ui-build12` |
| 14 | 2026-10-23 | Redesign UI w stylu Epic Games Store / Heroic + nowa ikona BL, na bazie build-12 (sklepy) | `feature/epic-heroic-ui-build12` |
| 13 | 2026-10-23 | Redesign UI w stylu Epic Games Store / Heroic + nowa ikona BL (na bazie build-11) | `feature/epic-heroic-ui` |
| 12 | 2026-10-22 | Integracje z wieloma sklepami, okładki i prefetch rozmiarów | `feature/store-integrations` |
| 11 | 2026-10-21 | Pełna biblioteka Steam z synchronizacją API i instalacją w aplikacji | `feature/steam-library-api` |
| 10 | 2026-10-21 | Menedżer Winetricks i kinowy tryb Big Picture | `feature/winetricks-big-picture` |
| 9 | 2026-10-21 | Boostlayer jako launcher gier (zastąpił prototyp skalowania) | `main` |
| 8 | 2026-10-20 | Poprawka zamrażania overlaya: SHM, click-through, single instance | — |
| 7 | 2026-10-20 | Wybór okna kliknięciem, aktywne okno, tray | — |
| 6 | 2026-10-20 | Obsługa wielu monitorów (pozycja i wybór monitora) | — |
| 5 | 2026-10-20 | Okna override-redirect (Proton/Wine) w wyborze okna | — |
| 4 | 2026-10-20 | Nienazwane okna + auto-odświeżanie wyboru okna | — |
| 3 | 2026-10-20 | Przechwytywanie XComposite + wybór okna, borderless overlay | — |
| 2 | 2026-10-20 | Poprawka GLFW video mode, start renderera overlaya | — |
| 1 | 2026-10-20 | Pierwszy commit projektu | — |

## 15 — Siatka 2.0, „Kontynuuj” i kinowa konsola

- **Siatka 2.0**: większe karty (212 px), okładki 3:4 z zaokrągleniem,
  tytuł i metadane pod okładką, badge źródła, gradientowy fallback dla gier
  bez okładki, hover z delikatnym zoomem i przyciskami Play/⋯, pierścień
  zaznaczenia i pełna nawigacja klawiaturą (strzałki, Enter, E, Delete).
- **Kontynuuj**: nowy rząd ostatnio granych gier (maks. 6) nad siatką,
  zasilany polem `last_played` w bazie i migracją dla starszych baz;
  uruchomienie dowolnej gry (standalone, Steam, sklep) aktualizuje wpis.
- **Sortowanie**: nowa opcja „Ostatnio grane”, segmentowe filtry źródła
  (Wszystkie / Steam / Standalone), licznik wyników i pusty stan z CTA.
- **Konsola 2.0**: kinowy hero z dużym tytułem, chipami i przyciskami
  Graj/Edytuj, pływająca okładka z poświatą, rozmyte tło z crossfade,
  pozioma karuzela okładek ze skalowaniem zaznaczenia, obsługa pada,
  kółka myszy i klawiatury; zachowane całe API i powrót z gry.
- **UX**: delikatne przejście stron (fade 150 ms), pływający toast-pigułka
  z ikoną i wygaszaniem, wspólne stany hover/focus dla przycisków i pól.
- Zachowane wszystkie funkcje: Wine/Proton, Steam i sklepy, tray, hotkey,
  pad, MangoHud, Winetricks oraz tłumaczenia PL/EN/DE.
- Testy: 95/95 OK.

## 14 — Redesign UI na bazie build-12 (sklepy)

- Ten sam redesign co build-13, przeniesiony na historię z integracjami
  sklepów (Steam, Amazon, GOG, Epic): zachowana cała logika sklepów.
- Nawigacja: Biblioteka / **Sklepy** / Ustawienia / Runnery / MangoHud;
  zakładki sklepów w nowym stylu, nagłówki i przyciski w sentence case.
- Globalna wyszukiwarka steruje aktywną zakładką sklepu (lokalne pole
  wyszukiwania jest ukryte).
- Zakładka Steam: siatka okładek z hoverem i panel szczegółów.
- Ikona BL (biały monogram na czarnym tle) wszędzie.
- Katalogi PL/EN/DE scalone z build-12; testy: 92/92 OK.

## 13 — Redesign UI: Epic Games Store / Heroic (na bazie build-11)

- Nowy design system: palety **Epic Dark**, **Heroic Violet**, **Ember**,
  tokeny QSS (`${accent}`, `${surface}`…), ciemna paleta Qt.
- Nowy shell: górny pasek z globalną wyszukiwarką, ikonowa szyna nawigacji
  ze zwijaniem do 64 px, dyskretny pasek statusu.
- Biblioteka: hero banner z rozmytej okładki, siatka okładek z nakładką
  hover (Play/⋯), widok listy, filtry źródła i sortowanie.
- Steam: siatka okładek + panel szczegółów z okładką, chipami i akcjami.
- Ustawienia, Runnery, MangoHud, dialogi i Big Picture w nowej stylistyce.
- 25 własnych ikon SVG (`assets/ui/`) tintowanych kolorem motywu.
- Nowa ikona aplikacji: biały monogram **BL** na czarnym tle, wszędzie
  (okno, tray, dialogi, Big Picture, AppImage/.deb).
- Tłumaczenia PL/EN/DE uzupełnione, przestarzałe klucze usunięte.
- Testy: 45/45 OK.
