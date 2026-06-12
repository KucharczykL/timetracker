import { getEl, disableElementsWhenTrue, onSwap } from "./utils.js";

const RELATED_PURCHASE_URL = "/tracker/purchase/related-purchase-by-game";

// The games field is now a SearchSelect widget (a <div>, not a <select>), so we
// react to its custom "search-select:change" event instead of syncing a select.
document.addEventListener("search-select:change", (event) => {
  if (event.detail.name !== "games") return;

  // (a) Auto-fill platform from the clicked option's data-platform.
  const last = event.detail.last;
  const platformId = last && last.data ? last.data.platform : "";
  if (platformId) {
    const platformEl = getEl("#id_platform");
    if (platformEl) platformEl.value = platformId;
  }

  // (b) Refresh #id_related_purchase for the currently selected games.
  const query = event.detail.values
    .map((value) => "games=" + encodeURIComponent(value))
    .join("&");
  fetch(RELATED_PURCHASE_URL + "?" + query, { credentials: "same-origin" })
    .then((response) => {
      if (response.status === 204) return null;
      return response.text();
    })
    .then((html) => {
      if (html === null) return;
      const target = getEl("#id_related_purchase");
      if (target) target.outerHTML = html;
    });
});

function setupElementHandlers() {
  disableElementsWhenTrue("#id_type", "game", [
    "#id_name",
    "#id_related_purchase",
  ]);
}

onSwap("#id_type", (typeSelect) => {
  setupElementHandlers();
  typeSelect.addEventListener("change", () => {
    setupElementHandlers();
  });
});
