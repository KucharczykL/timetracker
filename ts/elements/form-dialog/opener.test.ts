// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";

import { focusOpener } from "./opener.js";

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

  it("falls back to the page when no link with the href is reachable", () => {
    document.body.innerHTML = `<main id="main-container" tabindex="-1"><a href="/edit" id="only" hidden>Edit</a></main>`;
    focusOpener({ id: null, href: "/edit" });
    expect(document.activeElement?.id).toBe("main-container");
  });
});
