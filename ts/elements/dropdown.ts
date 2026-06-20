export interface DropdownConfig {
  patchUrl: string;
  bodyKey: string; // server field name, e.g. "status" or "device_id"
  event: string; // dispatched on document.body after a successful PATCH
  csrf: string;
  numericValue?: boolean; // parse the option value as a number
}

// Wires a light-DOM value-selector dropdown that lives inside `host`.
// Markup hooks (rendered server-side): [data-toggle], [data-menu],
// [data-label], and one or more [data-option][data-value].
export function initDropdown(host: HTMLElement, config: DropdownConfig): void {
  const toggle = host.querySelector<HTMLElement>("[data-toggle]");
  const menu = host.querySelector<HTMLElement>("[data-menu]");
  const label = host.querySelector<HTMLElement>("[data-label]");
  if (!toggle || !menu || !label) return;

  // The menu lives inside the table's `overflow-x-auto` wrapper, which forces
  // `overflow-y: auto` and clips an absolutely-positioned menu that extends
  // past a short table (issue #39). Position it `fixed` while open so it
  // escapes the clipping ancestor, anchored to the toggle and bounded to the
  // viewport (flipping up when there is more room above).
  const VIEWPORT_MARGIN = 8;

  const positionMenu = (): void => {
    const rect = toggle.getBoundingClientRect();
    const spaceBelow = window.innerHeight - rect.bottom - VIEWPORT_MARGIN;
    const spaceAbove = rect.top - VIEWPORT_MARGIN;
    const openUp = menu.scrollHeight > spaceBelow && spaceAbove > spaceBelow;

    menu.style.position = "fixed";
    menu.style.left = `${rect.left}px`;
    menu.style.width = `${rect.width}px`;
    menu.style.maxHeight = `${Math.max(0, openUp ? spaceAbove : spaceBelow)}px`;
    menu.style.overflowY = "auto";
    if (openUp) {
      menu.style.top = "";
      menu.style.bottom = `${window.innerHeight - rect.top}px`;
    } else {
      menu.style.bottom = "";
      menu.style.top = `${rect.bottom}px`;
    }
  };

  const clearPosition = (): void => {
    for (const property of [
      "position",
      "top",
      "bottom",
      "left",
      "width",
      "max-height",
      "overflow-y",
    ]) {
      menu.style.removeProperty(property);
    }
  };

  const reposition = (): void => {
    if (!menu.hidden) positionMenu();
  };

  const open = (): void => {
    menu.hidden = false;
    positionMenu();
    // Capture-phase scroll listener so scrolling any ancestor (incl. the table
    // wrapper) keeps the fixed menu anchored to its toggle.
    window.addEventListener("scroll", reposition, true);
    window.addEventListener("resize", reposition);
  };

  const close = (): void => {
    menu.hidden = true;
    clearPosition();
    window.removeEventListener("scroll", reposition, true);
    window.removeEventListener("resize", reposition);
  };

  toggle.addEventListener("click", (event) => {
    event.stopPropagation();
    if (menu.hidden) open();
    else close();
  });
  document.addEventListener("click", (event) => {
    if (!host.contains(event.target as Node)) close();
  });

  host.querySelectorAll<HTMLElement>("[data-option]").forEach((option) => {
    option.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      const raw = option.dataset.value ?? "";
      label.innerHTML = option.innerHTML;
      close();
      const body: Record<string, unknown> = {
        [config.bodyKey]: config.numericValue ? Number(raw) : raw,
      };
      window
        .fetchWithHtmxTriggers(config.patchUrl, {
          method: "PATCH",
          headers: { "Content-Type": "application/json", "X-CSRFToken": config.csrf },
          body: JSON.stringify(body),
        })
        .then(() => document.body.dispatchEvent(new CustomEvent(config.event)))
        .catch(() => console.error("Failed to update", config.patchUrl));
    });
  });
}
