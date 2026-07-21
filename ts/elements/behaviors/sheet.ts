import { registerBehavior } from "../dropdown-behaviors.js";
import { attachSheet } from "../sheet-controller.js";

registerBehavior("sheet", {
  createController: (host, toggle, menu) => attachSheet(host, toggle, menu),
});
