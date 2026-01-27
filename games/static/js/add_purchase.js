import {
  syncSelectInputUntilChanged,
  getEl,
  disableElementsWhenTrue,
  disableElementsWhenValueNotEqual,
} from "./utils.js";

let syncData = [
  {
    source: "#id_games",
    source_value: "dataset.platform",
    target: "#id_platform",
    target_value: "value",
  },
];

syncSelectInputUntilChanged(syncData, "form");

function setupElementHandlers() {
  disableElementsWhenTrue("#id_type", "game", [
    "#id_name",
    "#id_related_purchase",
  ]);
}

document.addEventListener("DOMContentLoaded", setupElementHandlers);
document.addEventListener("htmx:afterSwap", setupElementHandlers);
getEl("#id_type").addEventListener("change", () => {
  setupElementHandlers();
}
);
