/* Boostlayer landing — vanilla JS, no dependencies. */
(() => {
  "use strict";

  const root = document.documentElement;
  const body = document.body;
  const $ = (selector, scope = document) => scope.querySelector(selector);
  const $$ = (selector, scope = document) => [...scope.querySelectorAll(selector)];
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

  const storage = {
    get(key) {
      try { return localStorage.getItem(key); } catch { return null; }
    },
    set(key, value) {
      try { localStorage.setItem(key, value); } catch { /* private mode */ }
    }
  };

  /* ------------------------------ language ------------------------------ */
  const LANG_KEY = "boostlayer.site.lang";
  const i18nNodes = $$("[data-en], [data-en-html], [data-en-aria]");
  const metaDescription = $('meta[name="description"]');
  const ogTitle = $('meta[property="og:title"]');
  const ogDescription = $('meta[property="og:description"]');
  const twTitle = $('meta[name="twitter:title"]');
  const twDescription = $('meta[name="twitter:description"]');

  i18nNodes.forEach((el) => {
    if (el.hasAttribute("data-en")) el.dataset.plText = el.textContent;
    if (el.hasAttribute("data-en-html")) el.dataset.plHtml = el.innerHTML;
    if (el.hasAttribute("data-en-aria")) el.dataset.plAria = el.getAttribute("aria-label") || "";
  });

  let currentLang = "pl";

  function setMeta(selector, value) {
    const node = typeof selector === "string" ? $(selector) : selector;
    if (node && value) node.setAttribute("content", value);
  }

  function applyLanguage(lang, persist = true) {
    currentLang = lang === "en" ? "en" : "pl";

    root.lang = currentLang;

    i18nNodes.forEach((el) => {
      if (el.hasAttribute("data-en-html")) {
        el.innerHTML = currentLang === "en" ? el.dataset.enHtml : el.dataset.plHtml;
      } else if (el.hasAttribute("data-en")) {
        el.textContent = currentLang === "en" ? el.dataset.en : el.dataset.plText;
      }
      if (el.hasAttribute("data-en-aria")) {
        el.setAttribute("aria-label", currentLang === "en" ? el.dataset.enAria : el.dataset.plAria);
      }
    });

    const title = currentLang === "en" ? body.dataset.titleEn : body.dataset.titlePl;
    const description = currentLang === "en" ? body.dataset.descEn : body.dataset.descPl;
    if (title) document.title = title;
    setMeta(metaDescription, description);
    setMeta(ogTitle, title);
    setMeta(ogDescription, description);
    setMeta(twTitle, title);
    setMeta(twDescription, description);

    $$("[data-lang-btn]").forEach((btn) => {
      const active = btn.dataset.langBtn === currentLang;
      btn.classList.toggle("is-active", active);
      btn.setAttribute("aria-pressed", String(active));
    });

    const toggle = $(".menu-toggle");
    if (toggle) {
      const open = toggle.getAttribute("aria-expanded") === "true";
      toggle.setAttribute("aria-label", currentLang === "en" ? (open ? "Close menu" : "Open menu") : (open ? "Zamknij menu" : "Otwórz menu"));
    }

    if (persist) {
      storage.set(LANG_KEY, currentLang);
      const url = new URL(window.location.href);
      if (currentLang === "en") url.searchParams.set("lang", "en");
      else url.searchParams.delete("lang");
      history.replaceState(null, "", url);
    }
  }

  $$("[data-lang-btn]").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (btn.dataset.langBtn !== currentLang) applyLanguage(btn.dataset.langBtn);
    });
  });

  const queryLang = new URLSearchParams(window.location.search).get("lang");
  const initialLang = queryLang === "en" || queryLang === "pl" ? queryLang : storage.get(LANG_KEY) === "en" ? "en" : "pl";
  applyLanguage(initialLang, Boolean(queryLang));

  /* ------------------------------- theme -------------------------------- */
  const THEME_KEY = "boostlayer.site.theme";
  const themeColors = { epic: "#07080b", violet: "#08070c", ember: "#0a0807" };
  const themeMeta = $('meta[name="theme-color"]');

  function applyTheme(theme) {
    const next = ["epic", "violet", "ember"].includes(theme) ? theme : "epic";
    root.dataset.theme = next;
    if (themeMeta) themeMeta.setAttribute("content", themeColors[next]);
    $$("[data-set-theme]").forEach((dot) => {
      const active = dot.dataset.setTheme === next;
      dot.classList.toggle("is-active", active);
      dot.setAttribute("aria-pressed", String(active));
    });
    storage.set(THEME_KEY, next);
  }

  $$("[data-set-theme]").forEach((dot) => {
    dot.addEventListener("click", () => applyTheme(dot.dataset.setTheme));
  });
  applyTheme(storage.get(THEME_KEY) || "epic");

  /* --------------------------- header / scroll -------------------------- */
  const header = $(".site-header");
  const progress = $(".scroll-progress span");
  let scrollQueued = false;

  function onScroll() {
    scrollQueued = false;
    const y = window.scrollY;
    if (header) header.classList.toggle("is-scrolled", y > 12);
    if (progress) {
      const max = document.documentElement.scrollHeight - window.innerHeight;
      const ratio = max > 0 ? Math.min(y / max, 1) : 0;
      progress.style.width = `${(ratio * 100).toFixed(2)}%`;
    }

    let active = null;
    $$(".nav-links a[href^='#']").forEach((link) => {
      const section = document.getElementById(link.getAttribute("href").slice(1));
      if (!section) return;
      if (section.getBoundingClientRect().top <= 140) active = link;
    });
    $$(".nav-links a").forEach((link) => {
      const isActive = link === active;
      link.classList.toggle("is-active", isActive);
      if (isActive) link.setAttribute("aria-current", "location");
      else link.removeAttribute("aria-current");
    });
  }

  window.addEventListener("scroll", () => {
    if (scrollQueued) return;
    scrollQueued = true;
    requestAnimationFrame(onScroll);
  }, { passive: true });
  window.addEventListener("resize", onScroll, { passive: true });
  onScroll();

  /* ------------------------------ mobile menu --------------------------- */
  const menuToggle = $(".menu-toggle");
  const mobileMenu = $("#mobile-menu");

  function setMenu(open) {
    if (!menuToggle || !mobileMenu) return;
    mobileMenu.hidden = !open;
    menuToggle.setAttribute("aria-expanded", String(open));
    body.classList.toggle("menu-open", open);
    document.querySelectorAll("main, .site-footer").forEach((el) => { el.inert = open; });
    const label = currentLang === "en" ? (open ? "Close menu" : "Open menu") : (open ? "Zamknij menu" : "Otwórz menu");
    menuToggle.setAttribute("aria-label", label);
  }

  if (menuToggle && mobileMenu) {
    menuToggle.setAttribute("aria-label", currentLang === "en" ? "Open menu" : "Otwórz menu");
    menuToggle.addEventListener("click", () => setMenu(menuToggle.getAttribute("aria-expanded") !== "true"));
    $$("a", mobileMenu).forEach((link) => link.addEventListener("click", () => setMenu(false)));
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && menuToggle.getAttribute("aria-expanded") === "true") {
        setMenu(false);
        menuToggle.focus();
      }
    });
    window.addEventListener("resize", () => {
      if (window.innerWidth > 1180 && menuToggle.getAttribute("aria-expanded") === "true") setMenu(false);
    }, { passive: true });
  }

  /* -------------------------------- tabs -------------------------------- */
  $$("[data-tabs]").forEach((group) => {
    const tabs = $$("[role='tab']", group);
    const panels = $$("[role='tabpanel']", group);
    if (!tabs.length) return;

    tabs.forEach((tab) => {
      tab.tabIndex = tab.getAttribute("aria-selected") === "true" ? 0 : -1;
    });

    function select(index, focus = false) {
      const tab = tabs[index];
      const id = tab.dataset.tab;
      tabs.forEach((item) => {
        const active = item === tab;
        item.setAttribute("aria-selected", String(active));
        item.tabIndex = active ? 0 : -1;
      });
      panels.forEach((panel) => {
        const active = panel.dataset.panel === id;
        panel.hidden = !active;
        panel.classList.toggle("is-active", active);
      });
      if (focus) tab.focus();
    }

    tabs.forEach((tab, index) => {
      tab.addEventListener("click", () => select(index));
      tab.addEventListener("keydown", (event) => {
        let next = null;
        if (event.key === "ArrowRight" || event.key === "ArrowDown") next = (index + 1) % tabs.length;
        if (event.key === "ArrowLeft" || event.key === "ArrowUp") next = (index - 1 + tabs.length) % tabs.length;
        if (event.key === "Home") next = 0;
        if (event.key === "End") next = tabs.length - 1;
        if (next === null) return;
        event.preventDefault();
        select(next, true);
      });
    });
  });

  /* ------------------------------- copying ------------------------------ */
  const toast = $(".toast");
  let toastTimer;

  function showToast(message) {
    if (!toast) return;
    toast.textContent = message;
    toast.classList.add("is-visible");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toast.classList.remove("is-visible"), 1900);
  }

  async function copyText(text) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      const area = document.createElement("textarea");
      area.value = text;
      area.setAttribute("readonly", "");
      area.style.position = "fixed";
      area.style.opacity = "0";
      document.body.appendChild(area);
      area.select();
      let ok = false;
      try { ok = document.execCommand("copy"); } catch { ok = false; }
      area.remove();
      return ok;
    }
  }

  $$("[data-copy]").forEach((button) => {
    button.addEventListener("click", async () => {
      const block = button.closest(".code-block");
      const code = block ? $("pre code", block) : null;
      if (!code) return;
      const ok = await copyText(code.textContent.trim());
      if (!ok) {
        showToast(currentLang === "en" ? "Could not copy" : "Nie udało się skopiować");
        return;
      }
      button.classList.add("is-copied");
      showToast(currentLang === "en" ? "Copied to clipboard" : "Skopiowano do schowka");
      setTimeout(() => button.classList.remove("is-copied"), 1600);
    });
  });

  /* ------------------------------- reveal ------------------------------- */
  const revealTargets = $$("[data-reveal]");
  if ("IntersectionObserver" in window && !reduceMotion.matches) {
    root.classList.add("js-anim");
    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        entry.target.classList.add("is-visible");
        observer.unobserve(entry.target);
      });
    }, { threshold: 0.12, rootMargin: "0px 0px -40px" });
    revealTargets.forEach((el) => observer.observe(el));
  }

  /* ------------------------------ counters ------------------------------ */
  const stats = $(".stats");
  if (stats) {
    const counters = $$("[data-count]", stats);
    const runCounters = () => {
      counters.forEach((node) => {
        if (node.dataset.done) return;
        node.dataset.done = "1";
        const target = Number(node.dataset.count) || 0;
        if (reduceMotion.matches) {
          node.textContent = String(target);
          return;
        }
        const duration = 1300;
        const start = performance.now();
        const tick = (now) => {
          const t = Math.min((now - start) / duration, 1);
          const eased = 1 - Math.pow(1 - t, 3);
          node.textContent = String(Math.round(target * eased));
          if (t < 1) requestAnimationFrame(tick);
        };
        requestAnimationFrame(tick);
      });
    };

    if ("IntersectionObserver" in window) {
      const statsObserver = new IntersectionObserver((entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          runCounters();
          statsObserver.disconnect();
        }
      }, { threshold: 0.35 });
      statsObserver.observe(stats);
    } else {
      runCounters();
    }
  }

  /* -------------------------------- tilt -------------------------------- */
  const tilt = $("[data-tilt]");
  const finePointer = window.matchMedia("(hover: hover) and (pointer: fine)");
  if (tilt && finePointer.matches) {
    let frame = null;
    tilt.addEventListener("pointermove", (event) => {
      if (window.innerWidth < 1024 || reduceMotion.matches) return;
      const rect = tilt.getBoundingClientRect();
      const px = (event.clientX - rect.left) / rect.width - 0.5;
      const py = (event.clientY - rect.top) / rect.height - 0.5;
      if (frame) cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        tilt.style.setProperty("--ry", `${(px * 5).toFixed(2)}deg`);
        tilt.style.setProperty("--rx", `${(-py * 4).toFixed(2)}deg`);
      });
    });
    tilt.addEventListener("pointerleave", () => {
      if (frame) cancelAnimationFrame(frame);
      tilt.style.setProperty("--ry", "0deg");
      tilt.style.setProperty("--rx", "0deg");
    });
  }

  /* ----------------------------- card glow ------------------------------ */
  if (finePointer.matches) {
    $$(".card").forEach((card) => {
      card.addEventListener("pointermove", (event) => {
        const rect = card.getBoundingClientRect();
        card.style.setProperty("--mx", `${event.clientX - rect.left}px`);
        card.style.setProperty("--my", `${event.clientY - rect.top}px`);
      }, { passive: true });
    });
  }

  /* -------------------------------- year -------------------------------- */
  const yearNode = $("[data-year]");
  if (yearNode) yearNode.textContent = String(new Date().getFullYear());
})();
