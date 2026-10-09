// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const reportClientError = vi.hoisted(() => vi.fn());

vi.mock("../../client-errors.js", () => ({ reportClientError }));

import { focusOpener } from "./opener.js";

beforeEach(() => {
  reportClientError.mockClear();
});

afterEach(() => {
  document.body.innerHTML = "";
});

describe("focusOpener", () => {
  it("takes the second link with the href when the first is not rendered", () => {
    document.body.innerHTML = `
      <main id="main-container">
        <drop-down>
          <button data-toggle id="toggle">Menu</button>
          <div data-menu><a href="/edit" id="first">Edit</a></div>
        </drop-down>
        <a href="/edit" id="second">Edit</a>
      </main>`;
    const first = document.getElementById("first") as HTMLElement;
    const toggle = document.getElementById("toggle") as HTMLElement;
    first.checkVisibility = () => false;
    toggle.checkVisibility = () => false;

    focusOpener({ id: null, href: "/edit" });

    expect(document.activeElement?.id).toBe("second");
  });

  it("focuses the opener by id when it is reachable", () => {
    document.body.innerHTML = `
      <main id="main-container" tabindex="-1">
        <button id="opener">Edit</button>
        <a href="/edit" id="other">Edit</a>
      </main>`;
    const opener = document.getElementById("opener") as HTMLElement;
    opener.checkVisibility = () => true;

    focusOpener({ id: "opener", href: "/edit" });

    expect(document.activeElement?.id).toBe("opener");
    expect(reportClientError).not.toHaveBeenCalled();
  });

  it("falls through to the href link when the id is present but unreachable", () => {
    document.body.innerHTML = `
      <main id="main-container" tabindex="-1">
        <button id="opener" hidden>Edit</button>
        <a href="/edit" id="link">Edit</a>
      </main>`;
    const opener = document.getElementById("opener") as HTMLElement;
    opener.checkVisibility = () => false;

    focusOpener({ id: "opener", href: "/edit" });

    expect(document.activeElement?.id).toBe("link");
  });

  it("falls back to the page when no link with the href is reachable", () => {
    document.body.innerHTML = `<main id="main-container" tabindex="-1"><a href="/edit" id="only" hidden>Edit</a></main>`;
    focusOpener({ id: null, href: "/edit" });
    expect(document.activeElement?.id).toBe("main-container");
  });

  it("reports a fallback when the opener is still rendered but unreachable", () => {
    document.body.innerHTML = `<main id="main-container" tabindex="-1"><dialog><a href="/edit" id="only">Edit</a></dialog></main>`;
    const link = document.getElementById("only") as HTMLElement;
    link.checkVisibility = () => true;
    focusOpener({ id: null, href: "/edit" });
    expect(document.activeElement?.id).toBe("main-container");
    expect(reportClientError).toHaveBeenCalledTimes(1);
  });

  it("does not report a fallback when the opener row was removed", () => {
    document.body.innerHTML = `<main id="main-container" tabindex="-1"></main>`;
    focusOpener({ id: "gone", href: "/edit" });
    expect(document.activeElement?.id).toBe("main-container");
    expect(reportClientError).not.toHaveBeenCalled();
  });

  it("reports when a reachable target does not take focus", () => {
    document.body.innerHTML = `<main id="main-container" tabindex="-1"><div id="opener">Edit</div></main>`;
    const opener = document.getElementById("opener") as HTMLElement;
    opener.checkVisibility = () => true;

    focusOpener({ id: "opener", href: null });

    expect(document.activeElement?.id).not.toBe("opener");
    expect(reportClientError).toHaveBeenCalledTimes(1);
  });
});
