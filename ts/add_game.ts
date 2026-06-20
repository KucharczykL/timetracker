import { syncSelectInputUntilChanged } from "./utils.js";

const syncData = [
  {
    source: "#id_name",
    source_value: "value",
    target: "#id_sort_name",
    target_value: "value",
  },
];

// Scope to the add form (#add-form), not "form": the first <form> on the page
// is the navbar logout form, which never contains these fields.
syncSelectInputUntilChanged(syncData, "#add-form");
