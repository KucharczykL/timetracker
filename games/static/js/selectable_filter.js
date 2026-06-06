/**
 * SelectableFilter widget — Stash-style choice filter with search,
 * include/exclude buttons, and modifier tags (Any / None).
 */
(function () {
  "use strict";

  function initAll() {
    document.querySelectorAll("[data-selectable-filter]").forEach(function (el) {
      if (el._sfInit) return;
      el._sfInit = true;
      initWidget(el);
    });
  }

  function initWidget(container) {
    var search = container.querySelector(".sf-search");
    var options = container.querySelector(".sf-options");
    var selectedArea = container.querySelector(".sf-selected");

    if (!search || !options || !selectedArea) return;

    // ── Search ──
    search.addEventListener("input", function () {
      var q = search.value.toLowerCase();
      options.querySelectorAll(".sf-option").forEach(function (item) {
        var label = (item.getAttribute("data-label") || "").toLowerCase();
        item.style.display = label.indexOf(q) !== -1 ? "" : "none";
      });
    });

    // ── Include / Exclude clicks ──
    options.addEventListener("click", function (e) {
      var btn = e.target.closest("button");
      if (btn) {
        var action = btn.getAttribute("data-action");
        var itemEl = btn.closest(".sf-option");
        if (!itemEl) return;
        var value = itemEl.getAttribute("data-value");
        var label = itemEl.getAttribute("data-label");
        if (!value) return;
        if (action === "include") addTag(container, value, label, "include");
        else if (action === "exclude") addTag(container, value, label, "exclude");
        return;
      }

      // Click on modifier option (not a button)
      var modOption = e.target.closest(".sf-modifier-option");
      if (modOption) {
        var modVal = modOption.getAttribute("data-modifier");
        setModifier(container, modVal);
      }
    });

    // ── Remove selected tag ──
    selectedArea.addEventListener("click", function (e) {
      var removeBtn = e.target.closest(".sf-remove");
      if (removeBtn) {
        removeBtn.closest(".sf-tag").remove();
        return;
      }

      // Click on active modifier tag → deselect it
      var modTag = e.target.closest(".sf-modifier-tag");
      if (modTag) {
        clearModifier(container);
      }
    });
  }

  /** Add a tag to the selected area and clear modifier. */
  function addTag(container, value, label, type) {
    clearModifier(container);
    var selectedArea = container.querySelector(".sf-selected");

    // Check if already present
    var existing = selectedArea.querySelector('.sf-tag[data-value="' + value + '"]');
    if (existing) {
      if (existing.getAttribute("data-type") !== type) {
        existing.setAttribute("data-type", type);
        existing.classList.toggle("sf-excluded", type === "exclude");
        var text = existing.querySelector(".sf-tag-text");
        if (text) text.textContent = (type === "exclude" ? "✗ " : "✓ ") + label;
      }
      return;
    }

    var tag = document.createElement("span");
    tag.className = "sf-tag" + (type === "exclude" ? " sf-excluded" : "");
    tag.setAttribute("data-value", value);
    tag.setAttribute("data-type", type);
    tag.innerHTML =
      '<span class="sf-tag-text">' + (type === "exclude" ? "✗ " : "✓ ") + label + "</span>" +
      '<button type="button" class="sf-remove" aria-label="Remove">×</button>';
    selectedArea.appendChild(tag);
  }

  /** Set a modifier (Any / None) — clears all tags. */
  function setModifier(container, modVal) {
    var selectedArea = container.querySelector(".sf-selected");

    // Clear all tags
    selectedArea.querySelectorAll(".sf-tag").forEach(function (t) { t.remove(); });

    // Clear existing modifier tag
    selectedArea.querySelectorAll(".sf-modifier-tag").forEach(function (t) { t.remove(); });

    // Add new modifier tag
    var label = modVal === "NOT_NULL" ? "(Any)" : "(None)";
    var tag = document.createElement("span");
    tag.className = "sf-modifier-tag active";
    tag.setAttribute("data-modifier", modVal);
    tag.textContent = label;
    selectedArea.appendChild(tag);

    container.setAttribute("data-modifier", modVal);
  }

  /** Clear any active modifier, removing the tag. */
  function clearModifier(container) {
    var selectedArea = container.querySelector(".sf-selected");
    selectedArea.querySelectorAll(".sf-modifier-tag").forEach(function (t) { t.remove(); });
    container.removeAttribute("data-modifier");
  }

  // Read selections for form submission
  window.readSelectableFilters = function (form) {
    form.querySelectorAll("[data-selectable-filter]").forEach(function (container) {
      var modifier = container.getAttribute("data-modifier");
      var modTag = container.querySelector(".sf-modifier-tag.active");
      if (modTag) modifier = modTag.getAttribute("data-modifier");

      var included = [];
      var excluded = [];
      container.querySelectorAll(".sf-tag").forEach(function (tag) {
        var val = tag.getAttribute("data-value");
        if (tag.getAttribute("data-type") === "exclude") excluded.push(val);
        else included.push(val);
      });

      container.setAttribute("data-included", JSON.stringify(included));
      container.setAttribute("data-excluded", JSON.stringify(excluded));
      if (modifier) container.setAttribute("data-modifier", modifier);
    });
  };

  document.addEventListener("DOMContentLoaded", initAll);
  document.addEventListener("htmx:afterSwap", initAll);
})();
