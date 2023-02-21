/**
 * @description Sync select field with input field until user focuses it.
 * @param {HTMLSelectElement} sourceElementSelector
 * @param {HTMLInputElement} targetElementSelector
 */
function syncSelectInputUntilChanged(
  sourceElementSelector,
  targetElementSelector
) {
  const sourceElement = document.querySelector(sourceElementSelector);
  const targetElement = document.querySelector(targetElementSelector);
  function sourceElementHandler(event) {
    let selected = event.target.value;
    let selectedValue = document.querySelector(
      `#id_game option[value='${selected}']`
    ).textContent;
    targetElement.value = selectedValue;
  }
  function targetElementHandler(event) {
    sourceElement.removeEventListener("change", sourceElementHandler);
  }

  sourceElement.addEventListener("change", sourceElementHandler);
  targetElement.addEventListener("focus", targetElementHandler);
}

window.addEventListener("load", () => {
  syncSelectInputUntilChanged("#id_game", "#id_name");
});
