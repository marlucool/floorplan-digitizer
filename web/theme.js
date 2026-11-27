/* One shared theme controller for every Planline workspace. */
(() => {
  const root = document.documentElement;
  const button = document.querySelector("#themeToggle");
  const header = document.querySelector(".topbar");
  const links = document.querySelector(".top-links");
  const menu = header?.querySelector(".nav-menu-toggle");
  if (header && links && menu) {
    const closeMenu = () => {
      header.classList.remove("menu-open");
      menu.setAttribute("aria-expanded", "false");
      menu.setAttribute("aria-label", "Open navigation");
    };
    menu.addEventListener("click", () => {
      const open = header.classList.toggle("menu-open");
      menu.setAttribute("aria-expanded", String(open));
      menu.setAttribute("aria-label", open ? "Close navigation" : "Open navigation");
    });
    links.addEventListener("click", (event) => {
      if (event.target.closest("a")) closeMenu();
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") closeMenu();
    });
    document.addEventListener("click", (event) => {
      if (!header.contains(event.target)) closeMenu();
    });
  }
  const meta = document.querySelector('meta[name="theme-color"]');
  const key = "planline-theme-v2";
  const moon = '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M20.2 15.1A8.5 8.5 0 0 1 8.9 3.8 8.7 8.7 0 1 0 20.2 15.1Z"/></svg>';
  const sun = '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M4.93 4.93l1.42 1.42m11.3 11.3 1.42 1.42M2 12h2m16 0h2M4.93 19.07l1.42-1.42m11.3-11.3 1.42 1.42"/></svg>';

  function applyTheme(theme, persist = false) {
    const dark = theme !== "light";
    const value = dark ? "dark" : "light";
    root.dataset.theme = value;
    if (meta) meta.content = dark ? "#07090f" : "#f5f6fb";
    if (button) {
      button.innerHTML = dark ? sun : moon;
      button.setAttribute("aria-label", dark ? "Switch to light theme" : "Switch to dark theme");
      button.setAttribute("title", dark ? "Switch to light theme" : "Switch to dark theme");
      button.setAttribute("aria-pressed", String(dark));
    }
    if (persist) {
      try { localStorage.setItem(key, value); } catch (_) { /* Theme still applies for this session. */ }
    }
  }

  applyTheme(root.dataset.theme || "dark");
  button?.addEventListener("click", () => {
    applyTheme(root.dataset.theme === "dark" ? "light" : "dark", true);
  });
})();
