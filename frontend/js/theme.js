/* Loaded in <head> so there is no white flash in dark mode. Saved in localStorage; default = OS setting. */
(function () {
  const saved = localStorage.getItem("tp_theme");
  const dark = saved ? saved === "dark" : window.matchMedia("(prefers-color-scheme: dark)").matches;
  document.documentElement.dataset.theme = dark ? "dark" : "light";
  window.toggleTheme = function () {
    const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    document.documentElement.classList.add("theme-anim");
    document.documentElement.dataset.theme = next;
    localStorage.setItem("tp_theme", next);
    setTimeout(() => document.documentElement.classList.remove("theme-anim"), 400);
  };
})();
