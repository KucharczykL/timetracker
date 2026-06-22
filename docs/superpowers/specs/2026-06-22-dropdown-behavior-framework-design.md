# Dropdown behavior framework + listbox selectors (PR 2)

## Context

PR 1 made the Python `Dropdown` a generic "attach a popup to a trigger" primitive,
but the **client** is still two-headed:

- `<dropdown-menu>` (menus/submenus) — `ts/elements/dropdown-menu.ts` → `attachMenu`.
- the value-selectors — `ts/elements/game-status-selector.ts` /
  `session-device-selector.ts` → `ts/elements/dropdown.ts` (`initDropdown`) →
  `attachMenu` + PATCH-on-select.

The two selectors are near-identical reimplementations, and adding any new dropdown
type means a new custom element + `connectedCallback`.

**Goal (scope = full extensibility):** one generic `<dropdown>` element + a client
**behavior registry**, so a new dropdown type plugs in by registering a behavior —
no new element, no new `connectedCallback`. `menu` and `select` both become
behaviors; the selectors become the first proper **listbox** consumers. Lifecycle
DOM events open the seam for future types (lazy-load — issue #93, htmx seam docs —
issue #94).

This is **behavior-preserving** for the selectors (same options, same PATCH); it is
a structural unification plus a listbox-ARIA upgrade.

## Decisions (from brainstorming)

1. **Registry**, not per-type elements or subclassing — only a registry makes a new
   type need zero new element.
2. **Behavior contract** `{ menuOptions?, wire? }` — a behavior declares the
   `attachMenu` options it needs *and* its post-attach wiring, so the generic
   element reads **no** type-specific attribute.
3. **Lifecycle as DOM `CustomEvent`s** (`dropdown:show` / `dropdown:hide`) on the
   host — observable from behaviors *and* htmx/markup (`hx-on:dropdown:show`),
   unlike JS callbacks.
4. **Rename `<dropdown-menu>` → `<dropdown>`** — the tag should say "generic popup",
   not "menu"; `menu` becomes the default behavior.
5. **Selectors become proper listboxes** (`role="listbox"`/`option`,
   `aria-selected`, trigger `aria-haspopup="listbox"`) — the payoff of PR 1's
   type-agnostic core.
6. **`GameStatusSelector` / `SessionDeviceSelector` stay** as thin domain wrappers
   over a new `SelectDropdown` (call sites unchanged); they stop being their own
   custom elements.

## Client design (`ts/`)

### `dropdown-behaviors.ts` — the registry

```ts
type BehaviorCtx = { host: HTMLElement; toggle: HTMLElement;
                     menu: HTMLElement; controller: MenuController };
type DropdownBehavior = {
  menuOptions?: (host: HTMLElement) => Partial<MenuOptions>;
  wire?: (ctx: BehaviorCtx) => (() => void) | void;   // returns optional teardown
};
const BEHAVIORS = new Map<string, DropdownBehavior>();
export const registerBehavior = (name: string, b: DropdownBehavior) => BEHAVIORS.set(name, b);
export const getBehavior = (name: string) => BEHAVIORS.get(name);
```

### `dropdown.ts` — the one `<dropdown>` element

This file is **repurposed**: its current contents (the `initDropdown` select
wiring) move into `behaviors/select.ts`, and it becomes the generic element
(superseding `dropdown-menu.ts`, which is deleted).

`connectedCallback`: `ownChild` toggle/menu → read generic attrs (`placement`,
`submenu`) → merge `behavior.menuOptions(host)` → `attachMenu(merged)` →
`behavior.wire(ctx)` (store teardown). `disconnectedCallback`: teardown +
`controller.destroy()`. Reads no type-specific attribute.

### `menu-behavior.ts` — lifecycle events

`attachMenu`'s `open()` / `close()` dispatch bubbling `dropdown:show` /
`dropdown:hide` `CustomEvent`s on the host. The existing document-level single-open
event stays.

### `behaviors/menu.ts` and `behaviors/select.ts`

- `menu` — `{ wire }`: the submenu hover-open + ArrowRight/Left logic moved out of
  `dropdown-menu.ts`.
- `select` — `{ menuOptions: () => ({ itemSelector: "[data-option]", matchToggleWidth: true }), wire }`.
  `wire` is the old `initDropdown` body: per-`[data-option]` click → swap
  `[data-label]` innerHTML, flip `aria-selected`, `controller.close()`, PATCH
  `host.dataset.patchUrl` with `{ [bodyKey]: numeric ? Number(v) : v }` +
  `X-CSRFToken: host.dataset.csrf`, then dispatch the body event. Config from
  `data-*` on the host.

**Delete:** `dropdown-menu.ts`, `game-status-selector.ts`,
`session-device-selector.ts` (and `dropdown.ts`'s old `initDropdown` body, now
relocated as above).
**Unaffected:** `play-event-row.ts` (its caret is just a `<dropdown behavior="menu">`).

## Python design (`common/components/`)

- Rename `_DropdownMenu` → `_Dropdown` (tag `"dropdown"`); `DropdownMenuProps` →
  `DropdownProps { placement, submenu, behavior }`. Core `Dropdown(...)` gains
  `behavior: str = "menu"` (default → existing menus unchanged) + `data-*`
  passthrough for behavior config.
- `DropdownMenuPanel` keeps `role="menu"`; menu wrappers / `DropdownSubmenu` emit
  `<dropdown behavior="menu">` (default).
- **`ListboxPanel(*, options, ...)`** — new target preset: `role="listbox"`, items
  `role="option"` + `[data-option][data-value]` + `aria-selected` (current `"true"`).
- **`SelectDropdown(*, current_label, options, id, patch_url, body_key, event, numeric=False, csrf)`**
  — trigger (`[data-label]` current value + caret, `aria-haspopup="listbox"`) +
  `ListboxPanel` → `Dropdown(behavior="select", data_patch_url=…, data_body_key=…,
  data_event=…, data_csrf=…, data_numeric=…)`.
- `domain.py` — `GameStatusSelector` / `SessionDeviceSelector` become thin wrappers
  over `SelectDropdown` (per-entity endpoint/body-key/`numeric`); drop their custom
  elements + `register_element` entries + `*SelectorProps`.

## Data flow (select) — behavior unchanged

option click → `select` behavior: read `data-value` → `[data-label].innerHTML =
option.innerHTML` → flip `aria-selected` → `controller.close()` → PATCH → dispatch
`status-changed` / `device-changed` on `document.body` (existing htmx refresh wiring
in `games/views/game.py` / `session.py`).

## Migration / cleanup — single PR

New TS: `dropdown-behaviors.ts`, `behaviors/menu.ts`, `behaviors/select.ts`;
repurpose `dropdown.ts` into the generic element; delete `dropdown-menu.ts` +
the two selector elements. Python: rename element + props,
add `ListboxPanel` + `SelectDropdown`, rewrite the two domain selectors, drop two
`register_element`s. `make ts` regenerates `props.ts`. Update the few test/e2e
assertions that grep the `<dropdown-menu` tag.

## Testing

- Unit (`tests/test_custom_elements.py`): `Dropdown` emits `behavior="menu"`;
  `ListboxPanel` → `role="listbox"`/`option` + `aria-selected` + `data-value`;
  `SelectDropdown` → `behavior="select"` + `data-patch-url`/`data-body-key` +
  `aria-haspopup="listbox"`; menu wrappers still render `<dropdown behavior="menu">`.
- e2e (`e2e/test_widgets_e2e.py`): status selector PATCHes + label updates + closes;
  device selector (numeric); navbar menu + submenu under the `menu` behavior; a
  `dropdown:show` / `dropdown:hide` fire-on-open/close assertion. Update old-tag
  selectors.

## Verification

1. `make ts` + `make ts-check`.
2. `uv run --with pytest-django pytest tests/ -q` + `… pytest e2e/ -q`.
3. Live (chrome-devtools): status + device selectors PATCH and update; navbar
   menus/submenus; `dropdown:show` / `dropdown:hide` fire (console listener).
4. Commit + push as a new PR. Follow-ups already tracked by issues #93 / #94.

## Out of scope (tracked elsewhere)

- Lazy-load options on `dropdown:show` — issue #93.
- Document the `dropdown:show`/`hide` htmx seam — issue #94.
- Scroll-selected-into-view, commit-on-close multi-select, toggle-coordination —
  backlog, gated on a real consumer.
