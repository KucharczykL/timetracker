import { syncSelectInputUntilChanged, getEl, conditionalElementHandler } from "./utils.js";

let syncData = [
  {
    source: "#id_edition",
    source_value: "dataset.platform",
    target: "#id_platform",
    target_value: "value",
  },
];

syncSelectInputUntilChanged(syncData, "form");


let myConfig = [
  () => {
    return getEl("#id_type").value == "game";
  },
  ["#id_name", "#id_related_purchase"],
  (el) => {
    el.disabled = "disabled";
  },
  (el) => {
    el.disabled = "";
  }
]

document.DOMContentLoaded = conditionalElementHandler(...myConfig)
getEl("#id_type").onchange = () => {
  conditionalElementHandler(...myConfig)
}
