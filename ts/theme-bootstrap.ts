(() => {
  const root = document.documentElement;
  const allowed = new Set(
    (root.dataset.themePreferences ?? "").split(" ").filter(Boolean),
  );
  const isAllowed = (value: string | null | undefined): value is string =>
    typeof value === "string" && allowed.has(value);

  let preference: string | null = null;
  if (root.dataset.themeMode === "account") {
    preference = isAllowed(root.dataset.themePreference)
      ? root.dataset.themePreference
      : null;
  } else {
    try {
      const stored = localStorage.getItem("color-theme");
      preference = isAllowed(stored) ? stored : null;
    } catch (_error) {
      // Browser privacy policies may make storage unavailable.
    }
  }

  preference = preference ?? "system";
  root.dataset.themePreference = preference;
  const systemDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  root.classList.toggle(
    "dark",
    preference === "dark" || (preference === "system" && systemDark),
  );
})();
