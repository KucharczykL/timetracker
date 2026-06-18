import { getEl, disableElementsWhenTrue, onSwap } from "./utils.js";

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
