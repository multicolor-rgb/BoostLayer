# Strona projektu Boostlayer

Statyczna strona-wizytówka w `docs/`. Bez frameworków, bez build-stepu:
HTML + CSS + vanilla JS. Polski jest językiem domyślnym, angielski włącza się
przełącznikiem `PL / EN`. Wybór języka i motywu jest zapamiętywany w
`localStorage`. Język można też wymusić adresem `?lang=en`.

## Podgląd lokalny

```sh
python3 -m http.server 8000 --directory docs
# http://localhost:8000/
```

## Publikacja

Workflow `.github/workflows/pages.yml` publikuje katalog `docs/` na GitHub
Pages po pushu do `main`. W repozytorium włącz:

**Settings → Pages → Build and deployment → Source: GitHub Actions**

Strona: <https://multicolor-rgb.github.io/boostlayer/>

## Edycja treści

- Teksty polskie: bezpośrednio w `docs/index.html`.
- Teksty angielskie: atrybuty `data-en`, `data-en-html` i `data-en-aria`
  na tych samych elementach. JS podmienia je przy przełączeniu języka.
- Nowe teksty dodawaj do HTML, nie do JS — słownika nie ma, źródłem prawdy
  jest znacznik.
- Motywy (Epic / Violet / Ember) to zmienne CSS w `html[data-theme=…]`.

## Pliki

```text
docs/
├── index.html
├── site.webmanifest
├── favicon.ico
├── robots.txt
├── sitemap.xml
├── .nojekyll
└── assets/
    ├── css/site.css
    ├── js/site.js
    ├── fonts/        # self-hosted Space Grotesk, Inter, JetBrains Mono
    └── img/          # logo BL, ikony, og.png 1200×630
```
