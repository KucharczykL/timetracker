import { toISOUTCString } from "./utils.js";

for (let button of document.querySelectorAll("[data-target]")) {
  let target = button.getAttribute("data-target");
  let type = button.getAttribute("data-type");
  let targetElement = document.querySelector(`#id_${target}`);
  button.addEventListener("click", (event) => {
    event.preventDefault();
    if (type == "now") {
      targetElement.value = toISOUTCString(new Date());
    } else if (type == "copy") {
      const oppositeName =
        targetElement.name == "timestamp_start"
          ? "timestamp_end"
          : "timestamp_start";
      document.querySelector(`[name='${oppositeName}']`).value =
        targetElement.value;
    } else if (type == "toggle") {
      if (targetElement.type == "datetime-local") targetElement.type = "text";
      else targetElement.type = "datetime-local";
    }
  });
}
