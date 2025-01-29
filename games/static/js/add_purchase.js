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
  disableElementsWhenValueNotEqual(
    "#id_type",
    ["game", "dlc"],
    ["#id_date_finished"]
  );
}

document.addEventListener("DOMContentLoaded", setupElementHandlers);
document.addEventListener("htmx:afterSwap", setupElementHandlers);
getEl("#id_type").onchange = () => {
  setupElementHandlers();
};

document.body.addEventListener("htmx:beforeRequest", function (event) {
  // Assuming 'Purchase1' is the element that triggers the HTMX request
  if (event.target.id === "id_games") {
    var idEditionValue = document.getElementById("id_games").value;

    // Condition to check - replace this with your actual logic
    if (idEditionValue != "") {
      event.preventDefault(); // This cancels the HTMX request
    }
  }
});
