// @vitest-environment jsdom
import { readFileSync } from "node:fs";
import { beforeEach, describe, expect, it, vi } from "vitest";

const compiledBootstrap = (): string =>
  readFileSync("games/static/js/dist/theme-bootstrap.js", "utf8");

function configureRoot(mode: "account" | "browser", preference = ""): void {
  const root = document.documentElement;
  root.className = "";
  root.dataset.themeMode = mode;
  root.dataset.themePreferences = "system light dark";
  if (preference) root.dataset.themePreference = preference;
  else delete root.dataset.themePreference;
}

function runBootstrap(): void {
  window.eval(compiledBootstrap());
}

beforeEach(() => {
  localStorage.clear();
  configureRoot("browser");
  window.matchMedia = vi.fn().mockReturnValue({ matches: false });
});

describe("classic theme bootstrap", () => {
  it("uses account state even when anonymous storage is stale", () => {
    configureRoot("account", "dark");
    localStorage.setItem("color-theme", "light");

    runBootstrap();

    expect(document.documentElement.dataset.themePreference).toBe("dark");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
  });

  it("uses valid browser storage", () => {
    localStorage.setItem("color-theme", "light");

    runBootstrap();

    expect(document.documentElement.dataset.themePreference).toBe("light");
    expect(document.documentElement.classList.contains("dark")).toBe(false);
  });

  it("falls back to System and resolves the OS color scheme", () => {
    localStorage.setItem("color-theme", "invalid");
    window.matchMedia = vi.fn().mockReturnValue({ matches: true });

    runBootstrap();

    expect(document.documentElement.dataset.themePreference).toBe("system");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
  });

  it("does not read anonymous storage for an invalid document mode", () => {
    configureRoot("browser");
    document.documentElement.dataset.themeMode = "invalid";
    localStorage.setItem("color-theme", "dark");

    runBootstrap();

    expect(document.documentElement.dataset.themePreference).toBe("system");
    expect(document.documentElement.classList.contains("dark")).toBe(false);
  });
});
