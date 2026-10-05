/** Initializes matches present once parsing ends. */
function onReady(selector: string, initializeElement: (element: Element) => void) {
  const run = () => {
    for (const element of document.querySelectorAll(selector)) {
      initializeElement(element);
    }
  };
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", run, { once: true });
  } else {
    run();
  }
}

/**
 * The current instant as a real ISO-8601 UTC string (…Z) for the JSON API. Use
 * this — NOT toISOUTCString — when sending a timestamp to the server: the client
 * owns "now", and the API stores the true instant. (toISOUTCString emits the
 * offset-less datetime-local form, which would be read as the wrong instant.)
 */
function nowISOUTC(): string {
  return new Date().toISOString();
}

/** Formats Date to a UTC string accepted by the datetime-local input field. */
function toISOUTCString(date: Date): string {
  function stringAndPad(number: number) {
    return number.toString().padStart(2, "0");
  }
  const year = date.getFullYear();
  const month = stringAndPad(date.getMonth() + 1);
  const day = stringAndPad(date.getDate());
  const hours = stringAndPad(date.getHours());
  const minutes = stringAndPad(date.getMinutes());
  return `${year}-${month}-${day}T${hours}:${minutes}`;
}

type ElementHandlerConfig = [
  condition: () => boolean, // condition function
  targetElements: string[], // array of target element selectors
  callbackfn1: (el: HTMLElement) => void, // callback function for matched condition
  callbackfn2: (el: HTMLElement) => void // callback function for unmatched condition
];

/**
 * For each config, runs callbackfn1 on every target element when condition()
 * is true, callbackfn2 otherwise. See ElementHandlerConfig for the tuple shape.
 */
function conditionalElementHandler(...configs: ElementHandlerConfig[]) {
  configs.forEach(([condition, targetElements, callbackfn1, callbackfn2]) => {
    if (condition()) {
      targetElements.forEach((elementName) => {
        let el = document.querySelector<HTMLElement>(elementName);
        if (el === null) {
          console.error(`Element ${elementName} doesn't exist.`);
        } else {
          callbackfn1(el);
        }
      });
    } else {
      targetElements.forEach((elementName) => {
        let el = document.querySelector<HTMLElement>(elementName);
        if (el === null) {
          console.error(`Element ${elementName} doesn't exist.`);
        } else {
          callbackfn2(el);
        }
      });
    }
  });
}

export {
  onReady,
  nowISOUTC,
  toISOUTCString,
  conditionalElementHandler,
};
