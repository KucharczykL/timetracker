import { registerBehavior } from "../dropdown-behaviors.js";

// Combobox-hosting dropdown (issue #297): the [data-menu] panel is a dialog
// containing a <search-select> widget, which owns its own keyboard navigation
// and ARIA combobox semantics. The behavior therefore:
//
// - opts out of attachMenu's roving item navigation via a match-nothing
//   itemSelector (with zero items the menu keydown handler also stops swallowing
//   arrow/Home/End, so the caret works inside the search input; Escape and Tab
//   still close the dropdown from attachMenu),
// - on every open (the dropdown:show lifecycle event — the #94 seam) refetches
//   the widget's options and focuses the search input, so the list is always
//   server-fresh with zero bespoke fetch code here,
// - keeps Enter inside the search input from implicitly submitting an ancestor
//   <form> (the filter bar renders its action row inside one); the widget's own
//   Enter-pick handling has already run by the time this listener fires.
//
// The widget methods are duck-typed so this module never imports search-select
// (keeps drop-down.js's transitive graph lean; the element upgrades on its own).

interface ComboboxWidget extends HTMLElement {
  refetchOptions?: () => void;
}

registerBehavior("combobox", {
  menuOptions: () => ({
    itemSelector: "[data-combobox-no-items]",
  }),
  wire: ({ host, menu }) => {
    const searchInput = menu.querySelector<HTMLInputElement>(
      "[data-search-select-search]",
    );
    const onShow = () => {
      // Refetch first: it resets the query and marks the widget prefetched, so
      // the focus below cannot trigger a second (stale-query) fetch.
      menu.querySelector<ComboboxWidget>("search-select")?.refetchOptions?.();
      searchInput?.focus();
    };
    const onSearchKeydown = (event: KeyboardEvent) => {
      if (event.key === "Enter") event.preventDefault();
    };
    host.addEventListener("dropdown:show", onShow);
    searchInput?.addEventListener("keydown", onSearchKeydown);
    return () => {
      host.removeEventListener("dropdown:show", onShow);
      searchInput?.removeEventListener("keydown", onSearchKeydown);
    };
  },
});
