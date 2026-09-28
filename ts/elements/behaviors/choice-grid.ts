import { registerBehavior } from "../dropdown-behaviors.js";

// Choice-grid dropdown: the [data-menu] panel is a dialog holding one group
// of native radios laid out as a grid (the icon picker).
//
// - a match-nothing `itemSelector`, so attachMenu's roving navigation stays
//   off: the radio group owns the arrow keys, and moving the choice with them
//   reflects it on the trigger without closing;
// - a pointer pick, or Enter or Space on a tile, closes the panel and returns
//   focus to the trigger. Enter is kept from submitting the ancestor form;
// - on open, focus lands on the checked tile.

const RADIO = 'input[type="radio"]';

/** Copy a tile's glyph and name onto the trigger. */
export function reflectChoice(toggle: HTMLElement, radio: HTMLInputElement): void {
  const glyph = toggle.querySelector("[data-choice-grid-glyph]");
  const tileGlyph = radio.parentElement?.querySelector("[data-choice-grid-glyph]");
  if (glyph) glyph.innerHTML = tileGlyph ? tileGlyph.innerHTML : "";
  const label = toggle.querySelector("[data-choice-grid-label]");
  if (label) label.textContent = radio.dataset.choiceLabel ?? radio.value;
}

registerBehavior("choice-grid", {
  menuOptions: () => ({
    itemSelector: "[data-choice-grid-no-items]",
    keepOpenOnTab: true,
  }),
  wire: ({ host, toggle, menu, controller }) => {
    const pick = () => {
      controller.close();
      toggle.focus();
    };
    const onShow = () => {
      const checked =
        menu.querySelector<HTMLInputElement>(`${RADIO}:checked`) ??
        menu.querySelector<HTMLInputElement>(RADIO);
      checked?.focus();
    };
    const onChange = (event: Event) => {
      const radio = event.target;
      if (radio instanceof HTMLInputElement && radio.type === "radio") {
        reflectChoice(toggle, radio);
      }
    };
    const onClick = (event: MouseEvent) => {
      // An arrow key also clicks a radio, with no pointer detail.
      if (event.detail === 0) return;
      if (event.target instanceof HTMLInputElement && event.target.type === "radio") {
        pick();
      }
    };
    const onKeydown = (event: KeyboardEvent) => {
      const radio = event.target;
      if (!(radio instanceof HTMLInputElement) || radio.type !== "radio") return;
      if (event.key !== "Enter" && event.key !== " ") return;
      event.preventDefault();
      if (!radio.checked) {
        radio.checked = true;
        radio.dispatchEvent(new Event("change", { bubbles: true }));
      }
      pick();
    };
    host.addEventListener("dropdown:show", onShow);
    menu.addEventListener("change", onChange);
    menu.addEventListener("click", onClick);
    menu.addEventListener("keydown", onKeydown);
    return () => {
      host.removeEventListener("dropdown:show", onShow);
      menu.removeEventListener("change", onChange);
      menu.removeEventListener("click", onClick);
      menu.removeEventListener("keydown", onKeydown);
    };
  },
});
