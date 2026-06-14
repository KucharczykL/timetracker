// import { toISOUTCString } from "../../games/static/js/utils.js";

/**
 * @description Formats Date to a UTC string accepted by the datetime-local input field.
 * @param {Date} date
 * @returns {string}
 */
function toISOUTCString(date: Date): string {
    function stringAndPad(number: number): string {
        return number.toString().padStart(2, "0");
    }
    const year = date.getFullYear();
    const month = stringAndPad(date.getMonth() + 1);
    const day = stringAndPad(date.getDate());
    const hours = stringAndPad(date.getHours());
    const minutes = stringAndPad(date.getMinutes());
    return `${year}-${month}-${day}T${hours}:${minutes}`;
}

class SessionTimestampButtonsElement extends HTMLElement {
    connectedCallback(): void {
        for (const button of this.querySelectorAll("[data-target]")) {
            const target = button.getAttribute("data-target");
            const type = button.getAttribute("data-type");
            if (!target || !type) continue;
            const targetElement = document.querySelector(`#id_${target}`);
            if (!(targetElement instanceof HTMLInputElement)) return;
            button.addEventListener("click", (event) => {
                event.preventDefault();
                if (type == "now") {
                    targetElement.value = toISOUTCString(new Date());
                } else if (type == "copy") {
                    const oppositeName =
                        targetElement.name == "timestamp_start"
                            ? "timestamp_end"
                            : "timestamp_start";
                    const opposite = document.querySelector(`[name='${oppositeName}']`);
                    if (!(opposite instanceof HTMLInputElement)) return;
                    opposite.value = targetElement.value;
                } else if (type == "toggle") {
                    if (targetElement.type == "datetime-local") targetElement.type = "text";
                    else targetElement.type = "datetime-local";
                }
            });
        }
    }
}

customElements.define("session-timestamp-buttons", SessionTimestampButtonsElement);
