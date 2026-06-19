declare const htmx: any;


/**
 * Runs initializeElement once for each element matching selector, on initial
 * page load and inside every htmx-swapped fragment (a port of FastHTML's
 * proc_htmx). htmx fires htmx:load for the initial document and for each
 * swapped-in element, so a single registration covers both; the WeakSet
 * guarantees once-per-element initialization, replacing the old
 * DOMContentLoaded + htmx:afterSwap + per-element guard-flag pattern.
 */
function onSwap(selector: string, initializeElement: (element: Element) => void) {
  const initialized = new WeakSet();
  htmx.onLoad((swappedElement: Element) => {
    const elements: Element[] = Array.from(htmx.findAll(swappedElement, selector));
    if (swappedElement.matches && swappedElement.matches(selector)) {
      elements.unshift(swappedElement);
    }
    for (const element of elements) {
      if (initialized.has(element)) continue;
      initialized.add(element);
      initializeElement(element);
    }
  });
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

/**
 * Mirrors each source element's value onto its target live as the user types,
 * until the user edits the target directly — at which point that target is
 * "dirty" and the manual value wins (no more mirroring into it). Each syncData
 * entry maps a source selector and property onto a target selector and property.
 */
function syncSelectInputUntilChanged(syncData: Array<{ source: string; target: string; source_value: string; target_value: string }>, parentSelector: string | Document = document) {
  const parentElement =
    parentSelector === document
      ? document
      : document.querySelector(parentSelector as string);

  if (!parentElement) {
    console.error(`The parent selector "${parentSelector}" is not valid.`);
    return;
  }
  // One delegated "input" listener drives both directions per syncItem. "input"
  // (not "change") makes the mirror live as the user types. A target the user
  // edits is marked dirty so the mirror stops clobbering it — programmatically
  // setting target.value does NOT fire "input", so our own writes never mark a
  // target dirty; only real user edits do.
  const dirtyTargets = new Set<number>();
  parentElement.addEventListener("input", function (event) {
    const eventTarget = event.target as HTMLElement;
    syncData.forEach((syncItem, index) => {
      // User edited the target directly → stop mirroring into it.
      if (eventTarget.matches(syncItem.target)) {
        dirtyTargets.add(index);
        return;
      }
      // Source changed → mirror into the target unless the user took it over.
      if (eventTarget.matches(syncItem.source) && !dirtyTargets.has(index)) {
        const valueToSync = getValueFromProperty(eventTarget, syncItem.source_value);
        const targetElement = document.querySelector<HTMLSelectElement>(syncItem.target);
        if (targetElement && valueToSync !== null) {
          (targetElement as unknown as Record<string, unknown>)[syncItem.target_value] =
            valueToSync;
        }
      }
    });
  });
}

/**
 * Reads a property off the source element. For a <select>, reads from its
 * selected option. A "dataset." prefix reads from the element's data-* set.
 */
function getValueFromProperty(sourceElement: EventTarget, property: string): any {
  let source: HTMLElement | HTMLOptionElement =
    sourceElement instanceof HTMLSelectElement
      ? sourceElement.selectedOptions[0]
      : sourceElement as HTMLElement;
  if (property.startsWith("dataset.")) {
    let datasetKey = property.slice(8); // Remove 'dataset.' part
    return source.dataset[datasetKey];
  } else if (property in source) {
    return (source as unknown as Record<string, unknown>)[property];
  } else {
    console.error(`Property ${property} is not valid for the option element.`);
    return null;
  }
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

function disableElementsWhenValueNotEqual(
  targetSelect: string,
  targetValue: string | string[],
  elementList: string[]
) {
  return conditionalElementHandler([
    () => {
      let target = document.querySelector<HTMLSelectElement>(targetSelect);
      if (!target) return false;
      console.debug(
        `${disableElementsWhenTrue.name}: triggered on ${target.id}`
      );
      console.debug(`
      ${disableElementsWhenTrue.name}: matching against value(s): ${targetValue}`);
      if (targetValue instanceof Array) {
        if (targetValue.every((value) => target.value != value)) {
          console.debug(
            `${disableElementsWhenTrue.name}: none of the values is equal to ${target.value}, returning true.`
          );
          return true;
        }
        return false;
      } else {
        console.debug(
          `${disableElementsWhenTrue.name}: none of the values is equal to ${target.value}, returning true.`
        );
        return target.value != targetValue;
      }
    },
    elementList,
    (el) => {
      console.debug(
        `${disableElementsWhenTrue.name}: evaluated true, disabling ${el.id}.`
      );
      (el as HTMLInputElement).disabled = true;
    },
    (el) => {
      console.debug(
        `${disableElementsWhenTrue.name}: evaluated false, NOT disabling ${el.id}.`
      );
      (el as HTMLInputElement).disabled = false;
    },
  ]);
}

function disableElementsWhenTrue(targetSelect: string, targetValue: string | string[], elementList: string[]) {
  return conditionalElementHandler([
    () => {
      console.log(`${disableElementsWhenTrue.name}: triggered on ${targetSelect}`)
      console.log(`Value of ${targetSelect} is ${targetValue}: ${document.querySelector<HTMLSelectElement>(targetSelect)?.value == targetValue}`)
      return document.querySelector<HTMLSelectElement>(targetSelect)?.value == targetValue;
    },
    elementList,
    (el) => {
      console.log(`${disableElementsWhenTrue.name}: disabling ${el.id}`);
      (el as HTMLInputElement).disabled = true;
    },
    (el) => {
      console.log(`${disableElementsWhenTrue.name}: enabling ${el.id}`);
      (el as HTMLInputElement).disabled = false;
    },
  ]);
}

export {
  onSwap,
  toISOUTCString,
  syncSelectInputUntilChanged,
  conditionalElementHandler,
  disableElementsWhenValueNotEqual,
  disableElementsWhenTrue,
  getValueFromProperty,
};
