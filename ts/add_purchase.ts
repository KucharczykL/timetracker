import { disableElementsWhenTrue, onSwap } from "./utils.js";
import type { SearchSelectChangeDetail } from "./elements/search-select.js";

// Switch between a single bundle price and one price per game. The per-game
// inputs are the selection-fields element; this only sets the policy: the
// hidden pricing_mode the view reads, the element's "active" flag, and whether
// the bundle Price field is shown.
function applyPricingMode(separate: boolean): void {
  const pricingMode = document.querySelector<HTMLInputElement>("#id_pricing_mode");
  if (pricingMode) pricingMode.value = separate ? "per_game" : "combined";

  const selectionFields = document.querySelector("selection-fields");
  if (selectionFields)
    selectionFields.setAttribute("active", separate ? "true" : "false");

  const priceInput = document.querySelector<HTMLInputElement>("#id_price");
  if (priceInput) {
    const wrapper = priceInput.closest("div");
    if (wrapper) wrapper.classList.toggle("hidden", separate);
  }
}

// The games field is a SearchSelect widget (a <div>, not a <select>), so we
// react to its custom "search-select:change" event instead of syncing a select.
document.addEventListener("search-select:change", (event) => {
  const detail = (event as CustomEvent<SearchSelectChangeDetail>).detail;
  if (detail.name !== "games") return;

  // Auto-fill platform from the clicked option's data-platform.
  const last = detail.last;
  const platformId = last && last.data ? last.data.platform : "";
  if (platformId) {
    const platformElement = document.querySelector<HTMLInputElement>("#id_platform");
    if (platformElement) platformElement.value = platformId;
  }

  // The combined/per-game choice is only meaningful with 2+ games. Reveal the
  // checkbox there; below the threshold, fall back to a single bundle price.
  const separateRow = document.querySelector<HTMLElement>("#separate-prices-row");
  const multipleGames = detail.values.length >= 2;
  if (separateRow) separateRow.classList.toggle("hidden", !multipleGames);
  if (!multipleGames) {
    const checkbox = document.querySelector<HTMLInputElement>("#id_separate_prices");
    if (checkbox) checkbox.checked = false;
    applyPricingMode(false);
  }
});

onSwap("#id_separate_prices", (checkbox) => {
  checkbox.addEventListener("change", () =>
    applyPricingMode((checkbox as HTMLInputElement).checked)
  );
});

function setupElementHandlers(): void {
  disableElementsWhenTrue("#id_type", "game", ["#id_name", "#id_related_game"]);
}

onSwap("#id_type", (typeSelect) => {
  setupElementHandlers();
  typeSelect.addEventListener("change", () => {
    setupElementHandlers();
  });
});
