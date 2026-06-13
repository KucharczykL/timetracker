# HTML + JS Component Authoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the trusted HTML/JS f-strings (Alpine selectors, `@@TOKEN@@` played-row) with htpy-style Python markup + TypeScript custom elements bound by a codegen'd typed contract.

**Architecture:** Three composing layers — (1) additive htpy-style sugar on the existing `Element` node (kwargs attributes + `[]` children), keeping `Media`; (2) light-DOM custom elements whose behavior lives in TypeScript with the native `connectedCallback` lifecycle; (3) one Python `TypedDict` per element, codegen'd into a TS interface + attribute reader so server↔client drift fails `tsc`.

**Tech Stack:** Python 3.12 / Django, pytest + Playwright, TypeScript (`tsc` per-module, no bundler), pnpm, Tailwind, HTMX, the existing `common/components` node tree.

**Design spec:** `docs/superpowers/specs/2026-06-13-html-js-authoring-design.md`

---

## File structure

| Path | Responsibility | Create/Modify |
| --- | --- | --- |
| `tsconfig.json` | TS compiler config (per-module emit to `dist/`) | Create |
| `package.json` | add `typescript` devDep + scripts | Modify |
| `.gitignore` | ignore compiled `dist/` + generated TS | Modify |
| `Makefile` | `ts` target; wire into `dev`/`check` | Modify |
| `ts/globals.d.ts` | ambient types (`window.fetchWithHtmxTriggers`) | Create |
| `ts/elements/dropdown.ts` | shared value-selector dropdown behavior | Create |
| `ts/elements/game-status-selector.ts` | game status element | Create |
| `ts/elements/session-device-selector.ts` | session device element | Create |
| `ts/elements/play-event-row.ts` | played-count control | Create |
| `ts/generated/props.ts` | codegen output (interfaces + readers) | Generated |
| `common/components/core.py` | `Element.__getitem__`, kwargs attrs | Modify |
| `common/components/primitives.py` | `_attrs_from_kwargs` + kwargs in `_html_element` | Modify |
| `common/components/custom_elements.py` | registry, `custom_element()` builder, Props specs | Create |
| `games/management/commands/gen_element_types.py` | codegen command | Create |
| `common/components/domain.py` | convert the two selectors | Modify |
| `games/views/game.py` | convert played-row | Modify |
| `tests/test_node_tree.py` | htpy-style sugar tests | Modify |
| `tests/test_custom_elements.py` | registry/codegen/builder tests | Create |
| `e2e/test_custom_elements_e2e.py` | browser tests for the 3 elements | Create |

---

## Task 1: TypeScript toolchain scaffold

**Files:**
- Modify: `package.json`
- Create: `tsconfig.json`, `ts/globals.d.ts`
- Modify: `.gitignore`, `Makefile`

- [ ] **Step 1: Add the TypeScript dependency**

Edit `package.json` — add to `devDependencies`:

```json
    "typescript": "^5.6.0"
```

- [ ] **Step 2: Install**

Run: `pnpm install`
Expected: adds `typescript`, no errors.

- [ ] **Step 3: Create `tsconfig.json`**

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ES2022",
    "moduleResolution": "Bundler",
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "strict": true,
    "noEmitOnError": true,
    "forceConsistentCasingInFileNames": true,
    "rootDir": "ts",
    "outDir": "games/static/js/dist"
  },
  "include": ["ts/**/*.ts"]
}
```

- [ ] **Step 4: Create `ts/globals.d.ts`**

```typescript
export {};

declare global {
  interface Window {
    fetchWithHtmxTriggers(input: RequestInfo | URL, init?: RequestInit): Promise<Response>;
  }
}
```

- [ ] **Step 5: Create a smoke source to prove the pipeline**

Create `ts/_smoke.ts`:

```typescript
export const SMOKE: number = 1;
```

- [ ] **Step 6: Compile and verify output appears**

Run: `pnpm exec tsc`
Then: `test -f games/static/js/dist/_smoke.js && echo OK`
Expected: prints `OK`.

- [ ] **Step 7: Delete the smoke source**

Run: `rm ts/_smoke.ts games/static/js/dist/_smoke.js`

- [ ] **Step 8: Ignore generated + compiled output**

Append to `.gitignore`:

```
# TypeScript: compiled output and codegen are build-only
/games/static/js/dist/
/ts/generated/
```

- [ ] **Step 9: Add the `ts` Makefile target and wire it in**

In `Makefile`, add a `ts` target and a `gen-element-types` target (the command lands in Task 3; the target is defined now and will work once the command exists):

```makefile
gen-element-types:
	uv run python manage.py gen_element_types

ts: gen-element-types
	pnpm exec tsc

ts-check: gen-element-types
	pnpm exec tsc --noEmit
```

Change the `dev` target to also run the TS watcher — replace the existing `dev:` recipe with:

```makefile
dev:
	@pnpm concurrently \
		--names "Django,Tailwind,TS" \
		--prefix-colors "blue,green,magenta" \
		"uv run python -Wa manage.py runserver" \
		"pnpm tailwindcss -i ./common/input.css -o ./games/static/base.css --watch" \
		"pnpm exec tsc --watch"
```

Change `check:` to include the type-check gate:

```makefile
check: lint format-check ts-check test
```

- [ ] **Step 10: Commit**

```bash
git add package.json pnpm-lock.yaml tsconfig.json ts/globals.d.ts .gitignore Makefile
git commit -m "Add TypeScript toolchain (tsc per-module, build-only)"
```

(If pnpm produced no lockfile change, omit `pnpm-lock.yaml`.)

---

## Task 2: htpy-style sugar on `Element`

**Files:**
- Modify: `common/components/core.py` (add `Element.__getitem__`)
- Modify: `common/components/primitives.py` (kwargs attributes in the `_html_element` factory)
- Test: `tests/test_node_tree.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_node_tree.py`:

```python
class HtpyStyleSugarTest(unittest.TestCase):
    def test_getitem_sets_children(self):
        from common.components import Div, Span

        self.assertEqual(
            render(Div(class_="card")[Span()["hi"]]),
            '<div class="card"><span>hi</span></div>',
        )

    def test_getitem_multiple_children(self):
        from common.components import Div

        self.assertEqual(render(Div()["a", "b"]), "<div>a\nb</div>")

    def test_kwargs_class_underscore_becomes_class(self):
        from common.components import Div

        self.assertIn('class="x"', render(Div(class_="x")))

    def test_kwargs_inner_underscore_becomes_hyphen(self):
        from common.components import Div

        self.assertIn('hx-get="/y"', render(Div(hx_get="/y")))

    def test_kwargs_true_renders_bare_attr(self):
        from common.components import Div

        self.assertIn('hidden="hidden"', render(Div(hidden=True)))

    def test_kwargs_false_and_none_omitted(self):
        from common.components import Div

        html = render(Div(hidden=False, title=None))
        self.assertNotIn("hidden", html)
        self.assertNotIn("title", html)

    def test_getitem_preserves_media(self):
        from common.components import Div, Media, collect_media

        node = Div(class_="x").with_media(Media(js=("a.js",)))["child"]
        self.assertEqual(collect_media(node).js, ("a.js",))
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_node_tree.py::HtpyStyleSugarTest -v`
Expected: FAIL — `TypeError: 'Element' object is not subscriptable` / unexpected kwargs.

- [ ] **Step 3: Add `__getitem__` to `Element`**

In `common/components/core.py`, inside `class Element(Node):`, after `__init__`:

```python
    def __getitem__(self, children: "Children | Node") -> "Element":
        """htpy-style children: ``Div(class_="x")[child1, child2]``.

        Returns an Element with the same tag/attributes/media and these
        children, so the tree stays walkable (Media still bubbles)."""
        items = children if isinstance(children, tuple) else (children,)
        clone = Element(self.tag_name, self.attributes, list(items))
        clone.media = self.media
        return clone
```

- [ ] **Step 4: Add the kwargs→attributes helper and wire it into the factory**

In `common/components/primitives.py`, add near the top (after imports):

```python
def _attrs_from_kwargs(attrs: dict[str, object]) -> list[HTMLAttribute]:
    """Translate htpy-style attribute kwargs to (name, value) pairs.

    ``class_`` -> ``class`` (trailing underscore stripped); ``hx_get`` ->
    ``hx-get`` (inner underscores to hyphens); ``True`` -> bare attribute;
    ``False`` / ``None`` -> omitted."""
    result: list[HTMLAttribute] = []
    for key, value in attrs.items():
        if value is None or value is False:
            continue
        name = key.rstrip("_").replace("_", "-")
        result.append((name, name if value is True else value))  # type: ignore[arg-type]
    return result
```

Then change the `_html_element` factory's inner `element` function to accept and merge kwargs:

```python
def _html_element(tag_name: str):
    """Build a generic element builder for ``tag_name`` (the whitelist factory)."""

    def element(
        attributes: Attributes | None = None,
        children: Children = None,
        **attrs: object,
    ) -> Element:
        merged = as_attributes(attributes) + _attrs_from_kwargs(attrs)
        return Element(tag_name, merged, children)

    element.__name__ = element.__qualname__ = tag_name[:1].upper() + tag_name[1:]
    element.__doc__ = f"Builder for the <{tag_name}> element."
    return element
```

- [ ] **Step 5: Run to verify pass**

Run: `uv run pytest tests/test_node_tree.py::HtpyStyleSugarTest -v`
Expected: PASS (7 tests).

- [ ] **Step 6: Run the full component suite (no regressions)**

Run: `uv run pytest tests/test_node_tree.py tests/test_components.py tests/test_rendered_pages.py -q`
Expected: PASS.

- [ ] **Step 7: Lint + format**

Run: `uv run ruff check common/components/ && uv run ruff format common/components/core.py common/components/primitives.py`
Expected: clean.

- [ ] **Step 8: Commit**

```bash
git add common/components/core.py common/components/primitives.py tests/test_node_tree.py
git commit -m "htpy-style sugar on Element: kwargs attributes + [] children"
```

---

## Task 3: Custom-element registry, builder, and codegen

**Files:**
- Create: `common/components/custom_elements.py`
- Create: `games/management/commands/gen_element_types.py`
- Modify: `common/components/__init__.py` (export `custom_element`, `register_element`)
- Test: `tests/test_custom_elements.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_custom_elements.py`:

```python
import unittest
from typing import TypedDict

from common.components import custom_element, render
from common.components.custom_elements import (
    ElementSpec,
    _ts_for_spec,
    register_element,
)


class SampleProps(TypedDict):
    game_id: int
    status: str
    is_on: bool


class CustomElementBuilderTest(unittest.TestCase):
    def test_serializes_props_to_kebab_attributes(self):
        html = render(
            custom_element(
                "x-sample", {"game_id": 3, "status": "f"}, children=["hi"]
            )
        )
        self.assertIn("<x-sample", html)
        self.assertIn('game-id="3"', html)
        self.assertIn('status="f"', html)
        self.assertIn(">hi</x-sample>", html)

    def test_declares_compiled_module_media(self):
        from common.components import collect_media

        node = custom_element("x-sample", {"game_id": 3})
        self.assertEqual(collect_media(node).js, ("dist/elements/x-sample.js",))


class CodegenTest(unittest.TestCase):
    def test_emits_interface_and_reader(self):
        spec = ElementSpec("x-sample", "XSample", SampleProps)
        ts = _ts_for_spec(spec)
        self.assertIn("export interface XSampleProps {", ts)
        self.assertIn("gameId: number;", ts)
        self.assertIn("status: string;", ts)
        self.assertIn("isOn: boolean;", ts)
        self.assertIn(
            "export function readXSampleProps(el: HTMLElement): XSampleProps", ts
        )
        self.assertIn('Number(el.getAttribute("game-id"))', ts)
        self.assertIn('el.getAttribute("status") ?? ""', ts)
        self.assertIn('el.getAttribute("is-on") === "true"', ts)


class RegistryTest(unittest.TestCase):
    def test_register_adds_spec(self):
        from common.components.custom_elements import ELEMENT_REGISTRY

        before = len(ELEMENT_REGISTRY)
        register_element("x-reg-test", "XRegTest", SampleProps)
        self.assertEqual(len(ELEMENT_REGISTRY), before + 1)
        self.assertEqual(ELEMENT_REGISTRY[-1].tag, "x-reg-test")
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_custom_elements.py -v`
Expected: FAIL — `ImportError: cannot import name 'custom_element'`.

- [ ] **Step 3: Implement the registry, builder, and codegen helpers**

Create `common/components/custom_elements.py`:

```python
"""Custom-element builder, registry, and TypeScript codegen.

A custom element is a light-DOM Web Component: the Python builder emits a
semantic tag whose typed props become kebab-case attributes and whose behavior
lives in a compiled TS module (loaded via Media). One ``TypedDict`` per element
is the single source of truth for the server<->client contract; ``gen_element_types``
turns each registered spec into a TS interface + attribute reader so drift fails
``tsc``.
"""

from dataclasses import dataclass
from typing import Mapping, get_type_hints

from common.components.core import Children, Element, HTMLAttribute, Media, Node


@dataclass(frozen=True)
class ElementSpec:
    tag: str  # e.g. "game-status-selector"
    ts_name: str  # e.g. "GameStatusSelector"
    props: type  # a TypedDict subclass


ELEMENT_REGISTRY: list[ElementSpec] = []


def register_element(tag: str, ts_name: str, props: type) -> None:
    """Register an element so codegen can emit its TS contract."""
    ELEMENT_REGISTRY.append(ElementSpec(tag, ts_name, props))


def _kebab(name: str) -> str:
    return name.replace("_", "-")


def custom_element(
    tag: str, props: Mapping[str, object], *, children: Children = None
) -> Node:
    """Emit ``<tag kebab-attrs>children</tag>`` and declare its compiled module.

    The module path mirrors the source layout: ``ts/elements/<tag>.ts`` compiles
    to ``dist/elements/<tag>.js``, which ``Media`` loads via ``ModuleScript``."""
    attributes: list[HTMLAttribute] = [
        (_kebab(key), value) for key, value in props.items()  # type: ignore[misc]
    ]
    return Element(tag, attributes, children).with_media(
        Media(js=(f"dist/elements/{tag}.js",))
    )


# ── Codegen ──────────────────────────────────────────────────────────────────

_TYPE_MAP = {int: "number", float: "number", str: "string", bool: "boolean"}


def _camel(name: str) -> str:
    head, *tail = name.split("_")
    return head + "".join(part.title() for part in tail)


def _reader_expr(name: str, python_type: type) -> str:
    attr = _kebab(name)
    if python_type in (int, float):
        return f'Number(el.getAttribute("{attr}"))'
    if python_type is bool:
        return f'el.getAttribute("{attr}") === "true"'
    return f'el.getAttribute("{attr}") ?? ""'


def _ts_for_spec(spec: ElementSpec) -> str:
    hints = get_type_hints(spec.props)
    interface_lines = "\n".join(
        f"  {_camel(name)}: {_TYPE_MAP[python_type]};"
        for name, python_type in hints.items()
    )
    reader_lines = "\n".join(
        f"    {_camel(name)}: {_reader_expr(name, python_type)},"
        for name, python_type in hints.items()
    )
    return (
        f"export interface {spec.ts_name}Props {{\n{interface_lines}\n}}\n\n"
        f"export function read{spec.ts_name}Props(el: HTMLElement): "
        f"{spec.ts_name}Props {{\n  return {{\n{reader_lines}\n  }};\n}}"
    )


def render_props_module() -> str:
    """The full ``ts/generated/props.ts`` content for every registered element."""
    header = "// GENERATED by `manage.py gen_element_types` — do not edit.\n"
    blocks = [_ts_for_spec(spec) for spec in ELEMENT_REGISTRY]
    return header + "\n" + "\n\n".join(blocks) + "\n"
```

- [ ] **Step 4: Export the public helpers**

In `common/components/__init__.py`, add to the imports and `__all__`:

```python
from common.components.custom_elements import custom_element, register_element
```

and add `"custom_element"`, `"register_element"` to `__all__`.

- [ ] **Step 5: Run to verify pass**

Run: `uv run pytest tests/test_custom_elements.py -v`
Expected: PASS.

- [ ] **Step 6: Create the codegen management command**

Create `games/management/commands/gen_element_types.py`:

```python
"""Write ts/generated/props.ts from the registered custom-element specs."""

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

# Importing the components package triggers element registration at import time.
import common.components  # noqa: F401
from common.components.custom_elements import render_props_module


class Command(BaseCommand):
    help = "Generate ts/generated/props.ts from registered custom elements."

    def handle(self, *args, **options) -> None:
        output_dir = Path(settings.BASE_DIR) / "ts" / "generated"
        output_dir.mkdir(parents=True, exist_ok=True)
        target = output_dir / "props.ts"
        target.write_text(render_props_module(), encoding="utf-8")
        self.stdout.write(self.style.SUCCESS(f"Wrote {target}"))
```

- [ ] **Step 7: Verify the command runs**

Run: `uv run python manage.py gen_element_types`
Expected: prints `Wrote .../ts/generated/props.ts`; the file exists (only the header so far, since no elements are registered yet).

- [ ] **Step 8: Lint + format + commit**

```bash
uv run ruff check common/ games/ && uv run ruff format common/components/custom_elements.py games/management/commands/gen_element_types.py
git add common/components/custom_elements.py common/components/__init__.py games/management/commands/gen_element_types.py tests/test_custom_elements.py
git commit -m "Custom-element registry, builder, and TS codegen"
```

---

## Task 4: Shared dropdown behavior + GameStatusSelector element

**Files:**
- Create: `ts/elements/dropdown.ts`, `ts/elements/game-status-selector.ts`
- Modify: `common/components/custom_elements.py` (add `GameStatusSelectorProps` + registration), `common/components/domain.py` (rewrite `GameStatusSelector`), `common/components/__init__.py`
- Test: `tests/test_custom_elements.py`, `e2e/test_custom_elements_e2e.py`

- [ ] **Step 1: Write the shared dropdown TS helper**

Create `ts/elements/dropdown.ts`:

```typescript
export interface DropdownConfig {
  patchUrl: string;
  bodyKey: string; // server field name, e.g. "status" or "device_id"
  event: string; // dispatched on document.body after a successful PATCH
  csrf: string;
  numericValue?: boolean; // parse the option value as a number
}

// Wires a light-DOM value-selector dropdown that lives inside `host`.
// Markup hooks (rendered server-side): [data-toggle], [data-menu],
// [data-label], and one or more [data-option][data-value].
export function initDropdown(host: HTMLElement, config: DropdownConfig): void {
  const toggle = host.querySelector<HTMLElement>("[data-toggle]");
  const menu = host.querySelector<HTMLElement>("[data-menu]");
  const label = host.querySelector<HTMLElement>("[data-label]");
  if (!toggle || !menu || !label) return;

  const close = () => {
    menu.hidden = true;
  };

  toggle.addEventListener("click", (event) => {
    event.stopPropagation();
    menu.hidden = !menu.hidden;
  });
  document.addEventListener("click", (event) => {
    if (!host.contains(event.target as Node)) close();
  });

  host.querySelectorAll<HTMLElement>("[data-option]").forEach((option) => {
    option.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      const raw = option.dataset.value ?? "";
      label.innerHTML = option.innerHTML;
      close();
      const body: Record<string, unknown> = {
        [config.bodyKey]: config.numericValue ? Number(raw) : raw,
      };
      window
        .fetchWithHtmxTriggers(config.patchUrl, {
          method: "PATCH",
          headers: { "Content-Type": "application/json", "X-CSRFToken": config.csrf },
          body: JSON.stringify(body),
        })
        .then(() => document.body.dispatchEvent(new CustomEvent(config.event)))
        .catch(() => console.error("Failed to update", config.patchUrl));
    });
  });
}
```

- [ ] **Step 2: Register `GameStatusSelectorProps`**

In `common/components/custom_elements.py`, at the bottom add:

```python
from typing import TypedDict


class GameStatusSelectorProps(TypedDict):
    game_id: int
    status: str
    csrf: str


register_element("game-status-selector", "GameStatusSelector", GameStatusSelectorProps)
```

- [ ] **Step 3: Rewrite `GameStatusSelector` (Python) htpy-style**

In `common/components/domain.py`, replace the entire `GameStatusSelector` function with:

```python
def GameStatusSelector(game, game_statuses, csrf_token: str) -> Node:
    """Light-DOM custom element; behavior in ts/elements/game-status-selector.ts."""
    from common.components import custom_element
    from common.components.custom_elements import GameStatusSelectorProps
    from common.components.primitives import Button, Div, Icon, Span, Ul, Li

    _MENU = (
        "absolute top-[105%] left-0 w-full whitespace-nowrap z-10 text-sm "
        "font-medium bg-gray-800/20 backdrop-blur-lg rounded-md rounded-t-none "
        "border border-gray-200 dark:border-gray-700"
    )
    options = [
        Li()[
            Element(
                "button",
                [("type", "button"), ("data-option", ""), ("data-value", str(value))],
                GameStatus(status=value, children=[label], display="flex"),
            )
        ]
        for value, label in game_statuses
    ]
    current_label = Span(data_label="")[
        GameStatus(
            status=game.status,
            children=[game.get_status_display()],
            display="flex",
        )
    ]
    toggle = Element(
        "button",
        [("type", "button"), ("data-toggle", ""), ("class", "px-4 py-2")],
        [current_label, Icon("arrowdown")],
    )
    menu = Div(data_menu="", hidden=True, class_=_MENU)[Ul()[*options]]
    dropdown = Div(data_dropdown="", class_="inline-flex rounded-md shadow-2xs relative")[
        toggle, menu
    ]
    return custom_element(
        "game-status-selector",
        GameStatusSelectorProps(game_id=game.id, status=game.status, csrf=csrf_token),
        children=[Div(class_="flex gap-2 items-center")[dropdown]],
    )
```

(Delete `_dropdown_button_html` later, in Task 5, once `SessionDeviceSelector` no longer needs it.)

- [ ] **Step 4: Write the GameStatusSelector element**

Create `ts/elements/game-status-selector.ts`:

```typescript
import { readGameStatusSelectorProps } from "../generated/props.js";
import { initDropdown } from "./dropdown.js";

class GameStatusSelectorElement extends HTMLElement {
  connectedCallback(): void {
    const props = readGameStatusSelectorProps(this);
    initDropdown(this, {
      patchUrl: `/api/games/${props.gameId}/status`,
      bodyKey: "status",
      event: "status-changed",
      csrf: props.csrf,
    });
  }
}

customElements.define("game-status-selector", GameStatusSelectorElement);
```

- [ ] **Step 5: Codegen + compile**

Run: `make ts`
Expected: writes `ts/generated/props.ts` (now containing `GameStatusSelectorProps`), then compiles to `games/static/js/dist/elements/game-status-selector.js`, `dist/elements/dropdown.js`, `dist/generated/props.js` with no type errors.

- [ ] **Step 6: Write the Python render test**

Add to `tests/test_custom_elements.py`:

```python
class GameStatusSelectorRenderTest(unittest.TestCase):
    def test_emits_tag_props_and_media(self):
        import django

        django.setup()
        from types import SimpleNamespace

        from common.components import GameStatusSelector, collect_media, render

        game = SimpleNamespace(id=7, status="f", get_status_display=lambda: "Finished")
        node = GameStatusSelector(game, [("u", "Unplayed"), ("f", "Finished")], "tok")
        html = render(node)
        self.assertIn("<game-status-selector", html)
        self.assertIn('game-id="7"', html)
        self.assertIn('status="f"', html)
        self.assertIn('csrf="tok"', html)
        self.assertIn("data-option", html)
        self.assertIn('data-value="u"', html)
        self.assertNotIn("x-data", html)  # no Alpine left
        self.assertIn("dist/elements/game-status-selector.js", collect_media(node).js)
```

- [ ] **Step 7: Run Python tests**

Run: `uv run pytest tests/test_custom_elements.py tests/test_rendered_pages.py -q`
Expected: PASS (the games list page now renders `<game-status-selector>`).

- [ ] **Step 8: Write the e2e test**

Create `e2e/test_custom_elements_e2e.py`:

```python
import pytest
from django.urls import reverse
from playwright.sync_api import Page, expect


@pytest.fixture
def authenticated_page(live_server, page: Page, django_user_model) -> Page:
    django_user_model.objects.create_user(username="tester", password="secret123")
    page.goto(f"{live_server.url}{reverse('login')}")
    page.fill('input[name="username"]', "tester")
    page.fill('input[name="password"]', "secret123")
    page.click('input[type="submit"]')
    page.wait_for_url(f"{live_server.url}/tracker**")
    return page


@pytest.mark.django_db
def test_game_status_selector_opens_and_patches(
    authenticated_page: Page, live_server, django_user_model
):
    from games.models import Game, Platform

    platform = Platform.objects.create(name="PC", icon="pc")
    game = Game.objects.create(name="Test Game", platform=platform, status="u")

    page = authenticated_page
    page.goto(f"{live_server.url}{reverse('games:list_games')}")

    host = page.locator("game-status-selector").first
    expect(host).to_be_attached()
    # Menu hidden until toggled.
    host.locator("[data-toggle]").click()
    expect(host.locator("[data-menu]")).to_be_visible()
    # Selecting Finished PATCHes and updates the label.
    host.locator('[data-option][data-value="f"]').click()
    game.refresh_from_db()
    assert game.status == "f"
```

- [ ] **Step 9: Run the e2e test**

Run: `uv run pytest e2e/test_custom_elements_e2e.py::test_game_status_selector_opens_and_patches -v`
Expected: PASS (real Chromium upgrades the element, `connectedCallback` wires it).

- [ ] **Step 10: Lint, format, commit**

```bash
uv run ruff check common/ games/ && uv run ruff format common/components/domain.py common/components/custom_elements.py tests/test_custom_elements.py e2e/test_custom_elements_e2e.py
git add common/components/domain.py common/components/custom_elements.py common/components/__init__.py ts/elements/dropdown.ts ts/elements/game-status-selector.ts tests/test_custom_elements.py e2e/test_custom_elements_e2e.py
git commit -m "GameStatusSelector: custom element + typed contract (retire Alpine)"
```

---

## Task 5: SessionDeviceSelector element

**Files:**
- Create: `ts/elements/session-device-selector.ts`
- Modify: `common/components/custom_elements.py`, `common/components/domain.py` (rewrite `SessionDeviceSelector`, delete `_dropdown_button_html`)
- Test: `tests/test_custom_elements.py`, `e2e/test_custom_elements_e2e.py`

- [ ] **Step 1: Register `SessionDeviceSelectorProps`**

In `common/components/custom_elements.py` add:

```python
class SessionDeviceSelectorProps(TypedDict):
    session_id: int
    csrf: str


register_element(
    "session-device-selector", "SessionDeviceSelector", SessionDeviceSelectorProps
)
```

- [ ] **Step 2: Rewrite `SessionDeviceSelector` (Python) htpy-style**

In `common/components/domain.py`, replace the entire `SessionDeviceSelector` function with:

```python
def SessionDeviceSelector(session, session_devices, csrf_token: str) -> Node:
    """Light-DOM custom element; behavior in ts/elements/session-device-selector.ts."""
    from common.components import custom_element
    from common.components.custom_elements import SessionDeviceSelectorProps
    from common.components.primitives import Div, Icon, Li, Span, Ul

    _MENU = (
        "absolute top-[105%] left-0 w-full whitespace-nowrap z-10 text-sm "
        "font-medium bg-gray-800/20 backdrop-blur-lg rounded-md rounded-t-none "
        "border border-gray-200 dark:border-gray-700"
    )
    current_name = session.device.name if session.device else "Unknown"
    options = [
        Li()[
            Element(
                "button",
                [("type", "button"), ("data-option", ""), ("data-value", str(device.id))],
                children=[device.name],
            )
        ]
        for device in session_devices
    ]
    toggle = Element(
        "button",
        [("type", "button"), ("data-toggle", ""), ("class", "px-4 py-2")],
        [Span(data_label="")[current_name], Icon("arrowdown")],
    )
    menu = Div(data_menu="", hidden=True, class_=_MENU)[Ul()[*options]]
    dropdown = Div(data_dropdown="", class_="inline-flex rounded-md shadow-2xs relative")[
        toggle, menu
    ]
    return custom_element(
        "session-device-selector",
        SessionDeviceSelectorProps(session_id=session.id, csrf=csrf_token),
        children=[Div(class_="flex gap-2 items-center")[dropdown]],
    )
```

- [ ] **Step 3: Delete the dead Alpine helper**

In `common/components/domain.py`, delete the now-unused `_dropdown_button_html` function.

- [ ] **Step 4: Write the element**

Create `ts/elements/session-device-selector.ts`:

```typescript
import { readSessionDeviceSelectorProps } from "../generated/props.js";
import { initDropdown } from "./dropdown.js";

class SessionDeviceSelectorElement extends HTMLElement {
  connectedCallback(): void {
    const props = readSessionDeviceSelectorProps(this);
    initDropdown(this, {
      patchUrl: `/api/session/${props.sessionId}/device`,
      bodyKey: "device_id",
      event: "device-changed",
      csrf: props.csrf,
      numericValue: true,
    });
  }
}

customElements.define("session-device-selector", SessionDeviceSelectorElement);
```

- [ ] **Step 5: Codegen + compile**

Run: `make ts`
Expected: `props.ts` now includes `SessionDeviceSelectorProps`; compiles clean.

- [ ] **Step 6: Add the Python render test**

Add to `tests/test_custom_elements.py`:

```python
class SessionDeviceSelectorRenderTest(unittest.TestCase):
    def test_emits_tag_and_options(self):
        import django

        django.setup()
        from types import SimpleNamespace

        from common.components import SessionDeviceSelector, render

        session = SimpleNamespace(id=4, device=SimpleNamespace(name="Desktop"))
        devices = [SimpleNamespace(id=1, name="Desktop"), SimpleNamespace(id=2, name="Deck")]
        html = render(SessionDeviceSelector(session, devices, "tok"))
        self.assertIn("<session-device-selector", html)
        self.assertIn('session-id="4"', html)
        self.assertIn('data-value="2"', html)
        self.assertNotIn("x-data", html)
```

- [ ] **Step 7: Add the e2e test**

Add to `e2e/test_custom_elements_e2e.py`:

```python
@pytest.mark.django_db
def test_session_device_selector_patches(authenticated_page: Page, live_server):
    from games.models import Device, Game, Platform, Session

    platform = Platform.objects.create(name="PC", icon="pc")
    game = Game.objects.create(name="Test Game", platform=platform)
    desktop = Device.objects.create(name="Desktop")
    deck = Device.objects.create(name="Deck")
    session = Session.objects.create(
        game=game, device=desktop, timestamp_start="2025-01-01 00:00:00+00:00"
    )

    page = authenticated_page
    page.goto(f"{live_server.url}{reverse('games:list_sessions')}")

    host = page.locator("session-device-selector").first
    expect(host).to_be_attached()
    host.locator("[data-toggle]").click()
    host.locator(f'[data-option][data-value="{deck.id}"]').click()
    session.refresh_from_db()
    assert session.device_id == deck.id
```

- [ ] **Step 8: Run tests**

Run: `uv run pytest tests/test_custom_elements.py e2e/test_custom_elements_e2e.py -q`
Expected: PASS.

- [ ] **Step 9: Lint, format, commit**

```bash
uv run ruff check common/ games/ && uv run ruff format common/components/domain.py common/components/custom_elements.py tests/test_custom_elements.py e2e/test_custom_elements_e2e.py
git add common/components/domain.py common/components/custom_elements.py ts/elements/session-device-selector.ts tests/test_custom_elements.py e2e/test_custom_elements_e2e.py
git commit -m "SessionDeviceSelector: custom element; delete Alpine dropdown helper"
```

---

## Task 6: play-event-row element

**Files:**
- Create: `ts/elements/play-event-row.ts`
- Modify: `common/components/custom_elements.py`, `games/views/game.py` (rewrite `_played_row`, delete `_PLAYED_ROW_TEMPLATE`)
- Test: `tests/test_custom_elements.py`, `e2e/test_custom_elements_e2e.py`

- [ ] **Step 1: Register `PlayEventRowProps`**

In `common/components/custom_elements.py` add:

```python
class PlayEventRowProps(TypedDict):
    game_id: int
    csrf: str
    api_create_url: str


register_element("play-event-row", "PlayEventRow", PlayEventRowProps)
```

- [ ] **Step 2: Rewrite `_played_row` htpy-style + delete the template**

In `games/views/game.py`, delete the `_PLAYED_ROW_TEMPLATE` string constant entirely, and replace the `_played_row` function with:

```python
def _played_row(game: Game, request: HttpRequest) -> Node:
    """'Played N times' control as a custom element (ts/elements/play-event-row.ts)."""
    from common.components import custom_element
    from common.components.custom_elements import PlayEventRowProps

    played = game.playevents.count()
    add_pe = reverse("games:add_playevent")
    add_pe_for_game = reverse("games:add_playevent_for_game", args=[game.id])

    _BTN = (
        "px-4 py-2 text-sm font-medium text-gray-900 bg-white border border-gray-200 "
        "hover:bg-gray-100 hover:text-blue-700 dark:bg-gray-800 dark:border-gray-700 "
        "dark:text-white dark:hover:bg-gray-700 hover:cursor-pointer"
    )
    _MENU = (
        "absolute top-full -left-px w-auto whitespace-nowrap z-10 text-sm font-medium "
        "bg-gray-800/20 backdrop-blur-lg rounded-md rounded-tl-none border "
        "border-gray-200 dark:border-gray-700"
    )

    count_button = A(href=add_pe)[
        Element(
            "button",
            [("type", "button"), ("class", _BTN + " rounded-s-lg")],
            [Span(data_count="")[str(played)], " times"],
        )
    ]
    menu = Div(data_menu="", hidden=True, class_=_MENU)[
        Ul()[
            Li(attributes=[("class", "px-4 py-2")])[
                A(href=add_pe_for_game)["Add playthrough..."]
            ],
            Li(attributes=[("class", "px-4 py-2 cursor-pointer")], children=None)[
                Element(
                    "button",
                    [("type", "button"), ("data-add-play", "")],
                    children=["Played times +1"],
                )
            ],
        ]
    ]
    toggle = Element(
        "button",
        [("type", "button"), ("data-toggle", ""), ("class", _BTN + " rounded-e-lg relative")],
        [Icon("arrowdown"), menu],
    )
    group = Div(class_="inline-flex rounded-md shadow-2xs relative")[count_button, toggle]
    return custom_element(
        "play-event-row",
        PlayEventRowProps(
            game_id=game.id,
            csrf=get_token(request),
            api_create_url=reverse("api-1.0.0:create_playevent"),
        ),
        children=[Div(class_="flex gap-2 items-center")[Span(class_="uppercase")["Played"], group]],
    )
```

Ensure `A`, `Div`, `Span`, `Ul`, `Li`, `Icon`, `Element` are imported in `games/views/game.py` (most already are; add any missing from `common.components`).

- [ ] **Step 3: Write the element**

Create `ts/elements/play-event-row.ts`:

```typescript
import { readPlayEventRowProps } from "../generated/props.js";

class PlayEventRowElement extends HTMLElement {
  connectedCallback(): void {
    const props = readPlayEventRowProps(this);
    const toggle = this.querySelector<HTMLElement>("[data-toggle]");
    const menu = this.querySelector<HTMLElement>("[data-menu]");
    const count = this.querySelector<HTMLElement>("[data-count]");
    const addPlay = this.querySelector<HTMLElement>("[data-add-play]");
    if (!toggle || !menu) return;

    const close = () => {
      menu.hidden = true;
    };
    toggle.addEventListener("click", (event) => {
      event.stopPropagation();
      menu.hidden = !menu.hidden;
    });
    document.addEventListener("click", (event) => {
      if (!this.contains(event.target as Node)) close();
    });

    addPlay?.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      if (count) count.textContent = String(Number(count.textContent) + 1);
      close();
      window
        .fetchWithHtmxTriggers(props.apiCreateUrl, {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-CSRFToken": props.csrf },
          body: JSON.stringify({ game_id: props.gameId }),
        })
        .catch(() => {
          if (count) count.textContent = String(Number(count.textContent) - 1);
          console.error("Failed to record play");
        });
    });
  }
}

customElements.define("play-event-row", PlayEventRowElement);
```

- [ ] **Step 4: Codegen + compile**

Run: `make ts`
Expected: clean compile; `props.ts` includes `PlayEventRowProps`.

- [ ] **Step 5: Assert via the rendered game page (integration)**

`_played_row` calls `game.playevents.count()`, which needs a saved row, so the
contract is asserted through the rendered detail page rather than a unit stub.
Add to `tests/test_rendered_pages.py` (inside `RenderedPagesTest`):

```python
    def test_view_game_uses_play_event_row_element(self):
        game = Game.objects.create(name="Played Game", platform=self.platform)
        html = self.get("games:view_game", args=[game.id]).content.decode()
        self.assertIn("<play-event-row", html)
        self.assertIn('game-id="', html)
        self.assertNotIn("@@", html)  # token-replace hack gone
        self.assertNotIn("x-data", html)  # Alpine gone from this control
```

(`RenderedPagesTest.setUp` already creates `self.platform`; if not, add
`self.platform = Platform.objects.create(name="PC", icon="pc")` there. Ensure
`Game` and `Platform` are imported in the test module.)

- [ ] **Step 6: Add the e2e test**

Add to `e2e/test_custom_elements_e2e.py`:

```python
@pytest.mark.django_db
def test_play_event_row_increments(authenticated_page: Page, live_server):
    from games.models import Game, Platform

    platform = Platform.objects.create(name="PC", icon="pc")
    game = Game.objects.create(name="Test Game", platform=platform)

    page = authenticated_page
    page.goto(f"{live_server.url}{reverse('games:view_game', args=[game.id])}")

    host = page.locator("play-event-row").first
    expect(host).to_be_attached()
    host.locator("[data-toggle]").click()
    host.locator("[data-add-play]").click()
    expect(host.locator("[data-count]")).to_have_text("1")
    assert game.playevents.count() == 1
```

- [ ] **Step 7: Run tests**

Run: `uv run pytest tests/test_rendered_pages.py e2e/test_custom_elements_e2e.py -q`
Expected: PASS.

- [ ] **Step 8: Lint, format, commit**

```bash
uv run ruff check common/ games/ && uv run ruff format games/views/game.py common/components/custom_elements.py
git add games/views/game.py common/components/custom_elements.py ts/elements/play-event-row.ts tests/test_rendered_pages.py e2e/test_custom_elements_e2e.py
git commit -m "played-row: custom element; delete @@TOKEN@@ template + Alpine"
```

---

## Task 7: CI, Docker, and docs

**Files:**
- Modify: `Dockerfile`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Build TS in the Docker image**

In `Dockerfile`, find the stage that runs the Tailwind/`make css` build (the stage with pnpm available) and add a TS build right after it:

```dockerfile
RUN make ts
```

(If the image builds CSS via `pnpm tailwindcss ...` directly rather than `make css`, add `RUN uv run python manage.py gen_element_types && pnpm exec tsc` instead, ensuring `uv`, `pnpm`, and the source tree are present in that stage.)

- [ ] **Step 2: Verify the full check gate passes**

Run: `make check`
Expected: lint clean, format clean, `tsc --noEmit` clean (drift gate), all Python tests pass.

- [ ] **Step 3: Run the whole suite including e2e**

Run: `make ts && uv run pytest`
Expected: all unit + e2e tests pass (the `dist/` modules must be compiled first so the live_server serves them).

- [ ] **Step 4: Document the pattern in CLAUDE.md**

In `CLAUDE.md`, under the component-system / frontend section, add:

```markdown
**Interactive components are custom elements, not inline JS.** A component that
needs behavior emits a semantic tag via `custom_element("tag", Props(...))`
(light DOM, server-rendered inner markup built with the node builders). Behavior
lives in `ts/elements/<tag>.ts` (TypeScript, vanilla DOM, `customElements.define`),
compiled per-module by `tsc` to `games/static/js/dist/` (build-only, gitignored;
run `make ts`). The server↔client contract is one Python `TypedDict` per element
registered via `register_element(...)`; `manage.py gen_element_types` codegens
`ts/generated/props.ts` (interface + attribute reader), so renaming a prop fails
`tsc` (`make ts-check`). Do NOT author HTML/JS as Python f-strings, and do NOT
add new inline Alpine `x-data` blobs — Alpine remains only for trivial existing
toggles. htpy-style markup: `Div(class_="x", hx_get="/y")[child1, child2]`.
```

- [ ] **Step 5: Commit**

```bash
git add Dockerfile CLAUDE.md
git commit -m "Build TS in Docker; document the custom-element authoring pattern"
```

---

## Self-review notes

- **Spec coverage:** Layer 1 (htpy sugar) = Task 2; Layer 2 (custom elements) = Tasks 4–6; Layer 3 (typed contract/codegen) = Task 3; toolchain = Task 1; CI/Docker/docs = Task 7. All three exemplars (GameStatusSelector, SessionDeviceSelector, played-row) have a dedicated task. Alpine retired in each conversion; existing `.js` untouched (only `ts/` compiled). Build-only/gitignored output set in Task 1.
- **Known soft spot:** Task 6 Step 5's unit test is awkward because `game.playevents.count()` needs a DB row; the real assertion is the integration page test in Step 6 and the e2e in Step 7. The executor should rely on those two and keep/trim the unit stub accordingly.
- **Type/name consistency:** `custom_element` / `register_element` / `render_props_module` / `_ts_for_spec` / `ELEMENT_REGISTRY` / `ElementSpec` are used consistently. TS readers are named `read<TsName>Props` and imported from `../generated/props.js`; `initDropdown` shared by the two selectors; the data-attribute hooks (`data-toggle`, `data-menu`, `data-label`/`data-count`, `data-option`/`data-value`, `data-add-play`) match between each Python builder and its TS.
- **Media path:** `custom_element` declares `Media(js=("dist/elements/<tag>.js",))`; `ModuleScript` resolves it as `static("js/dist/elements/<tag>.js")` — matches the `outDir`.
