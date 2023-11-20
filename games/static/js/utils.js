/**
 * @description Formats Date to a UTC string accepted by the datetime-local input field.
 * @param {Date} date
 * @returns {string}
 */
function toISOUTCString(date) {
  function stringAndPad(number) {
    return number.toString().padStart(2, 0);
  }
  const year = date.getFullYear();
  const month = stringAndPad(date.getMonth() + 1);
  const day = stringAndPad(date.getDate());
  const hours = stringAndPad(date.getHours());
  const minutes = stringAndPad(date.getMinutes());
  return `${year}-${month}-${day}T${hours}:${minutes}`;
}

/**
 * @description Sync values between source and target elements based on syncData configuration.
 * @param {Array} syncData - Array of objects to define source and target elements with their respective value types.
 */
function syncSelectInputUntilChanged(syncData, parentSelector = document) {
  const parentElement =
    parentSelector === document
      ? document
      : document.querySelector(parentSelector);

  if (!parentElement) {
    console.error(`The parent selector "${parentSelector}" is not valid.`);
    return;
  }
  // Set up a single change event listener on the document for handling all source changes
  parentElement.addEventListener("change", function (event) {
    // Loop through each sync configuration item
    syncData.forEach((syncItem) => {
      // Check if the change event target matches the source selector
      if (event.target.matches(syncItem.source)) {
        const sourceElement = event.target;
        const valueToSync = getValueFromProperty(
          sourceElement,
          syncItem.source_value
        );
        const targetElement = document.querySelector(syncItem.target);

        if (targetElement && valueToSync !== null) {
          targetElement[syncItem.target_value] = valueToSync;
        }
      }
    });
  });

  // Set up a single focus event listener on the document for handling all target focuses
  parentElement.addEventListener(
    "focus",
    function (event) {
      // Loop through each sync configuration item
      syncData.forEach((syncItem) => {
        // Check if the focus event target matches the target selector
        if (event.target.matches(syncItem.target)) {
          // Remove the change event listener to stop syncing
          // This assumes you want to stop syncing once any target receives focus
          // You may need a more sophisticated way to remove listeners if you want to stop
          // syncing selectively based on other conditions
          document.removeEventListener("change", syncSelectInputUntilChanged);
        }
      });
    },
    true
  ); // Use capture phase to ensure the event is captured during focus, not bubble
}

/**
 * @description Retrieve the value from the source element based on the provided property.
 * @param {Element} sourceElement - The source HTML element.
 * @param {string} property - The property to retrieve the value from.
 */
function getValueFromProperty(sourceElement, property) {
  let source =
    sourceElement instanceof HTMLSelectElement
      ? sourceElement.selectedOptions[0]
      : sourceElement;
  if (property.startsWith("dataset.")) {
    let datasetKey = property.slice(8); // Remove 'dataset.' part
    return source.dataset[datasetKey];
  } else if (property in source) {
    return source[property];
  } else {
    console.error(`Property ${property} is not valid for the option element.`);
    return null;
  }
}

/**
 * @description Returns a single element by name.
 * @param {string} selector The selector to look for.
 */
function getEl(selector) {
  if (selector.startsWith("#")) {
    return document.getElementById(selector.slice(1));
  } else if (selector.startsWith(".")) {
    return document.getElementsByClassName(selector);
  } else {
    return document.getElementsByTagName(selector);
  }
}

/**
 * @description Applies different behaviors to elements based on multiple conditional configurations.
 * Each configuration is an array containing a condition function, an array of target element selectors,
 * and two callback functions for handling matched and unmatched conditions.
 * @param {...Array} configs Each configuration is an array of the form:
 *   - 0: {function(): boolean} condition - Function that returns true or false based on a condition.
 *   - 1: {string[]} targetElements - Array of CSS selectors for target elements.
 *   - 2: {function(HTMLElement): void} callbackfn1 - Function to execute when condition is true.
 *   - 3: {function(HTMLElement): void} callbackfn2 - Function to execute when condition is false.
 */
function conditionalElementHandler(...configs) {
  configs.forEach(([condition, targetElements, callbackfn1, callbackfn2]) => {
    if (condition()) {
      targetElements.forEach((elementName) => {
        let el = getEl(elementName);
        if (el === null) {
          console.error(`Element ${elementName} doesn't exist.`);
        } else {
          callbackfn1(el);
        }
      });
    } else {
      targetElements.forEach((elementName) => {
        let el = getEl(elementName);
        if (el === null) {
          console.error(`Element ${elementName} doesn't exist.`);
        } else {
          callbackfn2(el);
        }
      });
    }
  });
}

function disableElementsWhenFalse(targetSelect, targetValue, elementList) {
  return conditionalElementHandler([
    () => {
      return getEl(targetSelect).value != targetValue;
    },
    elementList,
    (el) => {
      el.disabled = "disabled";
    },
    (el) => {
      el.disabled = "";
    },
  ]);
}

function disableElementsWhenTrue(targetSelect, targetValue, elementList) {
  return conditionalElementHandler([
    () => {
      return getEl(targetSelect).value == targetValue;
    },
    elementList,
    (el) => {
      el.disabled = "disabled";
    },
    (el) => {
      el.disabled = "";
    },
  ]);
}

export {
  toISOUTCString,
  syncSelectInputUntilChanged,
  getEl,
  conditionalElementHandler,
  disableElementsWhenFalse,
  disableElementsWhenTrue,
  getValueFromProperty,
};
