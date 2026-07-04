# Dropdown lifecycle events: `dropdown:show` / `dropdown:hide`

The generic `<drop-down>` element (behavior core: [`ts/elements/menu-behavior.ts`](../ts/elements/menu-behavior.ts),
element shell: [`ts/elements/drop-down.ts`](../ts/elements/drop-down.ts)) emits two
DOM events on its host element as its panel opens and closes. These events are
**the supported extension seam** for reacting to dropdown visibility — reach for
them instead of re-implementing open/close detection (MutationObservers,
`hidden`-attribute polling, or per-widget fetch-on-focus plumbing) in each
consumer.

## The events

| Event | Fired by | When |
|-------|----------|------|
| `dropdown:show` | `attachMenu`'s `open()` | After the panel is unhidden, positioned (`position: fixed`, viewport-aware), and the toggle's `aria-expanded` is set to `"true"`. |
| `dropdown:hide` | `attachMenu`'s `close()` | After the panel is hidden, its inline positioning cleared, and `aria-expanded` reset to `"false"`. |

Facts that matter to consumers:

- **Target**: the `<drop-down>` host element itself.
- **Bubbling**: both events bubble (`bubbles: true`). A *submenu* opening also
  fires `dropdown:show` on every ancestor `<drop-down>`, so a listener on a
  top-level dropdown hears its flyouts too — check `event.target` if you only
  care about one level.
- **Deduplicated**: `open()` no-ops when already open and `close()` when already
  closed, so you never receive doubled events for one transition.
- **Timing**: dispatched synchronously, with the DOM already in the new state —
  inside a `dropdown:show` listener the panel is visible and positioned, so
  focusing an element inside it works immediately.
- **No detail payload**: state travels through the DOM (the host, `[data-menu]`,
  `aria-expanded`), not through `event.detail`.

Every open path fires the same event: toggle click, keyboard (Enter/Space/
ArrowDown on the toggle), hover-open submenus, and programmatic
`controller.open()`. Likewise every close path (outside click, Escape, Tab,
item activation, single-open coordination, `DropdownElement.close()`) fires
`dropdown:hide`.

## Consuming from a registered behavior (preferred)

Type-specific dropdown wiring lives in registered behaviors
([`ts/elements/dropdown-behaviors.ts`](../ts/elements/dropdown-behaviors.ts));
a behavior's `wire()` receives the host and returns a teardown, which is the
natural place to subscribe:

```ts
import { registerBehavior } from "../dropdown-behaviors.js";

registerBehavior("my-behavior", {
  wire: ({ host, menu }) => {
    const onShow = () => {
      // panel is already visible and positioned here
    };
    host.addEventListener("dropdown:show", onShow);
    return () => host.removeEventListener("dropdown:show", onShow);
  },
});
```

### Worked example: fetch-on-open (the `combobox` behavior)

[`ts/elements/behaviors/combobox.ts`](../ts/elements/behaviors/combobox.ts) is
the seam's canonical consumer (issue #297): a `<drop-down>` whose panel hosts a
`<search-select>` (the preset picker, `LoadPresetDropdown`). "Fetch fresh
options on every open" is wired entirely off the lifecycle event — the behavior
contains **zero fetch code**; it delegates to the widget's own fetch path:

```ts
wire: ({ host, menu }) => {
  const searchInput = menu.querySelector<HTMLInputElement>(
    "[data-search-select-search]",
  );
  const onShow = () => {
    // Refetch first (resets the query, marks the widget prefetched), THEN
    // focus — so the focus handler's own prefetch can't double-fetch.
    menu.querySelector<ComboboxWidget>("search-select")?.refetchOptions?.();
    searchInput?.focus();
  };
  host.addEventListener("dropdown:show", onShow);
  // …
  return () => host.removeEventListener("dropdown:show", onShow);
},
```

This is the pattern to copy for any "do something when the panel opens" need:
listen on the host, duck-type into the hosted widget, tear down in the returned
cleanup.

## Consuming from markup

Because these are ordinary bubbling DOM events, server-rendered markup can
observe them without any behavior registration — e.g. htmx's inline listener
syntax:

```html
<drop-down … hx-on:dropdown:show="htmx.trigger(this, 'refresh')">
```

> **Note:** the project is phasing HTMX out. The `hx-on:` form works today and
> illustrates why DOM events beat JS callbacks (observable from emitted
> attributes alone), but new interactive consumers should be custom elements or
> registered behaviors using `addEventListener` as above — not new inline
> `hx-on:` wiring.

## Programmatic control

- `DropdownElement.close()` — public, safe pre-connect (no-op); used by
  consumers that close the panel after handling an interaction inside it (the
  filter builder closes the preset picker after a pick).
- Behaviors get the full `MenuController` (`open`/`close`/`isOpen`/`focusFirst`)
  in their `wire()` context.

Both fire the corresponding lifecycle event, so listeners don't care whether a
transition was user-driven or programmatic.
