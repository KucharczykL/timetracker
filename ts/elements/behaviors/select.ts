import { registerBehavior } from "../dropdown-behaviors.js";
import { MenuOptions } from "../menu-behavior.js";

// Value-selector behavior: pick an option → swap the toggle label, reflect the
// selection (aria-selected), close, PATCH the server, and fire the body event
// that drives cross-widget htmx refresh. Config comes from data-* on the host.
registerBehavior("select", {
  menuOptions: (): Partial<MenuOptions> => ({
    itemSelector: "[data-option]",
    matchToggleWidth: true,
  }),
  wire: ({ host, controller }) => {
    const label = host.querySelector<HTMLElement>("[data-label]");
    const patchUrl = host.dataset.patchUrl ?? "";
    const bodyKey = host.dataset.bodyKey ?? "";
    const event = host.dataset.event ?? "";
    const csrf = host.dataset.csrf ?? "";
    const numeric = host.dataset.numeric === "true";
    const options = Array.from(host.querySelectorAll<HTMLElement>("[data-option]"));

    const handlers: Array<[HTMLElement, (event: Event) => void]> = [];
    for (const option of options) {
      const handler = (clickEvent: Event) => {
        clickEvent.preventDefault();
        clickEvent.stopPropagation();
        const rawValue = option.dataset.value ?? "";
        if (label) label.innerHTML = option.innerHTML;
        for (const other of options) {
          other.setAttribute("aria-selected", other === option ? "true" : "false");
        }
        controller.close();
        window
          .fetchWithHtmxTriggers(patchUrl, {
            method: "PATCH",
            headers: { "Content-Type": "application/json", "X-CSRFToken": csrf },
            body: JSON.stringify({ [bodyKey]: numeric ? Number(rawValue) : rawValue }),
          })
          .then(() => document.body.dispatchEvent(new CustomEvent(event)))
          .catch(() => console.error("Failed to update", patchUrl));
      };
      option.addEventListener("click", handler);
      handlers.push([option, handler]);
    }
    return () => {
      for (const [option, handler] of handlers) {
        option.removeEventListener("click", handler);
      }
    };
  },
});
