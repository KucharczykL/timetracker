import {
  syncSelectInputUntilChanged,
  getEl,
  disableElementsWhenTrue,
  disableElementsWhenFalse,
} from "./utils.js";

let syncData = [
  {
    source: "#id_edition",
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
  disableElementsWhenFalse("#id_type", "game", ["#id_date_finished"]);
}

document.addEventListener("DOMContentLoaded", setupElementHandlers);
getEl("#id_type").onchange = () => {
  setupElementHandlers();
};
