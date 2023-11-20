import { syncSelectInputUntilChanged } from "./utils.js";

let syncData = [
  {
    source: "#id_name",
    source_value: "value",
    target: "#id_sort_name",
    target_value: "value",
  },
];

syncSelectInputUntilChanged(syncData, "form");
