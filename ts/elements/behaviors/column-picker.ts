import { registerBehavior } from "../dropdown-behaviors.js";

// Column-picker dropdown: the [data-menu] panel is a dialog of native
// checkboxes and the two submit buttons of a form.
//
// - a match-nothing `itemSelector`, so attachMenu's roving navigation and
//   typeahead stay off. The boxes own Space, the arrow keys and the caret, and
//   a menu's item click would close the panel on the first box;
// - `keepOpenOnTab`, so Tab moves to Apply instead of dismissing the panel.
//   The shared focus-leave handler closes it when focus leaves.
//
// The fixed position that the clipping table shell needs, outside-click and
// Escape dismissal, and single-open coordination are the attachMenu engine.
registerBehavior("column-picker", {
  menuOptions: () => ({
    itemSelector: "[data-column-picker-no-items]",
    keepOpenOnTab: true,
  }),
});
