import { registerBehavior } from "../dropdown-behaviors.js";

// Column-picker dropdown (issue #1245): the [data-menu] panel is a dialog
// holding one native checkbox per column and the two submit buttons of a
// plain form. Its options:
//
// - a match-nothing `itemSelector`, so attachMenu's roving navigation and
//   typeahead stay off: the boxes are native controls that own Space, the
//   arrow keys and the caret, and a menu's item click handler would close the
//   panel on the first box a person ticked;
// - `keepOpenOnTab`, so Tab walks the boxes and reaches Apply instead of
//   dismissing the panel on the first move; the shared focus-leave handler
//   still closes it once focus leaves.
//
// Everything else - the fixed positioning the clipping table shell needs,
// outside-click and Escape dismissal, single-open coordination - is the
// shared attachMenu engine.
registerBehavior("column-picker", {
  menuOptions: () => ({
    itemSelector: "[data-column-picker-no-items]",
    keepOpenOnTab: true,
  }),
});
