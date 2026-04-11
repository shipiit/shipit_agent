/*
 * shipit-agent docs — collapsible right-hand TOC sidebar
 *
 * Hides the right-hand "Table of contents" sidebar by default so the
 * page content uses the full viewport. A small floating button at the
 * top right of the screen toggles it on demand. The user's preference
 * is persisted to localStorage so the layout sticks across page loads.
 */
(function () {
  const STORAGE_KEY = "shipit-toc-open";
  const OPEN_CLASS = "shipit-toc-open";
  const TOGGLE_LABEL_OPEN = "📑 Hide TOC";
  const TOGGLE_LABEL_CLOSED = "📑 Show TOC";

  function isOpen() {
    return localStorage.getItem(STORAGE_KEY) === "1";
  }

  function setOpen(open) {
    if (open) {
      document.documentElement.classList.add(OPEN_CLASS);
      localStorage.setItem(STORAGE_KEY, "1");
    } else {
      document.documentElement.classList.remove(OPEN_CLASS);
      localStorage.setItem(STORAGE_KEY, "0");
    }
    const toggle = document.getElementById("shipit-toc-toggle");
    if (toggle) {
      toggle.textContent = open ? TOGGLE_LABEL_OPEN : TOGGLE_LABEL_CLOSED;
      toggle.setAttribute("aria-pressed", open ? "true" : "false");
    }
  }

  function buildToggle() {
    if (document.getElementById("shipit-toc-toggle")) return;
    const button = document.createElement("button");
    button.id = "shipit-toc-toggle";
    button.type = "button";
    button.className = "shipit-toc-toggle";
    button.setAttribute("aria-label", "Toggle table of contents");
    button.setAttribute("title", "Toggle table of contents");
    button.textContent = isOpen() ? TOGGLE_LABEL_OPEN : TOGGLE_LABEL_CLOSED;
    button.addEventListener("click", () => setOpen(!isOpen()));
    document.body.appendChild(button);
  }

  // mkdocs-material's instant navigation re-runs scripts on each page
  // load via this hook; fall back to DOMContentLoaded for the initial load.
  function init() {
    setOpen(isOpen());
    buildToggle();
  }

  if (window.document$ && typeof window.document$.subscribe === "function") {
    window.document$.subscribe(init);
  } else if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
