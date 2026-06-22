# Dropdown Behavior Framework + Listbox Selectors — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Unify the two client dropdown paths (`<dropdown-menu>` for menus, `initDropdown` for value-selectors) behind one generic `<dropdown>` custom element + a behavior registry, and migrate the value-selectors to a proper listbox.

**Architecture:** A generic `<dropdown>` element owns open/close/position/keyboard (`attachMenu`). Type-specific wiring lives in registered *behaviors* (`menu`, `select`) that declare the `attachMenu` options they need and run post-attach side effects. `attachMenu` emits `dropdown:show`/`dropdown:hide` DOM events as the extension seam. Python `Dropdown(behavior=…)` emits the element; `SelectDropdown` + `ListboxPanel` presets build the listbox; `GameStatusSelector`/`SessionDeviceSelector` become thin wrappers.

**Tech Stack:** TypeScript (vanilla custom elements, `tsc` per-module → `games/static/js/dist/`), Python component system (`common/components`), Django, pytest + Playwright e2e.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-06-22-dropdown-behavior-framework-design.md`. Branch: `dropdown-behavior-framework`.
- **Behavior-preserving** for the selectors: same options, same PATCH (`status`/`device_id`), same body events (`status-changed`/`device-changed`). Listbox ARIA is additive.
- TS: vanilla DOM, `customElements.define`, no bundler — cross-module imports are real ES imports served from `dist/`. Variables use complete words (`event` not `e`, `element` not `el`).
- Build: `make ts` = `gen_element_types` + `tsc`; `make ts-check` = codegen + `tsc --noEmit`. Run `make ts` after editing any `.ts`.
- Python UI: build with `common.components` builders, never raw HTML. `Element.attributes` is a list; clone-don't-mutate (see PR 1's `_stamp`). One `TypedDict` per element registered with `register_element`; `gen_element_types` codegens `ts/generated/props.ts`.
- Some files already exist from a halted start (inert, nothing imports them): `ts/elements/dropdown-behaviors.ts`, `ts/elements/behaviors/menu.ts`, and the lifecycle edit in `ts/elements/menu-behavior.ts`. Tasks 1–3 below produce exactly those contents — verify/overwrite to match, then proceed.

---

## File Structure

**New TS**
- `ts/elements/dropdown-behaviors.ts` — the registry + `DropdownBehavior`/`BehaviorCtx` types.
- `ts/elements/behaviors/menu.ts` — the `menu` behavior (submenu hover + ArrowRight/Left + flyout anchor).
- `ts/elements/behaviors/select.ts` — the `select` behavior (PATCH-on-pick + label swap + `aria-selected`).

**Repurposed TS**
- `ts/elements/dropdown.ts` — was `initDropdown`; becomes the generic `<dropdown>` element.
- `ts/elements/menu-behavior.ts` — `attachMenu` gains lifecycle event dispatch.

**Deleted TS**
- `ts/elements/dropdown-menu.ts`, `ts/elements/game-status-selector.ts`, `ts/elements/session-device-selector.ts`.

**Python**
- `common/components/custom_elements.py` — rename element/props; `behavior` + `config` on `Dropdown`/`_assemble`; new `ListboxPanel` + `SelectDropdown`; drop two selector registrations/props.
- `common/components/domain.py` — `GameStatusSelector`/`SessionDeviceSelector` → thin wrappers.
- `common/components/__init__.py` — export `ListboxPanel`, `SelectDropdown`.

**Tests**
- `tests/test_custom_elements.py`, `e2e/test_widgets_e2e.py`.

---

## Task 1: Behavior registry module

**Files:**
- Create: `ts/elements/dropdown-behaviors.ts`
- Test: covered indirectly (TS logic; verified via Task 4/7 e2e). No standalone test — it's a 3-line `Map` wrapper.

**Interfaces:**
- Produces: `registerBehavior(name: string, behavior: DropdownBehavior): void`, `getBehavior(name: string): DropdownBehavior | undefined`, `interface DropdownBehavior { menuOptions?(host: HTMLElement): Partial<MenuOptions>; wire?(ctx: BehaviorCtx): (() => void) | void }`, `interface BehaviorCtx { host; toggle; menu; controller }`.

- [ ] **Step 1: Write the module**

```ts
import { MenuController, MenuOptions } from "./menu-behavior.js";

export interface BehaviorCtx {
  host: HTMLElement;
  toggle: HTMLElement;
  menu: HTMLElement;
  controller: MenuController;
}

export interface DropdownBehavior {
  menuOptions?: (host: HTMLElement) => Partial<MenuOptions>;
  wire?: (ctx: BehaviorCtx) => (() => void) | void;
}

const BEHAVIORS = new Map<string, DropdownBehavior>();

export function registerBehavior(name: string, behavior: DropdownBehavior): void {
  BEHAVIORS.set(name, behavior);
}

export function getBehavior(name: string): DropdownBehavior | undefined {
  return BEHAVIORS.get(name);
}
```

- [ ] **Step 2: Type-check**

Run: `make ts-check`
Expected: PASS (no emit errors).

- [ ] **Step 3: Commit**

```bash
git add ts/elements/dropdown-behaviors.ts
git commit -m "Add dropdown behavior registry"
```

---

## Task 2: Lifecycle events on attachMenu

**Files:**
- Modify: `ts/elements/menu-behavior.ts` (the `open()` and `close()` closures)
- Test: `e2e/test_widgets_e2e.py` (new `test_dropdown_lifecycle_events`)

**Interfaces:**
- Produces: host dispatches bubbling `CustomEvent("dropdown:show")` on open, `CustomEvent("dropdown:hide")` on close.

- [ ] **Step 1: Write the failing e2e test**

```python
def test_dropdown_lifecycle_events(authenticated_page: Page, live_server):
    """Opening/closing a dropdown dispatches dropdown:show / dropdown:hide on the host."""
    page = authenticated_page
    page.goto(f"{live_server.url}{reverse('games:list_games')}")
    page.evaluate(
        """() => {
            window.__dd = [];
            const host = document.querySelector('#navbarMenu').closest('dropdown, dropdown-menu');
            host.addEventListener('dropdown:show', () => window.__dd.push('show'));
            host.addEventListener('dropdown:hide', () => window.__dd.push('hide'));
        }"""
    )
    page.locator("#navbarMenuLink").click()
    expect(page.locator("#navbarMenu")).to_be_visible()
    page.locator("#navbarMenuLink").click()
    expect(page.locator("#navbarMenu")).to_be_hidden()
    assert page.evaluate("() => window.__dd") == ["show", "hide"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run --with pytest-django --with pytest-playwright pytest e2e/test_widgets_e2e.py::test_dropdown_lifecycle_events -q`
Expected: FAIL (events never fire; `window.__dd == []`).

- [ ] **Step 3: Dispatch the events in `open()`/`close()`**

In `open()`, immediately after the existing `document.dispatchEvent(new CustomEvent<OpenMenuDetail>(OPEN_MENUS_EVENT, …))`:

```ts
    // Lifecycle seam: behaviors and outside code (incl. htmx hx-on:dropdown:show)
    // observe visibility via these host events rather than JS callbacks.
    host.dispatchEvent(new CustomEvent("dropdown:show", { bubbles: true }));
```

At the end of `close()`, after `window.removeEventListener("resize", reposition);`:

```ts
    host.dispatchEvent(new CustomEvent("dropdown:hide", { bubbles: true }));
```

- [ ] **Step 4: Build + verify pass**

Run: `make ts && uv run --with pytest-django --with pytest-playwright pytest e2e/test_widgets_e2e.py::test_dropdown_lifecycle_events -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ts/elements/menu-behavior.ts e2e/test_widgets_e2e.py
git commit -m "Emit dropdown:show/dropdown:hide lifecycle events from attachMenu"
```

---

## Task 3: The `menu` behavior

**Files:**
- Create: `ts/elements/behaviors/menu.ts`
- Test: deferred to Task 4 (the element wires it; navbar submenu e2e proves it).

**Interfaces:**
- Consumes: `registerBehavior` (Task 1), `MenuOptions` (`menu-behavior.ts`).
- Produces: `registerBehavior("menu", …)` side effect on import. The submenu reads `submenu="true"` from the host.

- [ ] **Step 1: Write the behavior** (ports the submenu logic out of `dropdown-menu.ts`)

```ts
import { registerBehavior } from "../dropdown-behaviors.js";
import { MenuOptions } from "../menu-behavior.js";

const SUBMENU_CLOSE_DELAY_MS = 150;

const isSubmenu = (host: HTMLElement): boolean =>
  host.getAttribute("submenu") === "true";

registerBehavior("menu", {
  menuOptions: (host): Partial<MenuOptions> => {
    if (!isSubmenu(host)) return {};
    const parentPanel = host.closest("[data-menu]") as HTMLElement | null;
    return parentPanel ? { horizontalAnchor: parentPanel } : {};
  },
  wire: ({ host, toggle, menu, controller }) => {
    if (!isSubmenu(host)) return;
    let closeTimer = 0;
    const onEnter = (event: PointerEvent) => {
      if (event.pointerType !== "mouse") return;
      window.clearTimeout(closeTimer);
      controller.open();
    };
    const onLeave = (event: PointerEvent) => {
      if (event.pointerType !== "mouse") return;
      closeTimer = window.setTimeout(() => controller.close(), SUBMENU_CLOSE_DELAY_MS);
    };
    const onToggleKey = (event: KeyboardEvent) => {
      if (event.key !== "ArrowRight") return;
      event.preventDefault();
      controller.open();
      controller.focusFirst();
    };
    const onMenuKey = (event: KeyboardEvent) => {
      if (event.key !== "ArrowLeft") return;
      event.preventDefault();
      controller.close();
      toggle.focus();
    };
    host.addEventListener("pointerenter", onEnter);
    host.addEventListener("pointerleave", onLeave);
    toggle.addEventListener("keydown", onToggleKey);
    menu.addEventListener("keydown", onMenuKey);
    return () => {
      host.removeEventListener("pointerenter", onEnter);
      host.removeEventListener("pointerleave", onLeave);
      toggle.removeEventListener("keydown", onToggleKey);
      menu.removeEventListener("keydown", onMenuKey);
    };
  },
});
```

- [ ] **Step 2: Type-check** — `make ts-check` → PASS.
- [ ] **Step 3: Commit**

```bash
git add ts/elements/behaviors/menu.ts
git commit -m "Add menu dropdown behavior (submenu hover + arrow keys)"
```

---

## Task 4: Generic `<dropdown>` element + Python rename (menu path swap)

This is the keystone: repurpose `dropdown.ts`, rename the Python element, route all menu wrappers through `behavior="menu"`, delete `dropdown-menu.ts`. Behavior-preserving — verified by existing navbar/submenu e2e staying green.

**Files:**
- Modify (repurpose): `ts/elements/dropdown.ts`
- Delete: `ts/elements/dropdown-menu.ts`
- Modify: `common/components/custom_elements.py` (props/registration/builder rename; `behavior` + `config`)
- Modify: `tests/test_custom_elements.py` (tag/behavior assertions)
- Modify: `e2e/test_widgets_e2e.py` (the Task 2 test's `closest('dropdown, dropdown-menu')` → `closest('dropdown')`)

**Interfaces:**
- Consumes: `getBehavior` (Task 1), `attachMenu`/`MenuPlacement` (`menu-behavior.ts`), the `menu`+`select` behavior modules (side-effect imports).
- Produces: `<dropdown>` custom element. Python `register_element("dropdown", "Dropdown", DropdownProps)` with `DropdownProps {placement: str, submenu: bool, behavior: str}`; builder `_Dropdown`; `Dropdown(*, trigger_element, target_element, id, placement="bottom-start", behavior="menu", config: dict[str, str] | None = None)`; `_assemble(..., behavior, config)`.

- [ ] **Step 1: Repurpose `ts/elements/dropdown.ts`** (replace ENTIRE file)

```ts
import { readDropdownProps } from "../generated/props.js";
import { getBehavior } from "./dropdown-behaviors.js";
import { attachMenu, MenuController, MenuPlacement } from "./menu-behavior.js";
// Side-effect imports register the built-in behaviors before connectedCallback.
import "./behaviors/menu.js";
import "./behaviors/select.js";

// Finds the element's own [data-toggle]/[data-menu], ignoring any that belong to
// a nested <dropdown> (so a sub-dropdown never cross-wires its parent).
function ownChild(host: HTMLElement, selector: string): HTMLElement | null {
  for (const match of host.querySelectorAll<HTMLElement>(selector)) {
    if (match.closest("dropdown") === host) return match;
  }
  return null;
}

// The one generic dropdown element. attachMenu owns open/close/position/keyboard;
// a registered behavior (menu, select, …) declares the attachMenu options it
// needs and layers its own wiring. The element reads no type-specific attribute.
class DropdownElement extends HTMLElement {
  private controller?: MenuController;
  private teardown?: () => void;

  connectedCallback(): void {
    const props = readDropdownProps(this);
    const toggle = ownChild(this, "[data-toggle]");
    const menu = ownChild(this, "[data-menu]");
    if (!toggle || !menu) return;

    const behavior = getBehavior(props.behavior);
    const controller = attachMenu(this, toggle, menu, {
      placement: props.placement as MenuPlacement,
      submenu: props.submenu,
      ...(behavior?.menuOptions?.(this) ?? {}),
    });
    this.controller = controller;
    this.teardown =
      behavior?.wire?.({ host: this, toggle, menu, controller }) ?? undefined;
  }

  disconnectedCallback(): void {
    this.teardown?.();
    this.teardown = undefined;
    this.controller?.destroy();
    this.controller = undefined;
  }
}

customElements.define("dropdown", DropdownElement);
```

- [ ] **Step 2: Delete `dropdown-menu.ts`**

```bash
git rm ts/elements/dropdown-menu.ts
```

- [ ] **Step 3: Rename element/props in `custom_elements.py`**

Replace the `DropdownMenuProps` class + its `register_element` (currently near line 240) with:

```python
class DropdownProps(TypedDict):
    placement: str  # "bottom-start" | "bottom-center" | "bottom-end" | "right-start"
    submenu: bool  # enables hover-open + arrow-key submenu behavior
    behavior: str  # registered client behavior: "menu" | "select" | …


register_element("dropdown", "Dropdown", DropdownProps)
_Dropdown = custom_element_builder("dropdown")
```

(Delete the old `class DropdownMenuProps` + `register_element("dropdown-menu", …)` + `_DropdownMenu = custom_element_builder("dropdown-menu")`.)

- [ ] **Step 4: Thread `behavior` + `config` through `_assemble` and `Dropdown`**

Replace `_assemble` and `Dropdown` with:

```python
def _assemble(
    trigger: Element,
    target: Element,
    *,
    id: str,
    placement: str,
    submenu: bool,
    wrapper_class: str,
    behavior: str = "menu",
    config: dict[str, str] | None = None,
) -> Node:
    """Stamp both contracts and wire the <dropdown> element. The single assembly
    point shared by the public Dropdown and DropdownSubmenu. `config` becomes
    extra data-* attributes the chosen behavior reads (e.g. select's PATCH url)."""
    return _Dropdown(
        class_=wrapper_class,
        placement=placement,
        submenu="true" if submenu else "false",
        behavior=behavior,
        **(config or {}),
    )[
        Fragment(
            _stamp_trigger_contract(trigger, id),
            _stamp_target_contract(target, id),
        )
    ]


def Dropdown(
    *,
    trigger_element: Element,
    target_element: Element,
    id: str,
    placement: str = "bottom-start",
    behavior: str = "menu",
    config: dict[str, str] | None = None,
) -> Node:
    """Attach a popup (target_element) to a trigger_element. Generic primitive:
    stamps the JS/ARIA contract, wires the <dropdown> element, and tags it with a
    client `behavior` (menu by default). Menu semantics live in the menu preset/
    wrappers, not here."""
    return _assemble(
        trigger_element,
        target_element,
        id=id,
        placement=placement,
        submenu=False,
        # inline-flex (not inline-block) so the trigger stretches to fill the
        # wrapper — needed when the wrapper is itself a stretched flex child (the
        # SplitButtonDropdown group). Visually identical for a standalone dropdown.
        # FRICTION POINT: imposes flex on every wrapper; `display: contents` is the
        # cleaner-but-broader fallback if it ever fights a layout.
        wrapper_class="relative inline-flex",
        behavior=behavior,
        config=config,
    )
```

`DropdownSubmenu` already calls `_assemble(..., submenu=True, wrapper_class="relative")` — it now passes `behavior` implicitly via the default `"menu"`. No change needed there beyond confirming the default.

- [ ] **Step 5: Update unit-test assertions** in `tests/test_custom_elements.py`: every `self.assertIn("<dropdown-menu", html)` / `html.count("<dropdown-menu")` becomes `"<dropdown"` / `html.count("<dropdown ")` (note trailing space to avoid matching `dropdown-behaviors`); add `self.assertIn('behavior="menu"', html)` to the `MenuDropdown` test; the submenu test still asserts `placement="right-start"`, `submenu="true"`. Update the Task-2 e2e `closest('dropdown, dropdown-menu')` → `closest('dropdown')`.

- [ ] **Step 6: Build + run menu tests**

Run:
```bash
make ts && uv run --with pytest-django pytest tests/test_custom_elements.py -q \
  && uv run --with pytest-django --with pytest-playwright pytest e2e/test_widgets_e2e.py -q -k "navbar or submenu or dropdown"
```
Expected: PASS (navbar menus + submenus behave identically under `<dropdown behavior="menu">`).

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "Replace <dropdown-menu> with a generic <dropdown> element + behavior registry"
```

---

## Task 5: The `select` behavior

**Files:**
- Create: `ts/elements/behaviors/select.ts`
- Test: deferred to Task 7 (selector e2e).

**Interfaces:**
- Consumes: `registerBehavior`, `MenuOptions`, the global `window.fetchWithHtmxTriggers`.
- Produces: `registerBehavior("select", …)`. Reads config from host `data-*`: `data-patch-url`, `data-body-key`, `data-event`, `data-csrf`, `data-numeric`. Options are `[data-option][data-value]`; current label lives in `[data-label]`.

- [ ] **Step 1: Write the behavior** (ports the old `dropdown.ts` `initDropdown` body, adds `aria-selected`)

```ts
import { registerBehavior } from "../dropdown-behaviors.js";
import { MenuOptions } from "../menu-behavior.js";

// Value-selector behavior: pick an option → swap the toggle label, reflect the
// selection (aria-selected), close, PATCH the server, and fire the body event
// that drives cross-widget htmx refresh. Config comes from data-* on the host.
registerBehavior("select", {
  menuOptions: (): Partial<MenuOptions> => ({
    itemSelector: "[data-option]",
    matchToggleWidth: true,
  }),
  wire: ({ host, controller }) => {
    const label = host.querySelector<HTMLElement>("[data-label]");
    const patchUrl = host.dataset.patchUrl ?? "";
    const bodyKey = host.dataset.bodyKey ?? "";
    const event = host.dataset.event ?? "";
    const csrf = host.dataset.csrf ?? "";
    const numeric = host.dataset.numeric === "true";
    const options = Array.from(host.querySelectorAll<HTMLElement>("[data-option]"));

    const handlers: Array<[HTMLElement, (event: Event) => void]> = [];
    for (const option of options) {
      const handler = (clickEvent: Event) => {
        clickEvent.preventDefault();
        clickEvent.stopPropagation();
        const rawValue = option.dataset.value ?? "";
        if (label) label.innerHTML = option.innerHTML;
        for (const other of options) {
          other.setAttribute("aria-selected", other === option ? "true" : "false");
        }
        controller.close();
        window
          .fetchWithHtmxTriggers(patchUrl, {
            method: "PATCH",
            headers: { "Content-Type": "application/json", "X-CSRFToken": csrf },
            body: JSON.stringify({ [bodyKey]: numeric ? Number(rawValue) : rawValue }),
          })
          .then(() => document.body.dispatchEvent(new CustomEvent(event)))
          .catch(() => console.error("Failed to update", patchUrl));
      };
      option.addEventListener("click", handler);
      handlers.push([option, handler]);
    }
    return () => {
      for (const [option, handler] of handlers) {
        option.removeEventListener("click", handler);
      }
    };
  },
});
```

- [ ] **Step 2: Type-check** — `make ts-check` → PASS. (`window.fetchWithHtmxTriggers` global type already declared — the old `dropdown.ts` used it.)
- [ ] **Step 3: Commit**

```bash
git add ts/elements/behaviors/select.ts
git commit -m "Add select dropdown behavior (PATCH-on-pick + aria-selected)"
```

---

## Task 6: Python `ListboxPanel` + `SelectDropdown` presets

**Files:**
- Modify: `common/components/custom_elements.py` (add presets)
- Modify: `common/components/__init__.py` (export)
- Test: `tests/test_custom_elements.py` (new `SelectDropdownRenderTest`)

**Interfaces:**
- Consumes: `Dropdown` (Task 4), `DROPDOWN_TOGGLE_OUTLINE`, `DROPDOWN_PANEL_OUTLINE_CLASS`, `DROPDOWN_ITEM_CLASS`, `Button`, `Span`, `Icon`, `Element`, `Ul`, `Li`.
- Produces:
  - `type SelectOption = tuple[str, Child, bool]  # (value, label, is_selected)`
  - `ListboxPanel(*, options: list[SelectOption], aria_label: str = "") -> Element`
  - `SelectDropdown(*, current_label: Child, options: list[SelectOption], id: str, patch_url: str, body_key: str, event: str, csrf: str, numeric: bool = False, placement: str = "bottom-start") -> Node`

- [ ] **Step 1: Write the failing test**

```python
class SelectDropdownRenderTest(unittest.TestCase):
    def test_renders_listbox_with_select_behavior(self):
        from common.components import SelectDropdown, render

        html = render(
            SelectDropdown(
                current_label="Played",
                options=[("u", "Unplayed", False), ("f", "Finished", True)],
                id="game-7-status",
                patch_url="/api/games/7/status",
                body_key="status",
                event="status-changed",
                csrf="tok",
            )
        )
        self.assertIn('behavior="select"', html)
        self.assertIn('role="listbox"', html)
        self.assertIn('role="option"', html)
        self.assertIn('aria-haspopup="listbox"', html)
        self.assertIn('data-patch-url="/api/games/7/status"', html)
        self.assertIn('data-body-key="status"', html)
        self.assertIn('data-event="status-changed"', html)
        self.assertIn('data-value="f"', html)
        self.assertIn('aria-selected="true"', html)   # the current option
        self.assertIn("data-label", html)              # the toggle's swappable label

    def test_numeric_flag_sets_data_numeric(self):
        from common.components import SelectDropdown, render

        html = render(
            SelectDropdown(
                current_label="Deck", options=[("2", "Deck", True)],
                id="session-4-device", patch_url="/api/session/4/device",
                body_key="device_id", event="device-changed", csrf="t", numeric=True,
            )
        )
        self.assertIn('data-numeric="true"', html)
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run --with pytest-django pytest tests/test_custom_elements.py::SelectDropdownRenderTest -q`
Expected: FAIL (`ImportError: cannot import name 'SelectDropdown'`).

- [ ] **Step 3: Implement the presets** in `custom_elements.py` (after `SplitButtonDropdown`)

```python
type SelectOption = tuple[str, Child, bool]  # (value, label, is_selected); e.g. ("f", "Finished", True)


def ListboxPanel(*, options: list[SelectOption], aria_label: str = "") -> Element:
    """A single-select listbox target: role="listbox" over role="option" items
    carrying [data-option][data-value][aria-selected]. The select behavior wires
    clicks; the core stamps data-menu/hidden/id when it's used as target_element."""
    attributes: list[tuple[str, str]] = [
        ("role", "listbox"),
        ("class", DROPDOWN_PANEL_OUTLINE_CLASS),
    ]
    if aria_label:
        attributes.append(("aria-label", aria_label))
    option_nodes = [
        Li()[
            Element(
                "button",
                [
                    ("type", "button"),
                    ("role", "option"),
                    ("data-option", ""),
                    ("data-value", value),
                    ("aria-selected", "true" if selected else "false"),
                    ("tabindex", "-1"),
                    ("class", DROPDOWN_ITEM_CLASS),
                ],
                [label],
            )
        ]
        for value, label, selected in options
    ]
    return Element("div", attributes, [Ul()[*option_nodes]])


def SelectDropdown(
    *,
    current_label: Child,
    options: list[SelectOption],
    id: str,
    patch_url: str,
    body_key: str,
    event: str,
    csrf: str,
    numeric: bool = False,
    placement: str = "bottom-start",
) -> Node:
    """A value-selector dropdown: a current-value trigger + a listbox whose picks
    PATCH the server (via the client `select` behavior). The per-entity specifics
    (endpoint, body key, numeric) are the caller's; this owns the shared shape."""
    trigger = Button(
        attributes=[
            ("type", "button"),
            ("class", DROPDOWN_TOGGLE_OUTLINE + " rounded-lg"),
            ("aria-haspopup", "listbox"),
        ]
    )[
        Span(class_="flex flex-row gap-4 justify-between items-center")[
            Span(data_label="")[current_label], Icon("arrowdown")
        ]
    ]
    config: dict[str, str] = {
        "data_patch_url": patch_url,
        "data_body_key": body_key,
        "data_event": event,
        "data_csrf": csrf,
    }
    if numeric:
        config["data_numeric"] = "true"
    return Dropdown(
        trigger_element=trigger,
        target_element=ListboxPanel(options=options),
        id=id,
        placement=placement,
        behavior="select",
        config=config,
    )
```

- [ ] **Step 4: Export** in `common/components/__init__.py` — add `ListboxPanel`, `SelectDropdown` to the `custom_elements` import block and to `__all__`.

- [ ] **Step 5: Run to verify pass**

Run: `uv run --with pytest-django pytest tests/test_custom_elements.py::SelectDropdownRenderTest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add common/components/custom_elements.py common/components/__init__.py tests/test_custom_elements.py
git commit -m "Add ListboxPanel + SelectDropdown presets"
```

---

## Task 7: Migrate the value-selectors onto SelectDropdown

**Files:**
- Modify: `common/components/domain.py` (`GameStatusSelector`, `SessionDeviceSelector` → thin wrappers)
- Modify: `common/components/custom_elements.py` (delete `GameStatusSelectorProps`/`SessionDeviceSelectorProps` + their `register_element`s + `_GameStatusSelector`/`_SessionDeviceSelector` builders)
- Delete: `ts/elements/game-status-selector.ts`, `ts/elements/session-device-selector.ts`, and the old `initDropdown` is already gone (Task 4 repurposed `dropdown.ts`)
- Modify: `tests/test_custom_elements.py` (`GameStatusSelectorRenderTest`/`SessionDeviceSelectorRenderTest` — they assert the old `<game-status-selector>` tag)

**Interfaces:**
- Consumes: `SelectDropdown` (Task 6). `GameStatusSelector(game, game_statuses, csrf_token)` / `SessionDeviceSelector(session, session_devices, csrf_token)` keep their signatures + call sites.

- [ ] **Step 1: Update the existing selector render tests** to the new output:

```python
class GameStatusSelectorRenderTest(unittest.TestCase):
    def test_emits_listbox_and_patch_config(self):
        from types import SimpleNamespace
        from common.components import GameStatusSelector, render

        game = SimpleNamespace(id=7, status="f", get_status_display=lambda: "Finished")
        html = render(GameStatusSelector(game, [("u", "Unplayed"), ("f", "Finished")], "tok"))
        self.assertIn('behavior="select"', html)
        self.assertIn('role="listbox"', html)
        self.assertIn('data-patch-url="/api/games/7/status"', html)
        self.assertIn('data-body-key="status"', html)
        self.assertIn('data-value="u"', html)
        self.assertNotIn("<game-status-selector", html)  # element retired


class SessionDeviceSelectorRenderTest(unittest.TestCase):
    def test_emits_listbox_and_numeric_patch(self):
        from types import SimpleNamespace
        from common.components import SessionDeviceSelector, render

        session = SimpleNamespace(id=4, device=SimpleNamespace(id=2, name="Deck"))
        devices = [SimpleNamespace(id=1, name="Desktop"), SimpleNamespace(id=2, name="Deck")]
        html = render(SessionDeviceSelector(session, devices, "tok"))
        self.assertIn('behavior="select"', html)
        self.assertIn('data-patch-url="/api/session/4/device"', html)
        self.assertIn('data-body-key="device_id"', html)
        self.assertIn('data-numeric="true"', html)
        self.assertIn('data-value="2"', html)
```

- [ ] **Step 2: Run to verify they fail** — `uv run --with pytest-django pytest tests/test_custom_elements.py -q -k "GameStatusSelector or SessionDeviceSelector"` → FAIL (old code emits `<game-status-selector>`, no `behavior="select"`).

- [ ] **Step 3: Rewrite the two domain functions** in `domain.py` (replace both functions + the `_SELECTOR_*` constants block they relied on):

```python
def GameStatusSelector(game, game_statuses, csrf_token: str) -> Node:
    """Status value-selector: a listbox that PATCHes /api/games/<id>/status."""
    from common.components.custom_elements import SelectDropdown, SelectOption

    options: list[SelectOption] = [
        (
            value,
            GameStatus(status=value, children=[label], display="flex"),
            value == game.status,
        )
        for value, label in game_statuses
    ]
    return SelectDropdown(
        current_label=GameStatus(
            status=game.status, children=[game.get_status_display()], display="flex"
        ),
        options=options,
        id=f"game-{game.id}-status",
        patch_url=f"/api/games/{game.id}/status",
        body_key="status",
        event="status-changed",
        csrf=csrf_token,
    )


def SessionDeviceSelector(session, session_devices, csrf_token: str) -> Node:
    """Device value-selector: a listbox that PATCHes /api/session/<id>/device."""
    from common.components.custom_elements import SelectDropdown, SelectOption

    current = session.device.id if session.device else None
    options: list[SelectOption] = [
        (str(device.id), device.name, device.id == current) for device in session_devices
    ]
    return SelectDropdown(
        current_label=session.device.name if session.device else "Unknown",
        options=options,
        id=f"session-{session.id}-device",
        patch_url=f"/api/session/{session.id}/device",
        body_key="device_id",
        event="device-changed",
        csrf=csrf_token,
        numeric=True,
    )
```

(Remove the now-unused `_SELECTOR_MENU_CLASS` / `_SELECTOR_TOGGLE_CLASS` / `_SELECTOR_OPTION_CLASS` and the old inline `Element`/`_GameStatusSelector` bodies. Keep the `GameStatus` import.)

- [ ] **Step 4: Drop the retired element registrations** in `custom_elements.py`: delete `class GameStatusSelectorProps`, `class SessionDeviceSelectorProps`, both their `register_element(...)` calls, and the `_GameStatusSelector` / `_SessionDeviceSelector = custom_element_builder(...)` lines.

- [ ] **Step 5: Delete the retired TS elements**

```bash
git rm ts/elements/game-status-selector.ts ts/elements/session-device-selector.ts
```

- [ ] **Step 6: Regenerate types + build + run unit tests**

Run: `make ts && uv run --with pytest-django pytest tests/test_custom_elements.py -q`
Expected: PASS. (`gen_element_types` drops the two selector prop readers from `props.ts`; `tsc` confirms nothing imports them.)

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "Migrate value-selectors onto SelectDropdown listbox (retire their elements)"
```

---

## Task 8: End-to-end verification of the selectors + full sweep

**Files:**
- Modify: `e2e/test_widgets_e2e.py` (selector behavior tests, if any reference old tags; add a status-select e2e)

**Interfaces:** none new — this task proves Tasks 4–7 end-to-end.

- [ ] **Step 1: Add/realign a selector e2e** (a game detail page has a status selector):

```python
def test_status_selector_patches_and_updates_label(authenticated_page: Page, live_server):
    """Picking a status option swaps the toggle label, closes, and PATCHes."""
    page = authenticated_page
    # navigate to any game's detail page (list → first game)
    page.goto(f"{live_server.url}{reverse('games:list_games')}")
    page.locator("a[href*='/game/'][href*='/view']").first.click()
    toggle = page.locator("[aria-haspopup='listbox']").first
    toggle.click()
    listbox = page.locator("[role='listbox']").first
    expect(listbox).to_be_visible()
    option = listbox.locator("[role='option']").first
    label_text = option.inner_text()
    with page.expect_request(lambda r: "/status" in r.url and r.method == "PATCH"):
        option.click()
    expect(listbox).to_be_hidden()
    expect(page.locator("[data-label]").first).to_contain_text(label_text.strip())
```

(Adjust the reverse name / selectors to the repo's actual game-detail route if the list link differs; confirm with `grep -rn "view_game\|list_games" games/urls.py`.)

- [ ] **Step 2: Run the dropdown/selector e2e subset**

Run: `uv run --with pytest-django --with pytest-playwright pytest e2e/test_widgets_e2e.py -q -k "navbar or submenu or dropdown or status or select or play"`
Expected: PASS.

- [ ] **Step 3: Full verification sweep**

Run:
```bash
make ts-check
uv run --with pytest-django pytest tests/ -q
uv run --with pytest-django --with pytest-playwright pytest e2e/ -q
uv run ruff format common/ games/ && uv run ruff check common/ games/
```
Expected: all PASS / clean.

- [ ] **Step 4: Live smoke (chrome-devtools, dev server running)**

Open a game detail page: status + device selectors open as listboxes, picking PATCHes and updates the label and closes; the navbar Menu + entity submenus still work; in the console, `document.addEventListener('dropdown:show', …)` fires on open. Screenshot the open status listbox.

- [ ] **Step 5: Commit + push + open PR**

```bash
git add -A && git commit -m "Add e2e coverage for listbox status selector"
git push -u origin dropdown-behavior-framework
gh pr create --base main --title "Unify dropdowns behind a generic <dropdown> element + behavior registry" \
  --body "$(cat <<'BODY'
PR 2 of the dropdown overhaul. Collapses the two client dropdown paths
(<dropdown-menu> + initDropdown) into one generic <dropdown> element with a
behavior registry; value-selectors become proper listboxes via SelectDropdown.
Spec: docs/superpowers/specs/2026-06-22-dropdown-behavior-framework-design.md.
Follow-ups tracked by #93 (lazy-load on dropdown:show) and #94 (document the htmx seam).

🤖 Generated with [Claude Code](https://claude.com/claude-code)
BODY
)"
```

---

## Self-Review

**Spec coverage:** registry (T1) · lifecycle events (T2) · menu behavior (T3) · generic `<dropdown>` + rename + menu-path swap (T4) · select behavior (T5) · `ListboxPanel`/`SelectDropdown` (T6) · selector migration + element retirement (T7) · listbox ARIA (T6/T7) · e2e + full sweep (T8). The `play-event-row.ts` "unaffected" note holds — it isn't touched. All spec sections map to a task.

**Placeholder scan:** every code step contains full code; the one adjust-to-repo note (T8 Step 1 route name) is flagged with the exact `grep` to resolve it, not left vague.

**Type consistency:** `DropdownBehavior {menuOptions?, wire?}` and `BehaviorCtx {host, toggle, menu, controller}` are defined in T1 and consumed unchanged in T3/T5/T4. Python `Dropdown(..., behavior, config)` / `_assemble(..., behavior, config)` defined in T4, consumed by `SelectDropdown` in T6. `SelectOption = tuple[str, Child, bool]` defined in T6, consumed in T7. `register_element("dropdown", "Dropdown", DropdownProps)` → `readDropdownProps` used in T4's `dropdown.ts`. Tag selector `closest("dropdown")` (T4) matches `customElements.define("dropdown", …)`.
