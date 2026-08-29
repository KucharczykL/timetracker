# CLAUDE.md

Guidance for Claude Code (claude.ai/code) when working in this repository.

## Environment: drive everything through `make`

**Run `make <target>`. Do not wrap commands in `direnv exec .`** (it re-enters the
shell and re-runs `uv sync` for ~70 packages), **and do not reach around the
Makefile for raw `uv run` / `pnpm` / `pytest`.** If something has no target, add
one or extend an existing one — that is the intended way to grow this file.
Focused runs are already covered:

```
make test ARGS="tests/test_filters.py -k relation -x"
make test-e2e ARGS="-k widgets"
```

**`make check` runs anywhere — no Nix shell required.** The Makefile
version-proofs both interpreters, because getting either wrong produces failures
that look like the code's fault:

- **Python 3.14** — `ensure-python` finds or provisions it; `uv` pins the
  interpreter itself.
- **Node ≥ 26** — `ts/date-time-presentation.ts` uses `Temporal`, which arrives in
  Node 26. On Node 24 it is `undefined`, the date/time formatters return `null`,
  and ~11 vitest assertions fail. When `PATH` already has 26 it is used as-is;
  otherwise pnpm fetches the pinned version. `ensure-node-runtime` verifies what
  the JS commands will *actually* run on (`pnpm exec`, not `PATH`), so an offline
  first run fails with the reason instead of a wall of null assertions.
  `ensure-node-deps` adds that *this project's* pinned dependencies are installed
  into that runtime, not whatever global tsc `pnpm exec` would fall back to.

Every node invocation in the Makefile goes through `pnpm`: that is the single
switch redirecting the whole JS toolchain onto the right runtime. A new
node-using target must depend on **`ensure-node-deps`**, which pulls the runtime
gate in behind it. The one exception is the `npm` target itself, which depends on
`ensure-node-runtime` alone — gating the target that *creates* the install behind
a check for that install would make it refuse to run in the one state it repairs.

A real browser for e2e is found from the system; the shell does not vendor one.
`e2e/conftest.py` discovers it in order: `E2E_CHROME` (explicit path — a missing
file errors), then `google-chrome`/`chromium`/`chrome` on `PATH`, then well-known
Windows/macOS install locations. So `make test-e2e` works on a normal Chrome
install with no `playwright install`; set `E2E_CHROME` only for a non-standard path.

**Verification gate:** before declaring done / pushing / opening a PR, run the full
`make check` (lint + format-check + mypy + ts-check + vitest + the entire pytest
suite **including `e2e/`**) and confirm it is green. Never verify with a hand-picked
subset of test files — that is how removed-widget e2e breakage reaches CI. `ARGS` is
for iterating, never for the gate.

**While iterating, use `make check-fast`** — the same aggregate minus `e2e/`, which
is 83% of the suite's serial wall time (~70s vs ~6.5 min). It is explicitly **not**
the gate: only the full `check` catches e2e breakage.

The suite runs in parallel locally (pytest-xdist), because it is dominated by
browser page loads: 2507 tests take ~55s at 16 workers against ~370s serial.
`PYTEST_WORKERS` defaults to half the cores, capped at 16 — past that, contention
starts flaking timing-sensitive e2e tests. **CI sets `CI`, which defaults it to
`-n 0`**: `ubuntu-latest` is 4 vCPU, where the win is small and a
scheduling-induced red CI on a green local run is a bad trade. Set
`PYTEST_WORKERS=0` when debugging — parallel output interleaves and `-x` stops
only the worker that hit it.

### Python 3.14 is a hard prerequisite

`pyproject.toml` pins `requires-python = ">=3.14,<4"`, and the code **depends on
3.14-only syntax** — most notably **PEP 758** unparenthesized `except A, B:`
("catch both types", not the Python-2 `except A as B` binding). The pinned
**ruff 0.16.x** infers target 3.14 from `requires-python` and *formats to* that
bare form, so the source cannot be made to parse on an older interpreter without
fighting the formatter.

**A `SyntaxError` in `except …` / a "`make check` is red on `main`" report almost
always means the environment is running the wrong Python**, not that `main` is
broken. Check `python --version` first — it must be 3.14.x.

Outside Nix (Windows, restricted cloud boxes), either route works:

- **conda-forge**: `conda create -n timetracker python=3.14`, then install `uv`,
  Node 26 + `pnpm@10.33.0`, and run the same `make` targets from the activated env.
- **uv-managed**: `uv python install 3.14` then `uv sync`. **Watch uv's own
  version**: uv bakes its interpreter list into the binary, so uv 0.8.x can only
  offer **3.14.0rc2** — which passes a `>= 3.14` check yet cannot run the project
  (pydantic calls `typing._eval_type(..., prefer_fwd_module=True)`, a kwarg added
  in 3.14 *final*, so `import ninja` dies with `AssertionError`). If you get an
  `rc`, upgrade uv (`pip install --upgrade uv` works where `uv self update` is
  firewalled) and reinstall. pnpm must be on `PATH` separately; Node 26 itself
  need not be, since pnpm fetches it.

Either way the e2e suite needs a **system Chrome/Chromium** and, on Linux, the
`LD_LIBRARY_PATH` that greenlet/`pytest-playwright` want (the Nix shell sets this;
a bare conda/uv env may need it exported). Non-Nix setups are best-effort; **CI
runs the Nix path**, so verify against `make check` before pushing when possible.

## Commands

| Task | Command |
|------|---------|
| Install dependencies | `make init` (Python via uv + npm packages, loads platform fixtures) |
| Development server | `make dev` (Django runserver + Tailwind watcher + `tsc --watch`) |
| Production-like dev | `make dev-prod` (Caddy + Gunicorn/Uvicorn + Django-Q cluster) |
| Run tests | `make test` (pytest; also runs vitest via its `test-ts` prereq) |
| Run a subset of tests | `make test ARGS="tests/test_filters.py -k relation -x"` (same for `make test-e2e ARGS=…`) |
| Run TypeScript tests | `make test-ts` (vitest over `ts/**/*.test.ts`) |
| Make / apply migrations | `make makemigrations` / `make migrate` (`ARGS="games 0024_libraryidempotencyrecord"` targets one) |
| CSS (Tailwind) | `make css` |
| Django shell | `make shell` |
| Create superuser | `make createsuperuser` |
| Dev login (superuser + prefill) | `make devlogin` (idempotent `admin`/`admin`; pairs with `DEV_LOGIN_PREFILL`) |
| Format / lint Python | `make format` / `make lint` / `make lint-fix` |
| Type check (mypy) | `make typecheck` |
| Lint prose (docs + code comments) | `make vale` (terminology; see [Vocabulary](docs/vocabulary.md)) |
| Codegen element types (TS props) | `make gen-element-types` |
| Codegen icon nodes | `make gen-icons` (after editing `games/templates/icons/*.html`) |
| Lint + format check + mypy + vale + ts-check + vitest + tests | `make check` (CI runs exactly this) |
| Same aggregate minus `e2e/`, for iterating | `make check-fast` (**not** the verification gate) |
| Run every test except `e2e/` | `make test-fast` |
| Sync uv.lock | `uv sync` (after editing pyproject.toml) |
| Verify the UUID identity map | `make audit-uuid-identity` (read-only; fails on any violation) |
| Benchmark commands, replay, and per-event cost | `make bench` (~1.7 min, seeds and removes a scratch library; **not** in `make check`) |
| Load platform fixtures / sample data | `make loadplatforms` / `make loadsample` |
| Regenerate sample data (anonymized prod) | `make anonymize-sample` (see Testing) |
| Dump games data | `make dumpgames` |
| Fetch a dump of the deployed database | `make fetch-dump` (→ `.dumps/`; needs `PROD_SSH_HOST`/`PROD_DB_CONTAINER` in `.env`) |
| Restore the newest dump into a scratch database | `make restore-dump` (prints its `DATABASE_URL`; `DUMP=<path>` picks another) |
| Restore, migrate, and drop it on success | `make verify-dump` (`KEEP=1` keeps the copy — the pre-deploy rehearsal) |

## Architecture

A Django 6+ monolith (v1.7.0) with a single app (`games/`) for tracking video game
purchases, play sessions, and statistics. HTMX for interactivity over a pure-Python
server-side component system, plus a Django Ninja REST API. **pydantic** is a
declared runtime dependency, not just Ninja's transitive one: the event vocabulary
(`games/events/vocabulary.py`) validates every event payload with a `TypeAdapter`.

```
games/          — Django app: models, views, templates, forms, signals, tasks, API,
                  filters, writes/ (the command-backed write path for PlayerGame)
common/         — Shared utilities: time formatting, component system, criteria, layout, icons
timetracker/    — Django project: settings, URL root, ASGI/WSGI
tests/          — Pytest tests
e2e/            — Playwright browser tests (run via `make test-e2e`)
contrib/        — One-off scripts (exchange rate import)
docs/           — Additional documentation
```

### Models (in `games/models.py`)

- **Game** — the catalog row: `name`, `platform` (FK), `playtime` (DurationField updated via signal), `year_released`, `sort_name`, `wikidata`. `status` (u/p/f/r/a) and `mastered` are stranded columns since #678 D2 — nothing writes them, nothing reads them, #770 drops them
- **Platform** — `name`, `group`, `icon` (slug, auto-generated from name)
- **Purchase** — ownership type, prices, currency conversion (`converted_price`, `price_per_game` is a `GeneratedField`), M2M to Game. `num_purchases` counts linked games. DLC/SeasonPass/BattlePass must have a `related_game` (reverse accessor `game.addon_purchases`)
- **Session** — `timestamp_start`/`timestamp_end`, `duration_manual`, `device` (FK), `note`, `emulated`. `duration_calculated`/`duration_total` are `GeneratedField`s
- **Device** — `name`, `type` (PC/Console/Handheld/Mobile/SBC/Unknown)
- **PlayEvent** — marks when a game was started/finished (separate from Sessions); `days_to_finish` is a `GeneratedField`
- **ExchangeRate** — cached FX rates per currency pair per year
- **GameStatusChange** — the legacy audit log of status transitions, ordered by `-timestamp`. Nothing writes or reads it since #678 D1: the event stream is the record and `games/reads/playergame_history.py` is the one reader. The backfill still reads the old rows; #771 takes the table
- **FilterPreset** — saved filter config; `mode` (games/sessions/purchases/playevents), `find_filter`, `object_filter`, `ui_options` (all JSON). Follows Stash's SavedFilter pattern
- **PlayerGame** — the first projection: one row per catalog game a library tracks, written only by the `PlayerGames` projector. Its `removed_at` is the projector's, stated by a `RemovePlayerGame` command, and separate from the catalog row's. It states the library's `status` (the six `PlayerGameStatus` words) and `mastered`, and since #678 D2 it is the only place either is stated or read. Both `UUIDv7Field` defaults are opted out (the pk is the event's `aggregate_id`); `game` is `RESTRICT`, so a projection row is never collateral

**Nothing a user removes is destroyed** (#944). The seven removable models —
Game, Platform, Device, Session, PlayEvent, Purchase, FilterPreset — each carry a
nullable `removed_at`, listed in `REMOVABLE_MODELS` in `games/removal.py`.
`remove(instance)` stamps it, `restore(instance)` clears it, and both use an
`UPDATE` rather than `save()`, so a stamp revalidates nothing and fires no
`post_save`. What a signal would have done, `_AFTER_STAMP` does by hand: a
removed Game recounts its purchases, a removed Session recalculates the
playtime. `for_library()`/`visible_to()` call `.alive()`, so a removed row
leaves every list, form, filter and API response at once; the plain manager
still sees it. A Purchase is live while any of its games is, or while it names
none. Only a whole-library purge destroys anything.

**A multi-game Purchase is an *unsplittable* bundle** — one price, whole-purchase
refund (e.g. a Humble Bundle). Independently-refundable multi-item orders (e.g. a
Steam cart) are modeled as **separate single-game purchases**: the add-purchase
form's "separate price per game" mode (≥2 games) creates them, and the row's
**Split** action breaks an existing bundle into per-game purchases (price split
evenly as a starting point). This is why per-game refund/price need no
through-model — each refundable unit is its own Purchase.

**Unset platform/device is NULL**: `Game.platform`, `Purchase.platform`, and
`Session.device` are nullable and stay NULL when unset — there are no sentinel rows
(#290 removed them). "Unspecified" (platform) and "No device" are render-layer
labels only. All three FKs use `on_delete=SET_NULL`, exclude-mode set criteria match
NULL rows (`_SetCriterion._not_in_q`), and a conditional `UniqueConstraint` keeps
(name, year) unique among platformless games.

**GeneratedField constraint**: `duration_calculated`, `duration_total`,
`price_per_game`, `days_to_finish` are computed by the database and cannot be
written from application code.

### Key patterns

**Layout system** (`common/layout.py`): views call `render_page(request, content,
title=...)` instead of Django's `render()`. This assembles a full HTML document via
`Page()` — analogous to FastHTML's `fast_app()`: `<head>`, navbar, toast container,
FOUC-prevention script, and **JS includes** (it calls `collect_media(content)` and
emits the `<script>` tags automatically, so views do **not** pass `scripts=` for
component-owned JS). `scripts=` remains only for page-specific glue not owned by a
reusable component (e.g. `add_*.js`). The navbar shows today's/last-7-days playtime
from the `model_counts` context processor.

**Component system** (`common/components/`): a FastHTML-style **lazy node tree**.
Components are `Node` objects that render to HTML only when asked (`str(node)` /
`Page()`), so `Page()` can walk a finished tree and collect each component's JS.
Submodules re-exported via `common/components/__init__.py`:

- **`core.py`** — the node layer. `Node` (base; `__html__`/`__str__` return a
  `SafeString`), `Element` (the single class for *any* HTML element), `Safe`
  (pre-rendered/trusted HTML), `Fragment` (ordered children, no wrapper tag — use
  instead of `str(a)+str(b)`), `BaseComponent` (implement `render()`, declare
  `media`), `Media` (declarative JS deps with order-preserving dedup merge;
  `collect_media()` sums them over a tree, `node.with_media(...)` attaches them).
  `_render_element()` is `@lru_cache`-memoized (4096). Attribute values are always
  escaped. **Children: every string child is escaped — `SafeText`/`mark_safe`
  included; only `Node` children (so `Safe`) render unescaped.** `randomid()`
  generates stable hash-based IDs.
- **`primitives.py`** — generic HTML. Plain leaf builders (`A`, `Button`, `Div`,
  `Span`, `Table`, `Form`, `H1`, …) are **generated from a whitelist** via the
  `_html_element(tag)` factory — not hand-written per tag. Builders that add
  classes/behaviour are written out:
  `ControlButton()` (the one polymorphic button/link builder: `href=` renders `<a>`,
  `method="post"` renders a `<form>`+submit, default `<button>`), `ButtonGroup()`,
  `Input()`, `Checkbox()`, `Radio()`, `Pill()`, `Icon()`, `Popover()`,
  `TruncatedText()`, `SearchField()`, `PageHeading()` (badge heading; the plain
  `<h1>` is the generated `H1`), `Modal()`, `ConfirmPage()` (full-page POST
  confirmation — the canonical removal affordance; `details` is a block slot beside
  `message`, which renders inside a `<p>`), `StyledTable()`, `TableRow()`,
  `TableTd()`, `TableHeader()`, `ContentContainer()` (the page-body width container,
  `w-full max-w-7xl self-center` — every list/detail/stats body sits in one),
  `paginated_table_content()`, `AddForm()`, `YearPicker()`,
  `CsrfInput()`/`ModuleScript()`/`StaticScript()`.
- **`domain.py`** — `GameLink()`, `GameStatus()`, `GameStatusSelector()` (Alpine.js
  PATCH dropdown), `SessionDeviceSelector()` (ditto), `LinkedPurchase()`,
  `NameWithIcon()`, `PriceConverted()`, `PurchasePrice()`
- **`filters.py`** — filter widget layer: criterion-blob parse helpers
  (`_*_from_field`, `_choice_from_raw`, `parse_filter_dict`), widget builders
  (`StringFilter`, `NumberFilter`, `_bool_control`, the `FilterSelect` adapters),
  `field_widget`/`field_widget_templates` (the single per-field dispatcher the quick
  bar + nested builder render through), the builder's comparison-row/chip/relation
  templates, and `FilterFieldPicker`
- **`quick_filter.py`** — `QuickFilterBar()`, `QUICK_FACETS`, `is_quick_editable`
  (see Filter system below)
- **`search_select.py`** — the combobox family, all built on a shared
  `_combobox_shell` and wired by `ts/elements/search-select.ts`: `SearchSelect()`
  (form combobox; with `host_dropdown=True`, set by the `SearchSelectWidget` form
  adapter, it lives in a `<drop-down behavior="inline-combobox">` so its panel
  shares the one attachMenu open/close/position/dismiss engine, #348),
  `FilterSelect()` (include/exclude with pinned Any/None modifiers;
  `layout="panel"` is the GitHub-label-picker personality for hosting inside a
  dropdown dialog, #315), `ComboboxDropdown()` (generic "Label ▾" trigger +
  dialog), `PresetSelect()`/`LoadPresetDropdown()` (fetch-on-open preset picker,
  #297), `SearchSelectOption`
- **`date_range_picker.py`** — `DateRangePicker()`/`DateRangeField()`/
  `DateRangeCalendar()` custom element (wired by `ts/elements/date-range-picker.ts`)

**Filter system** (`games/filters.py` + `common/criteria.py`): Stash-inspired
structured filtering.

- `common/criteria.py` defines typed criterion classes — `StringCriterion`,
  `IntCriterion`, `FloatCriterion`, `DateCriterion`, `BoolCriterion`,
  `MultiCriterion`, `ChoiceCriterion` — each with a `modifier` (`Modifier` enum:
  EQUALS, NOT_EQUALS, INCLUDES, EXCLUDES, GREATER_THAN, LESS_THAN, BETWEEN, IS_NULL,
  …) and a `to_q(field_name)` method. `OperatorFilter` provides AND/OR/NOT
  sub-filter composition and JSON serialization.
- `games/filters.py` defines `GameFilter`, `SessionFilter`, `PurchaseFilter` (all
  `@dataclass` subclasses of `OperatorFilter`) and `FindFilter` (sort/pagination).
  Filters serialize to/from JSON and travel in the `?filter=` query parameter;
  `parse_game_filter()` / `parse_session_filter()` / `parse_purchase_filter()`
  deserialize. `FilterPreset` stores named configurations.
- **Quick filter bar** (#197/#315, `common/components/quick_filter.py` +
  `ts/elements/quick-filter-bar.ts`) is **THE one filter tier** above every list
  view — a GitHub-style row of ghost "Label ▾" dropdown facets directly above the
  table. The flat FilterBar family is gone (#315), as is the free-text search UI
  (the `search` criterion remains server-side inside the `?filter=` JSON; there is
  no `?search_string=` fallback).
  - Facets are own-model leaf fields of any `QUICK_FACET_KINDS` kind
    (set/number/date/string/bool; flat aggregates like `session_count` count as
    number), rendered via `field_widget(layout="panel")` with a `quick-` name prefix
    inside a form whose Apply button (or Enter in an inline input) serializes them
    and navigates. Clear is a plain link to the bare list URL. Set → panel
    `FilterSelect`; date → `DateRangePanel`; number/string/bool → the stacked widget
    embedded as-is. The per-mode facet lists live in `QUICK_FACETS`.
  - Row anatomy: collapsible facets, then the "⋯" priority-plus overflow menu
    (ResizeObserver-driven, continuous, no breakpoints — facets that don't fit are
    MOVED into it, same DOM nodes so widget state survives), then non-collapsible
    furniture — the Load-preset picker (`preset_api_url`, load-only) and the
    Apply | Clear [| Advanced filter…] ButtonGroup (`builder_url` gates the third
    segment). `apply_url` overrides every derived list URL (the #304
    synthetic-harness constraint).
  - Editable only when every top-level filter key is a facet field with a dict
    criterion (`is_quick_editable`); operator keys, `*_filter` relations,
    `field_comparisons`, `search`, or any non-facet leaf degrade it to a read-only
    "Advanced filter active" pill with Edit-in-builder/Clear links. The bar's
    serializer emits only flat facet criteria, so its own output always round-trips
    back to editable. Anything the facets can't express lives in the nested builder,
    reached via "Advanced filter…" — every filterable mode has a builder page,
    including devices/platforms (#336).

**Views** (`games/views/`): function-based, decorated with `@login_required`,
organized by domain entity:

- `session.py`, `game.py`, `purchase.py`, `playevent.py`, `platform.py`,
  `device.py`, `statuschange.py` — CRUD per entity
- `general.py` — `stats()`, `stats_alltime()`, `index()`, the `model_counts` and
  `global_current_year` context processors
- `returns.py` — route classification (`READ_ONLY` / `ORIGIN_AWARE` / `CONFIRMATION`
  / `IN_PLACE`, guarded for completeness against the route table) plus
  `origin_from()` and `return_url()`, the app-bound half of `common/returns.py`
- `removal.py` — `confirm_and_remove()`: GET renders a `ConfirmPage`, POST stamps
  `removed_at` and returns to the origin. Every `remove_*` view is one call to it,
  over `confirm_and_apply()`, which the same module keeps for any other
  confirmed POST
- `stats_data.py` — `compute_stats(year)` → a `StatsData` TypedDict; pure computation
- `stats_content.py` — renders stats page content from a `StatsData`
- `stats_links.py` — pure filter-link builders for stats rows/counts (#65);
  parity-tested so each builder's queryset count equals the stat it links from
- `auth.py` — custom `LoginView`, renders via `render_page()`

Filter presets have no classic views — they live on the Ninja API; the picker UI is
the shared combobox dropdown (#297).

**Signals** (`games/signals.py`):
- `pre_save` on Purchase: snapshots old price/currency for change detection
- `post_save` on Purchase: sets `needs_price_update` if price/currency changed
- `m2m_changed` on Purchase.games: updates `num_purchases` from the live games
  (`games.removal` recounts after a stamp, which fires no signal)
- `post_save`/`post_delete` on Session: recalculates `Game.playtime` from the aggregate

**Background tasks**: a django-q2 cluster (1 worker, 60s timeout, 120s retry, ORM
broker) runs `games.tasks.convert_prices()` on a schedule, fetching rates from
`cdn.jsdelivr.net/npm/@fawazahmed0/currency-api` and converting purchase prices to
the resolved site `DEFAULT_CURRENCY`.

**HTMX toast middleware** (`games/htmx_middleware.py`): converts Django messages
into `HX-Trigger` headers with a `show-toast` event; skipped if `HX-Redirect` is
present. Rendering is client-side (`games/static/js/toast.js`).

**REST API** (`games/api.py`): Django Ninja routers mounted at `/api/`:
- `GET /api/games/search` — search games for autocomplete
- `PATCH /api/games/{id}/status` — update game status
- `GET/POST /api/playevent/`, `GET/PATCH/DELETE /api/playevent/{id}`
- `PATCH /api/session/{id}/device` — update session device
- `GET /api/presets/` — the user's presets for a mode, shaped as combobox options
  (`limit=0` = unbounded)
- `POST /api/presets/` — upsert on (user, mode, name); 201 create / 200 update
- `DELETE /api/presets/{id}` — remove an owned preset (404 for non-owner). DELETE
  is the transport's word; the row stays and `removed_at` is set

### Templates

Only a few HTML templates remain; the bulk of the UI is Python components.

- `games/templates/icons/<slug>.html` — SVG icon snippets; **source** for the icon
  codegen (`manage.py gen_icons` → committed
  `common/components/icons_generated.py`), not loaded at runtime
- `games/templates/` — minimal partials for HTMX responses where needed

### Frontend stack

- **HTMX** — partial page updates
- **Alpine.js** (vendored) — reactive dropdowns (`GameStatusSelector`,
  `SessionDeviceSelector`), toast store
- **Flowbite** — its CSS theme and semantic tokens remain in use; the legacy
  `flowbite.min.js` bundle is a vendored static asset only
- **Tailwind CSS** — compiled from `common/input.css` → `games/static/base.css`
- All third-party JS is served locally from `games/static/js/` (no CDNs), so pages
  and browser tests work offline
- **Custom JS** is authored in TypeScript under `ts/`, compiled to
  `games/static/js/dist/` (gitignored, build-only): `ts/toast.ts` (Alpine toast
  store; also defines `window.fetchWithHtmxTriggers`),
  `ts/elements/search-select.ts`, `ts/utils.ts` (shared helpers — `onSwap`,
  `toISOUTCString`, …)
- **Widget initialization**: widget JS registers with `onSwap(selector,
  initializeElement)` from `ts/utils.ts` — a port of FastHTML's `proc_htmx` built on
  `htmx.onLoad`, running the initializer once per matching element on page load and
  inside every htmx-swapped fragment. Never hand-roll
  `DOMContentLoaded`/`htmx:afterSwap` listeners with per-element guard flags.

### Interactive components: custom elements + TypeScript

New interactive components are **custom elements**, not inline JS in Python. A
component that needs behavior emits a semantic tag via `custom_element("tag",
Props(...))` (light DOM, server-rendered inner markup built with the htpy-style node
builders). Behavior lives in `ts/elements/<tag>.ts` (vanilla DOM,
`customElements.define`); the native `connectedCallback` replaces `onSwap` (it fires
on parse *and* htmx swap). The server↔client contract is one Python `TypedDict` per
element registered with `register_element(...)` in
`common/components/custom_elements.py`; `manage.py gen_element_types` codegens
`ts/generated/props.ts` so renaming a prop fails `tsc`.

- **Build:** `tsc` per-module compiles `ts/` → `games/static/js/dist/`. `make ts` =
  codegen + compile; `make ts-check` (in `make check`) = codegen + `tsc --noEmit -p
  tsconfig.check.json`; `make dev` runs `tsc --watch`. Docker builds CSS + TS in a
  Node stage. Run `make ts` after editing any `.ts` so e2e/local serving sees fresh
  output. **Two tsconfigs:** the emit `tsconfig.json` **excludes** `ts/**/*.test.ts`;
  `tsconfig.check.json` re-includes them and adds `@types/node` (scoped there, so
  the browser emit stays node-free).
- **htpy-style markup:** builders take kwargs attributes and `[]` children —
  `Div(class_="x", hx_get="/y")[child1, child2]` (`class_`→`class`, `hx_get`→
  `hx-get`, `True`→`name="name"`, `False`/`None`→omitted). A runtime-built attribute
  collection goes in the single positional slot: `Div(attrs_list, class_="x")`.
  Still a walkable `Element` tree, so `Media` bubbles. `attributes=`/`children=`
  kwargs are rejected (`TypeError`).
- **Do NOT** author HTML/JS as Python f-strings or add new inline Alpine `x-data`
  blobs. Alpine remains only for trivial pre-existing toggles.
- **Tables bubble cell media:** `StyledTable` returns a node tree, so a custom
  element in a table cell has its `Media` collected automatically — no manual
  `collect_media` step.

### Deployment

Multi-stage Dockerfile (uv builder → Node assets stage → slim runtime), Caddy as
reverse proxy on port 8000, Gunicorn with UvicornWorker (ASGI), Supervisor managing
Caddy + Gunicorn + django-q2. `make dev-prod` mimics production locally. CI/CD via
`.github/workflows/build-docker.yml`: a `test` job runs `make check`, then
`build-and-push` builds + pushes the image on `main`.

**Package manager (pnpm), not npm.** Node 26 does not bundle Corepack: the Nix shell
provides `pnpm_10`, while CI and Docker explicitly install the `pnpm@10.33.0`
declared in `package.json`'s `packageManager` field. To bump pnpm, update that field
and every explicit install command — `scripts/bootstrap-cloud-env.sh` reads the
field, so it needs no edit. pnpm disables dependency lifecycle scripts by default
(opt in via `pnpm.onlyBuiltDependencies`). One dependency is on that list:
`@vvago/vale` ships a platform binary its postinstall downloads. pnpm links the
`bin` before running that script, so a plain `pnpm install` leaves no `vale` —
`make npm` and the CI step both follow it with `pnpm rebuild @vvago/vale`. The
Docker stages keep `--ignore-scripts` and never fetch it; nothing there lints.

### Database

PostgreSQL 18 is required. Development uses `make ensure-postgres` (normally via the
Nix shell) to provision an ignored loopback-only cluster; deployments supply
`DATABASE_URL`. Every connection must use UTF-8, the `builtin` locale provider, and
`C.UTF-8` — full contract in [Database contract](docs/database.md). Migrations live
in `games/migrations/`. Note the `GeneratedField`s (above).

### Configuration

All configurable Django settings are read through `config()` in
`timetracker/config.py`, never bare `os.environ` in `settings.py`. Full reference:
`docs/configuration.md`.

- **Resolution priority** (highest first): `NAME__FILE` (opt-in file secret) →
  `NAME` env var → `.env` → `settings.ini` (`[timetracker]` section) → in-code
  default. Missing + no default = `ImproperlyConfigured`.
- `config(name, *, default, cast, allow_file, required_in_prod)`: `cast` handles
  `bool`/`list`/`int`/`Path`/callable; `allow_file=True` honors `NAME__FILE`
  (contents `.strip()`-ed); `required_in_prod=True` hard-fails when missing and
  DEBUG is off.
- `DEBUG` defaults `True`, turned off with `DEBUG=false`. `PROD` is a **deprecated
  alias** kept for one release.
- `SECRET_KEY` is required in production (insecure default only in DEBUG); supports
  `SECRET_KEY__FILE`.
- `APP_URL` accepts one full URL or a comma-separated list; `ALLOWED_HOSTS` and
  `CSRF_TRUSTED_ORIGINS` are derived from all of them. `ALLOWED_HOSTS` can be
  overridden directly (e.g. `ALLOWED_HOSTS=*` behind a reverse proxy);
  `CSRF_TRUSTED_ORIGINS` is always derived from `APP_URL`.
- `TIME_ZONE` reads `TZ` (defaults `Europe/Prague` in debug, `UTC` in prod).
- Django Admin, Debug Toolbar, and `django_extensions` are `DEBUG`-only.
- `DEV_LOGIN_PREFILL` (**dev/staging only**, off by default): `username:password`
  prefills the login form and sends `X-Robots-Tag: noindex` — login still POSTs and
  authenticates (not a bypass). `make dev` sets `admin:admin`; `make devlogin`
  provisions that superuser. Parsed once (lru_cache) via `prefill_credentials()` in
  `games/dev_login.py`; malformed values fail safe. All three prefill branches are
  flag-guarded, so production is inert.
- **Container/entrypoint-only** flags (`CREATE_DEFAULT_SUPERUSER`, `STAGING`,
  `LOAD_SAMPLE_DATA`) live in `entrypoint.sh`, not the Python config. The container
  runs as uid 1000 (no root, no PUID/PGID remap); mounted data dirs must be writable
  by that uid.

## Testing

Tests live in `tests/`; run with `make test`. Pytest settings are in
`pyproject.toml` under `[tool.pytest.ini_options]`. Tests use PostgreSQL databases
created by Django from `DATABASE_URL`; pytest-xdist gives each worker its own test
database. Most files are named after what they cover; the less obvious ones are
`test_paths_return_200.py` (smoke-tests every list/view URL),
`test_rendered_pages.py` (HTML output of pages), `test_signals.py` (playtime recalc,
status-change audit, …), and `test_anonymize_sample.py` (the fixture anonymizer's
rollback safety, determinism, invariants, round-trip).

**`games/fixtures/sample.yaml.gz`** (the `make loadsample` seed) is a **generated,
anonymized production snapshot** — gzip-compressed (~147 KB vs 1.6 MB raw), do not
hand-edit. Regenerate with `make anonymize-sample` against a dedicated restored
production PostgreSQL database (then `make migrate`). It randomizes prices,
game↔purchase links, and dates (per-game offset), clears free-text notes/names, and
sanitizes audit timestamps — all inside a rolled-back transaction, so the source DB
is untouched. Output is **byte-deterministic** per `--seed`. The fixture keeps prod
pks, so load it into an empty dev DB.

**A UI assertion is not a database assertion.** Several custom elements update the
DOM optimistically before their POST lands (`play-event-row.ts` bumps the play count
on click). Before reading the ORM in an e2e test, wait on something *server-rendered*
— the htmx section that swaps in after the write commits.

**TypeScript unit tests** (vitest) live beside their modules as `ts/**/*.test.ts`,
run with `make test-ts` and automatically by `make test`/`make check`. The pnpm
script passes Node 26's `--no-experimental-webstorage` so jsdom, not Node's
experimental global, provides `localStorage`. vitest resolves the NodeNext-style
`.js` specifiers to the sibling `.ts`, so no compile step is needed. The filter-tree
serializer (`ts/elements/filter-tree/`, #188) is covered this way plus a
**cross-language contract** (`tests/test_filter_tree_contract.py`): vitest writes
`fixtures.canonical.json` (the serializer's output for the shared `fixtures.json`
cases, gitignored) and the pytest test asserts each is `to_q()`-equivalent to the
source filter, so the TS serializer cannot drift from the Python backend. The
contract `skipif`-skips when the artifact is absent; `make check`/`make test` order
`test-ts` first.

**Browser/E2E tests** live in `e2e/` and run with `make test-e2e`
(`pytest-playwright` driving a real Chromium against pytest-django's `live_server`).
`e2e/conftest.py` sets `DJANGO_ALLOW_ASYNC_UNSAFE` and prefers a system
Chrome/Chromium (see the env section); otherwise `uv run playwright install
chromium` once. All JS is vendored, so the tests run fully offline. A bare
`make test` collects `e2e/` too, so it needs a browser as well. Key files:
`test_widgets_e2e.py` (onSwap lifecycle, FilterSelect/RangeSlider/add-purchase),
`test_search_select_e2e.py` (single-select edge cases on a synthetic page).

## Conventions for AI assistants

- **Never write to `GeneratedField`s** (`duration_calculated`, `duration_total`,
  `price_per_game`, `days_to_finish`).
- **One act, one verb** — an event type, its command and its projection column
  share one verb, and the column is `<act>_at`: a nullable `DateTimeField` whose
  null is the live state. See [Naming](docs/event-retention.md#naming).
- **Some words are refused** — a projector *replays* events; the row it leaves is
  the *projection*. `make vale` enforces the list over docs and over code
  comments, and [Vocabulary](docs/vocabulary.md) says why each word is refused
  and how to add one. Code is out of scope, so an identifier or a flag name that
  contains a refused word is fine. The check grades by meaning: the domain sense
  — the word next to an event, a projector, or the row it writes — is an
  **error** with one named replacement, and every other sense is a **warning**
  that prints without failing the build, because there the right word depends on
  what is joined.
- **Name variables with complete words** — unabbreviated identifiers in Python and
  TypeScript (`template` not `tpl`, `event` not `e`, `element` not `el`,
  `removeButton` not `removeBtn`, `option`/`value` not single letters in loops).
  Applies to new code and to code you touch.
- **Name compound types explicitly** — if a `tuple`/`dict`/other compound value is
  passed between functions or appears in multiple signatures, give it a name
  (`TypedDict`, `NamedTuple`, `type` alias) rather than repeating the structural
  annotation, even for small types: `LabeledOption = tuple[str, str]`,
  `RangeValues(min, max)`.
- **Name primitive roles too** — when a bare `str`/`int` stands for a domain concept
  (an id, key, token, field name), give it a PEP 695 transparent alias (`type
  SortKey = str  # e.g. "sort_name"`) so signatures say *which* string goes where.
  Zero-cost, no wrapping. Use `NewType` only when you want the checker to reject
  cross-assignment and will wrap every literal.
- **Use `render_page()` not `render()`** for all full-page HTTP responses (import
  from `common.layout`).
- **Build UI with Python components** from `common.components`, not raw HTML strings
  or Django templates. Build with `Div()`, `Span()`, `Element("tag", ...)`, etc.;
  use `Fragment(a, b, ...)` to group siblings (never `str(a)+str(b)`, which flattens
  the tree and drops media); wrap trusted pre-rendered HTML in `Safe(html)`. Plain
  strings — `SafeText` included — are auto-escaped as children.
- **Builders take htpy form only** — static attributes as kwargs, children via `[]`:
  `Builder(class_="x", hx_get="/y")[child1, child2]`. Dynamic attributes (a runtime
  `list[(name, value)]` or `Mapping`) go through the single positional slot. The
  generic and the six styled builders (`Input`, `Checkbox`, `Radio`, `Pill`,
  `ControlButton`, `SearchField`) **do not accept `attributes=`/`children=`** —
  passing either raises `TypeError`. Semantic params are keyword-only
  (`ControlButton(color="red")`, `Checkbox(name=…, checked=…)`, `Pill(label=…)`).
  Reach for the named builder a tag has; if a tag has none, add it to the whitelist
  in `primitives.py` and export it from `__init__.py`. The low-level `Element(tag,
  attributes, children)` keeps positional args — it is node machinery and a codegen
  target, not a call-site builder. Single-content-slot components support `[]` too
  (`Modal(id)[content]`, `DropdownActionItem(data_x="")[label]`); multi-slot or
  sibling-composing ones (`Popover`, `GameStatus`, `PageHeading`, `Icon`) keep their
  own `children=`/`attributes=` params. The badge page heading is `PageHeading`, not
  `H1`. The node layer owns attribute merging (`normalize_attributes`):
  `class`/`style` accumulate, other attributes are first-wins, so a caller `class_`
  appends to a builder's baked class and duplicate-attribute HTML is impossible.
- **JS-bearing components declare `Media`, they don't rely on the view** — give a
  component `class Media: js = (...)` or `return node.with_media(Media(js=...))`.
  `Page()` collects and emits it. Never re-add `scripts=ModuleScript(...)` threading
  in a view for a component that can declare its own dependency.
- **Filter views** accept `?filter=<JSON>`; free-text search rides inside it as a
  `search` criterion (there is no `?search_string=`). New criteria go in
  `games/filters.py`; new criterion *types* go in `common/criteria.py`.
- **Mutating links carry their origin** — build every link to a mutating view with
  `action_url(name, *args, origin=request.get_full_path())`, never a bare
  `reverse()`, and end every mutating view with `redirect(return_url(request,
  fallback=...))`. A new route must be classified in `games/views/returns.py` or the
  completeness guard fails. The origin travels only in the `?origin=` query
  parameter — never the session, never a form body — and is validated against the
  `READ_ONLY` route set, so it can never name a mutating target. It is `origin`
  rather than `next` because Django's auth views own `next`.
- **No route mutates on GET** — a removal answers GET with a `ConfirmPage` and acts
  on POST at the same URL (which is what lets `?origin=` ride through the
  confirmation for free); write them as one `confirm_and_remove()` call. Anything
  else that changes state is POST-only.
- **Signals handle side-effects** — do not manually recalculate `Game.playtime` or
  `Purchase.num_purchases`.
- **Buttons are `ControlButton`** — colors: `blue` (primary), `red` (destructive),
  `gray` (secondary), `green` (positive); variants: `filled` (default), `segmented`
  (ButtonGroup members), plus the colorless single-look toggles that ignore `color`
  — `outline` (bordered dropdown toggle), `ghost` (transparent until hover;
  quick-facet triggers), `plain` (navbar nav-link). There is no size parameter and
  no `icon=` flag: buttons are compact by default and upsize inside an `@container`
  ancestor ≥28rem (form/modal/confirm containers declare `@container`); icon+text
  layout (`inline-flex items-center gap-2`) is baked in. Never wrap a button in
  `A(href=…)` — pass `href=` to `ControlButton`; `method="post"` renders a no-JS
  `<form>` submit.
- **Read settings via `config()`** from `timetracker/config.py`, never bare
  `os.environ.get` in `settings.py`. Declare `cast`/`allow_file`/`required_in_prod`
  explicitly. Container-bootstrap flags belong in `entrypoint.sh`.
- **No styling-at-a-distance; elements carry their own classes**: `input.css` is
  document bootstrapping only (Tailwind import, theme, fonts, resets) — no
  form/component styling and no selectors that reach across the DOM (`#id
  descendant`, `form input:disabled`) to style something a component owns. An
  element's appearance, **including state** (`disabled:`, `has-[:disabled]:`,
  `focus:`), comes from utility classes emitted by its own component.
- **Forms render via `FormFields`/`AddForm`, never `form.as_div()`**:
  `FormFields(form, *, extras=...)` (in `primitives.py`) renders label + control +
  errors + row layout; native controls get their classes from
  `PrimitiveWidgetsMixin` (`games/forms.py`, which stamps
  `INPUT/SELECT/TEXTAREA_CLASS` incl. `disabled:` variants by widget type, skipping
  SearchSelect + checkbox). Every form is on this path, including login. `extras`
  appends a node into a named field's row.
- **Disabled form controls share one look** via the constants in `primitives.py` —
  `DISABLED_CONTROL_CLASS` (`disabled:opacity-50 disabled:cursor-not-allowed`, on
  the control itself) and `DISABLED_WITHIN_CLASS` (the `has-[:disabled]:` wrapper
  variant, for composites like `SearchSelect`). Reuse these; don't hand-roll a
  per-control disabled style.
- **Disabling composite widgets**: a composite widget carries its `id` on a wrapper
  `<div>`, which has no `disabled` state — setting `.disabled` on it is a no-op.
  Disable the inner control (for `SearchSelect`, the `[data-search-select-search]`
  input); the wrapper fades itself via `DISABLED_WITHIN_CLASS`.
- **Platform icons** are SVG snippets in `games/templates/icons/<slug>.html`,
  compiled to `Element` node trees by `make gen-icons` (committed
  `common/components/icons_generated.py`; drift-guarded in `make check`). Add/edit a
  snippet, run `make gen-icons`, reference by slug in `Platform.icon`. `Icon(name,
  attributes=...)` returns a node: `class` merges onto the svg, `title` becomes a
  `<title>` child. Never edit `icons_generated.py` by hand.
- **Inline Alpine.js** remains only in the pre-existing domain components
  (`GameStatusSelector`, `SessionDeviceSelector`): `x-data="{...}"` plus
  `fetchWithHtmxTriggers()` for PATCH calls. New behavior goes in a custom element.
- **Nothing destroys a record** — call `remove()`/`restore()` from
  `games/removal.py`, never `instance.delete()`, and write a confirmation as one
  `confirm_and_remove()` call. A new removable model needs `removed_at`, a place
  in `REMOVABLE_MODELS`, and a builder in `tests/test_removable_models.py`, which
  fails until it has one. `delete` is Django's word, not the library's: see
  [Vocabulary](docs/vocabulary.md), which `make vale` enforces.
- **A PlayerGame fact is stated as a command** — never assign `Game.status` or
  `Game.mastered` directly. Call `record_facts()` / `track_game()` from
  `games/writes/playergame.py`, or their request-shaped wrappers in
  `games/views/playergame_writes.py`. Nothing maintains the `Game.status` and
  `Game.mastered` columns any more, and #770 drops them: a command is the only
  way to state either fact, and the projection is the only place to read it.
- **A refused command becomes an answer** — wrap a dispatch in
  `answered(subject)` from `games/writes/answers.py`. It answers three ways, and
  a caller handles all three: a `CommandRejected` or a mapped `CommandConflict`
  becomes a `CommandFailed` carrying a sentence and a status code;
  `CommandNotPermitted` becomes an `Http404`, which a view lets rise; an unmapped
  conflict is re-raised as itself rather than given a sentence that might be
  wrong. A new conflict type goes in `CONFLICT_ANSWERS`, `ANSWERED_DIRECTLY` or
  `NOT_ANSWERED`, or `tests/test_command_answers.py` fails. Never translate one
  at a call site.
- **A rejection carries two sentences** — `raise CommandRejected(message,
  sentence=…)`. The argument explains the refusal to whoever reads a log or a
  traceback and may name an id or an issue; `sentence` is the only thing a
  person is shown. The boundary never reads `str(error)`, so a raise site that
  states no `sentence` is answered with `REFUSED` and logged, rather than
  leaking. Write one for every new raise site.
- **No dispatch inside a transaction** — `run_in_transaction` opens the
  transaction it retries and refuses to nest, so a view that dispatches carries
  no `@transaction.atomic` and calls no helper that does. `games.E008` refuses
  `ATOMIC_REQUESTS`. A test that POSTs through such a view needs
  `@pytest.mark.django_db(transaction=True)`.
