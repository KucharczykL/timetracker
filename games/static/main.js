function elt(type, props, ...children) {
  let dom = document.createElement(type);
  if (props) Object.assign(dom, props);
  for (let child of children) {
    if (typeof child != "string") dom.appendChild(child);
    else dom.appendChild(document.createTextNode(child));
  }
  return dom;
}

/**
 * @param {Node} targetNode
 */
function addToggleButton(targetNode) {
  let manualToggleButton = elt(
    "td",
    {},
    elt(
      "div",
      { className: "basic-button" },
      elt(
        "button",
        {
          onclick: (event) => {
            let textInputField = elt("input", { type: "text", id: targetNode.id });
            targetNode.replaceWith(textInputField);
            event.target.addEventListener("click", (event) => {
              textInputField.replaceWith(targetNode);
            });
          },
        },
        "Toggle manual"
      )
    )
  );
  targetNode.parentElement.appendChild(manualToggleButton);
}

const toggleableFields = ["#id_games", "#id_platform"];

toggleableFields.map((selector) => {
  addToggleButton(document.querySelector(selector));
});
