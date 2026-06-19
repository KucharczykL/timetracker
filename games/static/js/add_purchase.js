import { getEl, disableElementsWhenTrue, onSwap } from "./utils.js";

// Switch between a single bundle price and one price per game. The per-game
// inputs are the selection-fields element; this only sets the policy: the
// hidden pricing_mode the view reads, the element's "active" flag, and whether
// the bundle Price field is shown.
function applyPricingMode(separate) {
  const pricingMode = getEl("#id_pricing_mode");
  if (pricingMode) pricingMode.value = separate ? "per_game" : "combined";

  const selectionFields = document.querySelector("selection-fields");
  if (selectionFields)
    selectionFields.setAttribute("active", separate ? "true" : "false");

  const priceInput = getEl("#id_price");
  if (priceInput) {
    const wrapper = priceInput.closest("div");
    if (wrapper) wrapper.classList.toggle("hidden", separate);
  }
}

// The games field is now a SearchSelect widget (a <div>, not a <select>), so we
// react to its custom "search-select:change" event instead of syncing a select.
document.addEventListener("search-select:change", (event) => {
  if (event.detail.name !== "games") return;

  // Auto-fill platform from the clicked option's data-platform.
  const last = event.detail.last;
  const platformId = last && last.data ? last.data.platform : "";
  if (platformId) {
    const platformEl = getEl("#id_platform");
    if (platformEl) platformEl.value = platformId;
  }

  // The combined/per-game choice is only meaningful with 2+ games. Reveal the
  // checkbox there; below the threshold, fall back to a single bundle price.
  const separateRow = getEl("#separate-prices-row");
  const multipleGames = event.detail.values.length >= 2;
  if (separateRow) separateRow.classList.toggle("hidden", !multipleGames);
  if (!multipleGames) {
    const checkbox = getEl("#id_separate_prices");
    if (checkbox) checkbox.checked = false;
    applyPricingMode(false);
  }
});

onSwap("#id_separate_prices", (checkbox) => {
  checkbox.addEventListener("change", () => applyPricingMode(checkbox.checked));
});

function setupElementHandlers() {
  disableElementsWhenTrue("#id_type", "game", [
    "#id_name",
    "#id_related_game",
  ]);
}

onSwap("#id_type", (typeSelect) => {
  setupElementHandlers();
  typeSelect.addEventListener("change", () => {
    setupElementHandlers();
  });
});
