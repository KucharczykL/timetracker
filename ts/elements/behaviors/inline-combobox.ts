import { registerBehavior } from "../dropdown-behaviors.js";

// Inline-combobox dropdown (issue #348): unlike the `combobox` behavior — which
// hosts a <search-select> behind a SEPARATE ghost toggle button opened on click
// — here the hosted widget's OWN search input is the trigger. The widget opens
// the panel from its own focus/typing handlers (which route through its
// delegated showPanel → host.open()), so this behavior does NOT wire focus→open
// (that would bypass the widget's empty-panel gate) and does NOT refetch on
// dropdown:show (the widget already prefetches on first focus; a second fetch
// would race it). Its only jobs:
//
// - via attachMenu's `inlineTrigger` MenuOption: suppress the toggle click and
//   keydown handlers (a click on a pill/input must not toggle-close; the widget
//   owns Arrow keys) and the toggle aria-expanded writes (the widget owns
//   aria-expanded on the role="combobox" input);
// - a match-nothing `itemSelector`, so attachMenu's roving stays off (with zero
//   items the menu keydown handler also stops swallowing arrow/Home/End, so the
//   caret works inside the search input; Tab still closes);
// - keep Enter inside the search input from implicitly submitting an ancestor
//   <form> (the widget's own Enter-pick handling has already run by the time
//   this listener fires).
//
// attachMenu and the stack do the rest.

registerBehavior("inline-combobox", {
  menuOptions: () => ({
    itemSelector: "[data-combobox-no-items]",
    inlineTrigger: true,
    matchToggleWidth: true,
  }),
  wire: ({ menu }) => {
    const searchInput = menu
      .closest("drop-down")
      ?.querySelector<HTMLInputElement>("[data-search-select-search]");
    const onSearchKeydown = (event: KeyboardEvent) => {
      if (event.key === "Enter") event.preventDefault();
    };
    searchInput?.addEventListener("keydown", onSearchKeydown);
    return () => {
      searchInput?.removeEventListener("keydown", onSearchKeydown);
    };
  },
});
