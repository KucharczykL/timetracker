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

  const close = () => {
    menu.hidden = true;
  };

  toggle.addEventListener("click", (event) => {
    event.stopPropagation();
    menu.hidden = !menu.hidden;
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
