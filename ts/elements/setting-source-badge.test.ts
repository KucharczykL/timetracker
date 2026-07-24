// @vitest-environment jsdom
import { beforeEach, describe, expect, it } from "vitest";
import {
  dispatchSettingCommitted,
  parseResolvedSetting,
} from "../settings-events.js";
import "./setting-source-badge.js";

function mountBadges(): HTMLElement[] {
  document.body.innerHTML = `
    <setting-source-badge key="THEME" namespace="user">
      <pop-over>
        <button data-pop-over-trigger aria-label="Default source">
          <span data-setting-origin="default"
              class="bg-neutral-quaternary text-heading">
            <span data-setting-source-label>Default</span>
          </span>
        </button>
        <div data-pop-over-panel>
          <dl><div data-setting-source-description><dt>Source</dt>
            <dd>The built-in default.</dd></div>
            <div data-setting-source-status hidden><dt>Status</dt><dd>Status</dd></div>
          </dl>
        </div>
      </pop-over>
    </setting-source-badge>
    <setting-source-badge key="PAGE_SIZE" namespace="user">
      <pop-over><button data-pop-over-trigger aria-label="Default source">
        <span data-setting-origin="default" class="bg-neutral-quaternary text-heading">
          <span data-setting-source-label>Default</span>
        </span>
      </button><div data-pop-over-panel><dl>
        <div data-setting-source-description><dd>The built-in default.</dd></div>
        <div data-setting-source-status hidden><dd>Status</dd></div>
      </dl></div></pop-over>
    </setting-source-badge>`;
  return Array.from(document.querySelectorAll<HTMLElement>("setting-source-badge"));
}

beforeEach(() => document.body.replaceChildren());

describe("resolved setting events", () => {
  it("accepts only complete payloads with recognized sources and namespaces", () => {
    expect(parseResolvedSetting({
      key: "THEME",
      value: "dark",
      source: "user",
      locked: false,
      namespace: "user",
    })).toEqual({
      key: "THEME", value: "dark", source: "user", locked: false, namespace: "user",
    });

    for (const invalid of [
      null,
      { key: "THEME", value: "dark", source: "mystery", locked: false, namespace: "user" },
      { key: "THEME", value: { nested: true }, source: "user", locked: false, namespace: "user" },
      { key: "", value: "dark", source: "user", locked: false, namespace: "user" },
      { key: "THEME", value: "dark", source: "user", namespace: "user" },
      { key: "THEME", value: "dark", source: "user", locked: false },
      { key: "THEME", value: "dark", source: "user", locked: false, namespace: "planet" },
    ]) {
      expect(() => parseResolvedSetting(invalid)).toThrow("Invalid resolved setting");
    }
  });

  it("updates only the matching badge from a committed event", () => {
    const [theme, pageSize] = mountBadges();

    dispatchSettingCommitted({
      key: "THEME",
      value: "dark",
      source: "user",
      locked: false,
      namespace: "user",
    });

    expect(theme.querySelector("[data-setting-source-label]")?.textContent).toBe(
      "Personal",
    );
    expect(theme.querySelector<HTMLElement>("[data-setting-origin]")?.dataset.settingOrigin)
      .toBe("user");
    expect(theme.querySelector("[data-pop-over-trigger]")?.getAttribute("aria-label"))
      .toBe("Personal source");
    expect(theme.querySelector("[data-setting-source-description] dd")?.textContent)
      .toBe("Saved for your account and overrides the site default.");
    expect(theme.querySelector<HTMLElement>("[data-setting-source-status]")?.hidden)
      .toBe(false);
    expect(pageSize.querySelector("[data-setting-source-label]")?.textContent)
      .toBe("Default");
  });

  it("ignores a same-key event from a different namespace", () => {
    document.body.innerHTML = `
    <setting-source-badge key="THEME" namespace="site">
      <pop-over>
        <button data-pop-over-trigger aria-label="Default source">
          <span data-setting-origin="default"
              class="bg-neutral-quaternary text-heading">
            <span data-setting-source-label>Default</span>
          </span>
        </button>
        <div data-pop-over-panel>
          <dl><div data-setting-source-description><dt>Source</dt>
            <dd>The built-in default.</dd></div>
            <div data-setting-source-status hidden><dt>Status</dt><dd>Status</dd></div>
          </dl>
        </div>
      </pop-over>
    </setting-source-badge>`;
    const badge = document.querySelector<HTMLElement>("setting-source-badge")!;

    dispatchSettingCommitted({
      key: "THEME",
      value: "dark",
      source: "user",
      locked: false,
      namespace: "user",
    });

    expect(badge.querySelector("[data-setting-source-label]")?.textContent).toBe(
      "Default",
    );
    expect(
      badge.querySelector<HTMLElement>("[data-setting-origin]")?.dataset.settingOrigin,
    ).toBe("default");
  });
});
