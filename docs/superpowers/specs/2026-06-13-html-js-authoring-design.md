# HTML + JS component authoring — design

**Date:** 2026-06-13
**Status:** Approved (design); pending implementation plan
**Branch context:** follows the lazy node-tree component system (`Element`/`Safe`/`Fragment`/`Media`) and the `Children`/`Attributes` typing work.

## Problem

Trusted HTML and JavaScript are authored as Python f-strings in several places. Two distinct pains:

- **HTML-as-string** — `Navbar`, `_TOAST_CONTAINER`, the played-row markup skeleton, and the generally verbose `Element("div", attributes=[...], children=[...])` call shape.
- **JS-in-string** — the genuinely ugly ones: `GameStatusSelector` (~70 lines) and `SessionDeviceSelector` (~50 lines) inline an Alpine `x-data="{...}"` blob with `fetchWithHtmxTriggers`, server-value interpolation (`{game.status}`), **and** `{{ }}` brace-doubling throughout; `_PLAYED_ROW_TEMPLATE` dodges the brace collision entirely by switching to `@@TOKEN@@` placeholders + a `.replace()` loop.

You cannot node-tree JavaScript, so the JS pain needs a different answer than the HTML pain. The newer widgets (`search_select`, `range_slider`, `filter_bar`) already moved behavior into real `.js` files wired by `onSwap` + `data-*` attributes; the Alpine selectors are the holdouts that still inline their JS.

## Goal

Establish the *right* way to author interactive, server-rendered components in this codebase, and convert a few exemplars to prove it. North-star principle:

> The server never writes a line of JavaScript. The server↔client boundary is a typed, declarative contract. Behavior lives in real, tooled TypeScript files.

## Decisions (locked during brainstorming)

| Decision | Choice |
| --- | --- |
| HTML authoring | **htpy-*style* sugar on the existing `Element`** (not the htpy library) — keeps `Media`/`collect_media`, no build step |
| JS runtime model | **Custom Elements** (Web Components), light DOM |
| Server↔client contract | **Typed contract + codegen** (one Python `Props` type → generated TS interface + reader) |
| JS language | **TypeScript** (real `.ts`, compiled) |
| Build tool | **`tsc` per-module** (no bundler) — preserves per-component `Media` loading |
| Alpine, for converted components | **Retired** — behavior rewritten as vanilla TS in the element class |
| Exemplars | **`GameStatusSelector` + `SessionDeviceSelector` + played-row** |
| Compiled output | **Build-only, gitignored** (produced by `make` + Docker) |
| Existing hand-written `.js` | **Left as-is**, migrated to TS later |

## Architecture

Three independent layers composing through one typed seam:

```
Python (server)                          TypeScript (client)
─────────────────                        ───────────────────
htpy-style Element  ──renders──►  <game-status-selector       ──connectedCallback──►  game-status-selector.ts
  + Media (kept)                     game-id="3" status="f">          (vanilla DOM behavior)
        │                                    ▲
        └── GameStatusSelectorProps ─codegen─┘  generated props.ts (interface + typed reader)
            (one Python type = the whole server↔client contract)
```

- **Layer 1 — htpy-style HTML** removes HTML-string / verbose-`Element` ugliness, pure Python, no build, `Media` untouched.
- **Layer 2 — Custom Elements (TS)** removes JS-string ugliness; behavior in real typed modules with a native lifecycle.
- **Layer 3 — Typed contract codegen** makes the seam type-safe in both languages from a single Python source.

### Layer 1 — htpy-style sugar on `Element`

Additive only. Existing `Element("div", attributes=[...], children=[...])` and `Div([("class","x")], "hi")` keep working.

- **Attributes as kwargs:** `Div(class_="card", hx_get="/x", disabled=True)`. Translation: trailing `_` stripped (`class_`→`class`); inner `_`→`-` (`hx_get`→`hx-get`, `data_id`→`data-id`); `True`→bare attribute, `False`/`None`→omitted.
- **Children via `[]`:** `Div(class_="card")[H1["Title"], body]`. `Element.__getitem__` normalizes through the existing `as_children` and returns an `Element` carrying the same attributes and media.

The result is still a walkable `Element` tree, so `collect_media` / `Media` are unaffected. This is the "htpy feel on our own node so the asset system survives" decision.

Example:

```python
Div(class_="flex gap-2 items-center")[
    Icon("play"),
    Span(class_="label")[name],
]
```

### Layer 2 — Custom Elements (TypeScript, light DOM)

- Python builder emits a **semantic tag**: `Element("game-status-selector", attrs).with_media(Media(js=("dist/elements/game-status-selector.js",)))`.
- **Light DOM** (no shadow root — Tailwind's global classes must apply). The server renders the inner markup (htpy-style); the element enhances it.
- **Native lifecycle replaces `onSwap`:** `connectedCallback()` fires when the browser parses or htmx-swaps the element in; `disconnectedCallback()` provides free teardown. No init registry, no guard flags.
- Behavior is **vanilla TS** — the element class owns its state (dropdown open/closed, PATCH-on-select via `fetchWithHtmxTriggers`). Alpine retired for these three.
- Source `ts/elements/<tag>.ts` → compiled `games/static/js/dist/elements/<tag>.js`, loaded only on pages that use it (via `Media`).

### Layer 3 — Typed contract (one Python type → the whole seam)

Each element declares its props once, in Python:

```python
class GameStatusSelectorProps(TypedDict):
    game_id: int
    status: str
    csrf: str
```

- The **Python builder** takes these typed args and serializes them to kebab-case attributes (`game-id="3"`).
- **Codegen** reads the registered Props types and emits, per component, into `ts/generated/props.ts`:
  - an **interface** — `GameStatusSelectorProps { gameId: number; status: string; csrf: string }`, and
  - a **typed reader** — `readGameStatusSelectorProps(el): GameStatusSelectorProps` that pulls and parses attributes (`Number(el.getAttribute("game-id"))`, etc.).
- The element imports the generated reader. The entire server↔client boundary is generated from one Python type: rename `game_id` in Python, regenerate, and `tsc` fails until the element updates. Drift is caught at build time; no hand-written `getAttribute` soup, no silent attr-name drift.

Type map: `int`/`float` → `number`, `str` → `string`, `bool` → `boolean`. Field `game_id` → attr `game-id` → TS prop `gameId`. Reader parsing follows the type (number → `Number(...)`, bool → presence / `=== "true"`, string → `getAttribute(...) ?? ""`).

## Toolchain (`tsc` per-module, build-only)

Layout:

```
ts/
  elements/game-status-selector.ts      # hand-written element classes
  generated/props.ts                     # codegen output (gitignored)
  globals.d.ts                           # ambient: window.fetchWithHtmxTriggers, htmx
tsconfig.json                            # strict, ES2022, lib [ES2022, DOM, DOM.Iterable]
                                         # rootDir: ts/  →  outDir: games/static/js/dist/
```

- **`games/static/js/dist/` is the only compiled output**, trivially gitignored, never colliding with hand-written `.js`. `Media` references `dist/elements/...`.
- **package.json**: add `typescript` devDep; scripts `build:ts` (`tsc -p tsconfig.json`), `watch:ts` (`tsc -p tsconfig.json --watch`).
- **Makefile**: `make ts` = codegen → `tsc`; `make dev` also runs `tsc --watch` (beside Django runserver + Tailwind watch); `make check` gains `tsc --noEmit` as a drift gate.
- **.gitignore**: `games/static/js/dist/`, `ts/generated/`.
- **Docker**: add a `make ts` step in the image build (npm already present for Tailwind); compiled JS baked into the image. Runtime stays offline.
- **TS lint/format**: deferred — `tsc --strict` is the only gate for now.

### Codegen mechanics

- A registry maps `tag → Props type` (e.g. a decorator `@element("game-status-selector", GameStatusSelectorProps)` on the Python builder, collected into a module-level registry).
- A Django management command (or script) imports the registry and writes `ts/generated/props.ts` (interface + reader per component).
- **Ordering:** codegen runs before `tsc` (the generated file is a `tsc` input). CI runs codegen then `tsc --noEmit`, so Python/TS drift fails the build. No committed generated artifact to diff against — `tsc` failing on drift is the gate.

## Exemplar conversions

1. **`GameStatusSelector` → `<game-status-selector game-id status csrf>`** — Python builds the light-DOM htpy-style; `game-status-selector.ts` wires the dropdown toggle + click→PATCH `/api/games/{id}/status` via `fetchWithHtmxTriggers` with CSRF, and updates the displayed status. Deletes the ~70-line f-string + brace-doubling.
2. **`SessionDeviceSelector` → `<session-device-selector>`** — same shape; PATCH `/api/session/{id}/device`.
3. **played-row → `<play-event-row>`** (non-Alpine) — deletes `_PLAYED_ROW_TEMPLATE` and the `@@TOKEN@@` / `.replace()` hack; Python builds markup htpy-style; `play-event-row.ts` owns the dropdown + add-playthrough POST. URLs are server-reversed and passed as attributes. Proves the pattern is not Alpine-only.

## Testing

- **Python**: builders render the correct tag + attributes (extend `test_components` / `test_rendered_pages`); assert no f-string remnants remain.
- **Type-check**: `tsc --noEmit` in `make check` — type errors, including contract drift, fail CI.
- **e2e (Playwright)**: real Chromium upgrades the custom elements natively; port/extend the existing widget-e2e pattern for all three (open dropdown → select → PATCH → DOM updates).

## Risks and mitigations

1. **Element module must be loaded before its tag appears.** Full-page render loads the module via `Media`; htmx row-swaps reuse the already-defined element. Constraint to document: a fragment response that introduces a brand-new element type must include that element's `Media`. (Same limitation class as today's "`onSwap` needs the script present.")
2. **A build step is now required** for `make dev` and Docker. One-time wiring, mitigated by Make/Docker integration.
3. **First TypeScript in the repo** — adds `typescript`, `tsconfig.json`, a Docker build step. Scoped to `ts/`; existing `.js` untouched.
4. **CSRF/PATCH parity** — the vanilla TS must replicate the Alpine version's fetch/CSRF/`HX-Trigger` behavior; it reuses the existing `fetchWithHtmxTriggers`; e2e guards it.
5. **Codegen ↔ build ordering** — codegen must precede `tsc`; encoded in `make ts`.

## Out of scope (YAGNI)

- Migrating the existing hand-written `.js` to TypeScript (later, incrementally).
- Bundling / minification of app JS.
- Shadow DOM / scoped styles.
- A general island / props-blob hydration runtime (custom elements cover these three).
- TS lint/format tooling (prettier/eslint).

## Future on-ramps (not now)

- **More custom elements**: migrate the remaining `onSwap` widgets to custom elements once the pattern is proven.
- **Existing `.js` → TS**: incremental, file by file (`tsc` checks mixed projects).
- The typed contract already positions the boundary for full type-safety as more client code becomes TS.
