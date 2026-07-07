# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Environment: run everything inside the Nix dev shell

This repo's toolchain (`pnpm`, `nodejs`, `uv`, `ruff`, and the `LD_LIBRARY_PATH`
that `pytest-playwright`/greenlet needs) is provided **only** by the Nix dev shell
defined in `shell.nix`, loaded automatically via `direnv` (`.envrc` = `use nix`).

**Every `make` / `pnpm` / `uv` / `pytest` command MUST run inside that shell.** A
bare `make check` (or `make ts`, `make css`, `pytest e2e/…`) run outside it has no
`pnpm` on `PATH`, so the TS compile and Tailwind build silently no-op or error,
`dist/` and `games/static/base.css` go stale/missing, and the e2e suite then fails
on CSS/JS-dependent assertions **locally only** — a green local run that breaks CI.
Do not work around this with a `pnpm` shim or a global install: that still misses
the pinned node, `LD_LIBRARY_PATH`, and `uv`/`ruff` the shell pins.

How to run commands (non-interactive tools/agents):

- **Preferred:** `direnv exec . <command>` — e.g. `direnv exec . make check`. Uses
  the cached direnv env. In a **fresh worktree** the `.envrc` is unapproved; run
  `direnv allow .` once first (first load runs `shell.nix`'s `shellHook`:
  `uv venv --clear` + `uv sync`, so it's slow once).
- **Fallback (no direnv):** `nix-shell --run "<command>"`.
- A real browser for e2e is found from the system (`google-chrome`); the shell does
  not vendor one.

**Verification gate:** before declaring done / pushing / opening a PR, run the full
`direnv exec . make check` (lint + format-check + mypy + ts-check + vitest + the
entire pytest suite **including `e2e/`**) and confirm it is green. Never verify with
a hand-picked subset of test files — that is how removed-widget e2e breakage reaches
CI.

## Commands

| Task | Command |
|------|---------|
| Install dependencies | `make init` (installs Python via uv + npm packages, loads platform fixtures) |
| Development server | `make dev` (runs Django runserver + Tailwind CSS watcher) |
| Production-like dev | `make dev-prod` (Caddy + Gunicorn/Uvicorn + Django-Q cluster) |
| Run tests | `make test` (pytest; also runs the vitest TS suite via its `test-ts` prereq) |
| Run TypeScript tests | `make test-ts` (vitest over `ts/**/*.test.ts`) |
| Make migrations | `make makemigrations` |
| Apply migrations | `make migrate` |
| CSS (Tailwind) | `make css` |
| Django shell | `make shell` |
| Create superuser | `make createsuperuser` |
| Format Python | `make format` (or `uv run ruff format`) |
| Lint Python | `make lint` (or `uv run ruff check`) |
| Auto-fix lint | `make lint-fix` (`ruff check --fix`) |
| Type check (mypy) | `make typecheck` (or `uv run mypy .`) |
| Codegen element types (TS props) | `make gen-element-types` |
| Codegen icon nodes | `make gen-icons` (after editing `games/templates/icons/*.html`) |
| Lint + format check + mypy + ts-check + vitest + tests | `make check` (CI-style aggregate; CI runs exactly this) |
| Sync uv.lock | `uv sync` (after editing pyproject.toml) |
| Load platform fixtures | `make loadplatforms` |
| Load sample data | `make loadsample` |
| Dump games data | `make dumpgames` |

## Architecture

A Django 6+ monolith (v1.7.0) with a single app (`games/`) for tracking video game purchases, play sessions, and statistics. Uses HTMX for interactivity with a pure-Python server-side component system, plus a Django Ninja REST API.

### Directory layout

```
games/          — Django app: models, views, templates, forms, signals, tasks, API, filters
common/         — Shared utilities: time formatting, component system, criteria, layout, icons
timetracker/    — Django project: settings, URL root, ASGI/WSGI
tests/          — Pytest tests
e2e/            — Playwright browser tests (run via `make test-e2e`)
contrib/        — One-off scripts (exchange rate import)
docs/           — Additional documentation
```

### Models (in `games/models.py`)

- **Game** — `name`, `platform` (FK), `status` (u/p/f/r/a), `mastered`, `playtime` (DurationField updated via signal), `year_released`, `sort_name`, `wikidata`
- **Platform** — `name`, `group`, `icon` (slug, auto-generated from name)
- **Purchase** — ownership type, prices, currency conversion (`converted_price`, `price_per_game` is a `GeneratedField`), links to Game via M2M. `num_purchases` counts linked games. DLC/SeasonPass/BattlePass must have a `related_game` (the base Game the add-on belongs to; reverse accessor `game.addon_purchases`). **A multi-game Purchase is an *unsplittable* bundle** (one price, whole-purchase refund — e.g. a Humble Bundle). Independently-refundable multi-item orders (e.g. a Steam cart) are modeled as **separate single-game purchases**, not one bundle: the add-purchase form's "separate price per game" mode (≥2 games) creates them, and the row's **Split** action breaks an existing bundle into per-game purchases (price split evenly as a starting point). This is why per-game refund/price need no through-model — each refundable unit is its own Purchase.
- **Session** — `timestamp_start`/`timestamp_end`, `duration_manual`, `device` (FK), `note`, `emulated`. `duration_calculated` and `duration_total` are `GeneratedField`s (cannot be written directly)
- **Device** — `name`, `type` (PC/Console/Handheld/Mobile/SBC/Unknown)
- **PlayEvent** — marks when a game was started/finished (separate from Sessions), `days_to_finish` is a `GeneratedField`
- **ExchangeRate** — cached FX rates per currency pair per year
- **GameStatusChange** — audit log of status transitions, ordered by `-timestamp`
- **FilterPreset** — saved filter configuration; `mode` (games/sessions/purchases/playevents), `find_filter`, `object_filter`, `ui_options` (all JSON). Follows Stash's SavedFilter pattern

**Unset platform/device is NULL**: `Game.platform`, `Purchase.platform`, and `Session.device` are nullable and stay NULL when unset — there are no sentinel rows (issue #290 removed the old "Unspecified" platform / "Unknown" device sentinels). "Unspecified" (platform) and "No device" are render-layer display labels only (e.g. `NameWithIcon`'s `PlatformBadge` fallback, `SessionDeviceSelector`, `search_label`, game detail, stats — the list is not exhaustive). All three FKs use `on_delete=SET_NULL`, exclude-mode set criteria match NULL rows (`_SetCriterion._not_in_q`), and a conditional `UniqueConstraint` keeps (name, year) unique among platformless games.

**GeneratedField constraint**: `duration_calculated`, `duration_total`, `price_per_game`, `days_to_finish` are computed by the database and cannot be written from application code.

### Key patterns

**Layout system** (`common/layout.py`): Views call `render_page(request, content, title=...)` instead of Django's `render()`. This assembles a full HTML document via `Page()` — analogous to FastHTML's `fast_app()`. `Page()` handles the `<head>`, navbar, toast container, FOUC-prevention script, and **JS includes**: it calls `collect_media(content)` to gather every component's declared `Media` and emits the `<script>` tags automatically — so views do **not** pass `scripts=` for component-owned JS. The `scripts=` argument remains only for page-specific glue not owned by a reusable component (e.g. the add-form helper `add_*.js`). The navbar shows today's/last-7-days playtime from the `model_counts` context processor.

**Component system** (`common/components/`): a FastHTML-style **lazy node tree**. Components are `Node` objects that render to HTML only when asked (`str(node)` / `Page()`), so `Page()` can walk a finished tree and collect each component's JS. Split into submodules re-exported via `common/components/__init__.py`:

- **`core.py`** — the node layer. `Node` (base; `__html__`/`__str__` return a `SafeString`), `Element` (the single class for *any* HTML element), `Safe` (wraps pre-rendered/trusted HTML), `Fragment` (ordered children, no wrapper tag — use instead of `str(a)+str(b)`), `BaseComponent` (base for higher-level components: implement `render()`, declare `media`), and `Media` (declarative JS deps with order-preserving dedup merge; `collect_media()` sums them over a tree, `node.with_media(...)` attaches them). `_render_element()` is `@lru_cache`-memoized (4096). Attribute values are always escaped. **Children: every string child is escaped — `SafeText`/`mark_safe` included; only `Node` children (so `Safe`) render unescaped.** Trusted pre-rendered HTML must be wrapped in `Safe(...)`, never passed as a safe string. `randomid()` generates stable hash-based IDs.
- **`primitives.py`** — Generic HTML. Plain leaf builders (`A`, `Button`, `Div`, `Span`, `P`, `Ul`, `Li`, `Strong`, `Label`, `Template`, `Td`, `Tr`, `Th`, `Table`, `Thead`, `Tbody`, `Caption`, `Nav`, `Form`, `H1`, `H2`, `H3`, `Option`, `Select`, …) are **generated from a whitelist** via the `_html_element(tag)` factory over `Element` — not hand-written per tag. Builders that add classes/behaviour are written out: `ControlButton()` (the one polymorphic button/link builder: `href=` renders `<a>`, `method="post"` renders a `<form>`+submit, default `<button>`; no size param — sizing is container-query driven), `ButtonGroup()` (segmented `ControlButton` members), `Input()`, `Checkbox()`, `Radio()`, `Pill()`, `Icon()`, `Popover()`, `PopoverTruncated()`, `SearchField()`, `PageHeading()` (the badge page heading; the plain `<h1>` is the generated `H1`), `Modal()`, `StyledTable()`, `TableRow()`, `TableTd()`, `TableHeader()`, `ContentContainer()` (the page-body width container: `w-full max-w-7xl self-center`; every list/detail/stats page body sits in one — navbar/popovers apply the max-width constant with their own layout, forms cap narrower via `AddForm`), `paginated_table_content()` (the StyledTable + pagination for a list page; its caller wraps it, with the filter tiers, in `ContentContainer`), `AddForm()`, `YearPicker()` (declares datepicker media), `CsrfInput()`/`ModuleScript()`/`StaticScript()` (script-tag string helpers used by `Page()`).
- **`domain.py`** — Domain-specific: `GameLink()`, `GameStatus()` (colored dot + label), `GameStatusSelector()` (Alpine.js PATCH dropdown), `SessionDeviceSelector()` (Alpine.js PATCH dropdown), `LinkedPurchase()`, `NameWithIcon()`, `PriceConverted()`, `PurchasePrice()`
- **`filters.py`** — Filter widget layer (no bars any more — #315 deleted the flat FilterBar family): the criterion-blob parse helpers (`_*_from_field`, `_choice_from_raw`, `parse_filter_dict`), the widget builders (`StringFilter`, `NumberFilter`, `_bool_control`, the `FilterSelect` adapters), `field_widget`/`field_widget_templates` (the single per-field dispatcher the quick bar + nested builder render through), the builder's comparison-row/chip/relation templates, and `FilterFieldPicker`
- **`quick_filter.py`** — `QuickFilterBar()` (#197, #315): THE one filter tier above every list view (wired by `ts/elements/quick-filter-bar.ts`), plus `QUICK_FACETS` and the `is_quick_editable` degrade predicate. Every facet renders as a ghost "Label ▾" `ComboboxDropdown` hosting the panel-layout widget — set → panel `FilterSelect`, date → `DateRangePanel` (static calendar), number/string/bool → the stacked widget embedded as-is. Row anatomy: collapsible facets, the "⋯" priority-plus overflow menu (ResizeObserver-driven, no breakpoints), then non-collapsible furniture — the Load-preset picker (`preset_api_url`, load-only) and the Apply | Clear [| Advanced filter…] ButtonGroup (`builder_url` gates the third segment). `apply_url` overrides every derived list URL (the #304 synthetic-harness constraint)
- **`search_select.py`** — `SearchSelect()` (form combobox) + `FilterSelect()` (include/exclude filter combobox with pinned Any/None modifiers; `layout="panel"` is the GitHub-label-picker personality for hosting inside a dropdown dialog, #315) + `ComboboxDropdown()` (the generic "Label ▾" trigger + combobox dialog; ghost or filled trigger) + `PresetSelect()`/`LoadPresetDropdown()` (the preset picker: an always-visible fetch-on-open personality hosted in a `<drop-down behavior="combobox">` dialog, #297) + `SearchSelectOption`, all built on a shared `_combobox_shell`; wired by `ts/elements/search-select.ts` (compiled to `dist/elements/search-select.js`)
- **`date_range_picker.py`** — `DateRangePicker()`/`DateRangeField()`/`DateRangeCalendar()` custom-element date-range widget (wired by `ts/elements/date-range-picker.ts`); used by filter bars

**Filter system** (`games/filters.py` + `common/criteria.py`): Stash-inspired structured filtering.

- `common/criteria.py` defines typed criterion classes: `StringCriterion`, `IntCriterion`, `FloatCriterion`, `DateCriterion`, `BoolCriterion`, `MultiCriterion`, `ChoiceCriterion`. Each has a `modifier` (`Modifier` enum: EQUALS, NOT_EQUALS, INCLUDES, EXCLUDES, GREATER_THAN, LESS_THAN, BETWEEN, IS_NULL, etc.) and a `to_q(field_name)` method.
- `OperatorFilter` base class provides AND/OR/NOT sub-filter composition and JSON serialization/deserialization.
- `games/filters.py` defines `GameFilter`, `SessionFilter`, `PurchaseFilter` (all `@dataclass` subclasses of `OperatorFilter`) and `FindFilter` (sort/pagination). Filters serialize to/from JSON and are passed in the `?filter=` query parameter.
- `parse_game_filter()`, `parse_session_filter()`, `parse_purchase_filter()` helpers deserialize from a JSON string.
- `FilterPreset` model stores named filter configurations that users can save and reload.
- **Quick filter bar** (#197/#315, `common/components/quick_filter.py` + `ts/elements/quick-filter-bar.ts`): THE single filter tier on every list view — a GitHub-style row of ghost "Label ▾" dropdown facets directly above the table (games: status/platform/name/year/playtime/mastered/session-and-purchase-count/total-price; sessions: game/device/started/ended/duration; purchases: type/ownership/name/price/infinite/purchased/refunded/created; playevents: game/started/ended/days-to-finish/note/created; devices: name/type/created; platforms: name/group/created). The flat FilterBar family is gone; anything the facets can't express lives in the nested builder, reached via the action group's "Advanced filter…" segment (every filterable mode has a builder page now, incl. devices/platforms — #336). Facets are own-model leaf fields of any `QUICK_FACET_KINDS` kind (set/number/date/string/bool — flat aggregate keys like `session_count` count as number), rendered via `field_widget(layout="panel")` with a `quick-` name prefix, inside a form whose Apply button (or Enter in an inline input) serializes them and navigates (Clear is a plain link to the bare list URL). Facets that don't fit the row are MOVED into the "⋯" overflow dropdown by a ResizeObserver priority-plus layout (continuous, no breakpoints; widget state survives — same DOM nodes); the preset picker and action group after the overflow host are non-collapsible furniture. The free-text search UI is gone (the `search` criterion remains server-side, carried inside the `?filter=` JSON — there is no `?search_string=` fallback). Editable only when every top-level filter key is a facet field with a dict criterion (`is_quick_editable` — the pinned predicate); operator keys, `*_filter` relations, `field_comparisons`, `search`, or any non-facet leaf degrade it to a read-only "Advanced filter active" pill with Edit-in-builder/Clear links. The bar's serializer emits only flat facet criteria, so its own output always round-trips back to editable.

**Views** (`games/views/`): Function-based views decorated with `@login_required`. Organized by domain entity:

- `session.py`, `game.py`, `purchase.py`, `playevent.py`, `platform.py`, `device.py`, `statuschange.py` — CRUD for each entity
- `general.py` — `stats()`, `stats_alltime()`, `index()`, `model_counts` context processor, `global_current_year` context processor, `use_custom_redirect` decorator (redirects to `request.session["return_path"]` if set)
- `stats_data.py` — `compute_stats(year)` returns a `StatsData` TypedDict; pure computation, no HTTP
- `stats_content.py` — renders stats page content from a `StatsData` dict
- `stats_links.py` — pure filter-link builders for stats rows/counts (issue #65); parity-tested so each builder's queryset count equals the stat it links from
- `auth.py` — custom `LoginView` subclassing Django's auth view, renders login page via `render_page()`

Filter presets have no classic views: they live on the Ninja API (`/api/presets`, see below); the preset picker UI is the shared combobox dropdown (#297).

**Signals** (`games/signals.py`):
- `pre_save` on Purchase: snapshots old price/currency for change detection
- `post_save` on Purchase: sets `needs_price_update` if price/currency changed
- `m2m_changed` on Purchase.games: updates `num_purchases` count
- `pre_delete` on Game: decrements `num_purchases` on related Purchases (deletes Purchase if count reaches 0)
- `post_save/post_delete` on Session: recalculates `Game.playtime` from session aggregate
- `pre_save` on Game: creates `GameStatusChange` audit records when `status` changes

**Background tasks**: django-q2 cluster runs `games.tasks.convert_prices()` on a schedule to fetch exchange rates from `cdn.jsdelivr.net/npm/@fawazahmed0/currency-api` and convert purchase prices to CZK.

**HTMX toast middleware** (`games/htmx_middleware.py`): Converts Django messages into `HX-Trigger` headers with `show-toast` event. Skips if `HX-Redirect` is present. Toast rendering is handled client-side by Alpine.js (`games/static/js/toast.js`).

**REST API** (`games/api.py`): Django Ninja with routers mounted at `/api/`:
- `GET /api/games/search` — search games for autocomplete
- `PATCH /api/games/{id}/status` — update game status
- `GET/POST /api/playevent/` — list/create play events
- `GET/PATCH/DELETE /api/playevent/{id}` — get/update/delete play event
- `PATCH /api/session/{id}/device` — update session device
- `GET /api/presets/` — the user's filter presets for a mode, shaped as combobox options (`limit=0` = unbounded)
- `POST /api/presets/` — upsert a preset on (user, mode, name); 201 create / 200 update
- `DELETE /api/presets/{id}` — delete an owned preset (404 for non-owner)

### Templates

Only a small number of HTML templates remain (platform icon snippets and partials). The bulk of the UI is built via Python components. Template files:

- `games/templates/icons/<slug>.html` — SVG icon snippets; **source** for the icon codegen (`manage.py gen_icons` → committed `common/components/icons_generated.py`), not loaded at runtime
- `games/templates/` — minimal partials for HTMX responses where needed

### Frontend stack

- **HTMX** (`games/static/js/htmx.min.js`) — partial page updates
- **Alpine.js** (vendored: `alpine.min.js`, `alpine-mask.min.js`) — reactive dropdowns (`GameStatusSelector`, `SessionDeviceSelector`), toast store
- **Flowbite** (vendored: `flowbite.min.js`; `datepicker.umd.js` for the stats YearPicker) — navbar collapse, dropdown toggles
- **Tailwind CSS** — utility classes, compiled from `common/input.css` → `games/static/base.css`
- All third-party JS is served locally from `games/static/js/` (no CDNs), so pages and browser tests work offline
- **Custom JS** authored in TypeScript under `ts/`, compiled to `games/static/js/dist/` (gitignored, build-only):
  - `ts/toast.ts` — Alpine.js toast store (listens for `show-toast` HTMX event); also defines `window.fetchWithHtmxTriggers`
  - `ts/elements/search-select.ts` — SearchSelect/FilterSelect widgets (search-as-you-type, pills, include/exclude filter mode)
  - `ts/utils.ts` — shared ES-module helpers (`onSwap`, `toISOUTCString`, …)
- **Widget initialization**: widget JS registers with `onSwap(selector, initializeElement)` from `ts/utils.ts` — a port of FastHTML's `proc_htmx` built on `htmx.onLoad`. It runs the initializer once per matching element, on initial page load and inside every htmx-swapped fragment. Never hand-roll `DOMContentLoaded`/`htmx:afterSwap` listeners with per-element guard flags.

### Interactive components: custom elements + TypeScript

New interactive components are **custom elements**, not inline JS in Python. A component that needs behavior emits a semantic tag via `custom_element("tag", Props(...))` (light DOM, server-rendered inner markup built with the htpy-style node builders). Behavior lives in `ts/elements/<tag>.ts` (TypeScript, vanilla DOM, `customElements.define`); the native `connectedCallback` replaces `onSwap` (it fires on parse *and* htmx swap). The server↔client contract is one Python `TypedDict` per element registered with `register_element(...)` in `common/components/custom_elements.py`; `manage.py gen_element_types` codegens `ts/generated/props.ts` (interface + attribute reader) so renaming a prop fails `tsc`.

- **Build:** `tsc` per-module (`tsconfig.json`) compiles `ts/` → `games/static/js/dist/` (build-only, gitignored). `make ts` = codegen + compile; `make ts-check` (in `make check`) = codegen + `tsc --noEmit -p tsconfig.check.json`; `make dev` runs `tsc --watch`. The Docker image builds CSS + TS in a Node stage. Run `make ts` after editing any `.ts` so e2e/local serving sees fresh output. **Two tsconfigs:** the emit `tsconfig.json` **excludes** `ts/**/*.test.ts` (test files never ship to `dist/`); `tsconfig.check.json` re-includes them and adds `@types/node` (scoped there, so the browser emit stays node-free) so `make ts-check` also type-checks the vitest tests.
- **htpy-style markup:** builders take kwargs attributes and `[]` children — `Div(class_="x", hx_get="/y")[child1, child2]` (`class_`→`class`, `hx_get`→`hx-get`, `True`→`name="name"` boolean form, `False`/`None`→omitted). A runtime-built attribute collection goes in the single positional slot: `Div(attrs_list, class_="x")`. Still a walkable `Element` tree, so `Media` bubbles. `attributes=`/`children=` kwargs are rejected (`TypeError`).
- **Do NOT** author HTML/JS as Python f-strings or add new inline Alpine `x-data` blobs. Alpine remains only for trivial pre-existing toggles (toast store, etc.).
- **Tables bubble cell media:** `StyledTable` returns a node tree (`Table`/`Thead`/`Tbody` builders), so a custom element in a table cell has its declared `Media` collected automatically when `Page()` walks the tree — its `<script>` is still emitted, with no manual `collect_media` step.

### Deployment

Docker-based: multi-stage Dockerfile (uv builder → Node assets stage → slim runtime), Caddy as reverse proxy on port 8000, Gunicorn with UvicornWorker (ASGI), Supervisor to manage Caddy + Gunicorn + django-q2. `make dev-prod` mimics production locally. CI/CD via GitHub Actions (`.github/workflows/build-docker.yml`): a `test` job runs `make check` (lint, format-check, mypy, ts-check, icon drift, the vitest suite, and the pytest suite incl. the cross-language filter-tree contract), then a `build-and-push` job builds + pushes the Docker image on `main`.

**Package manager (pnpm):** front-end deps use **pnpm**, not npm. The pnpm version is pinned in `package.json`'s `packageManager` field and provisioned via **Corepack** (bundled with Node) — the Docker assets stage runs `corepack enable` rather than `npm install -g pnpm`. To bump pnpm, update the `packageManager` field; local, CI, and Docker all follow it. pnpm disables dependency lifecycle scripts by default (opt in via `pnpm.onlyBuiltDependencies`), so the project is unaffected by npm v12's install-script changes.

### Database

SQLite with WAL journal mode. Connection timeout 20s. The `DATA_DIR` setting controls the database file location and is read consistently by both `settings.py` and `entrypoint.sh` (same env var + matching default). Migrations live in `games/migrations/`. There are `GeneratedField`s on the models — these are computed by the database engine and cannot be written from application code.

### Configuration

All configurable Django settings are read through `config()` in `timetracker/config.py`, never via bare `os.environ` in `settings.py`. Full reference: `docs/configuration.md`.

- **Resolution priority** (highest first): `NAME__FILE` (opt-in file secret) → `NAME` env var → `.env` → `settings.ini` (`[timetracker]` section) → in-code default. Missing + no default = `ImproperlyConfigured`.
- `config(name, *, default, cast, allow_file, required_in_prod)`: `cast` handles `bool`/`list`/`int`/`Path`/callable; `allow_file=True` honors `NAME__FILE` (contents `.strip()`-ed); `required_in_prod=True` hard-fails when missing and DEBUG is off.
- `DEBUG` defaults `True` (dev), turned off with `DEBUG=false`. `PROD` is a **deprecated alias** kept for one release.
- `SECRET_KEY` is required in production (insecure default only in DEBUG); supports `SECRET_KEY__FILE`.
- `APP_URL` accepts one full URL or a comma-separated list of full URLs; `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS` are derived from all listed URLs. `ALLOWED_HOSTS` can still be overridden directly (e.g. `ALLOWED_HOSTS=*` behind a reverse proxy); `CSRF_TRUSTED_ORIGINS` is always derived from `APP_URL`.
- `TIME_ZONE` reads `TZ` (defaults `Europe/Prague` in debug, `UTC` in prod).
- Django Admin, Debug Toolbar, and `django_extensions` are only available in `DEBUG` mode.
- **Container/entrypoint-only** flags (`PUID`, `PGID`, `CREATE_DEFAULT_SUPERUSER`, `STAGING`, `LOAD_SAMPLE_DATA`) live in `entrypoint.sh`, not the Python config — they are bootstrap concerns, not Django settings.
- django-q2 cluster: 1 worker, 60s timeout, 120s retry, ORM broker

### Testing

Tests live in `tests/`. Run with `make test` or `uv run --with pytest-django pytest`. Key test files:

- `test_components.py` — component rendering
- `test_filter_bars.py`, `test_filter_helpers.py`, `test_filters.py` — filter system
- `test_paths_return_200.py` — smoke test all list/view URLs
- `test_rendered_pages.py` — HTML output of pages
- `test_signals.py` — signal side-effects (playtime recalc, status change audit, etc.)
- `test_stats.py` — stats computation
- `test_streak.py`, `test_time.py`, `test_session_formatting.py` — utilities
- `test_middleware_integration.py`, `test_toast_middleware.py` — HTMX middleware
- `test_price_update.py` — currency conversion signals
- `test_search_select.py` — SearchSelect component

Pytest settings are in `pyproject.toml` under `[tool.pytest.ini_options]` (`DJANGO_SETTINGS_MODULE = "timetracker.settings"`).

**TypeScript unit tests** (vitest) live beside their modules as `ts/**/*.test.ts`, run with `make test-ts` (`vitest run`) — and automatically by `make test` (a prereq) and `make check`. vitest/Vite resolves the NodeNext-style `.js` import specifiers to the sibling `.ts`, so no compile step is needed; the test files are excluded from the emit build but type-checked by `make ts-check` (via `tsconfig.check.json`). The filter-tree serializer (`ts/elements/filter-tree/`, issue #188) is covered this way, plus a **cross-language contract** (`tests/test_filter_tree_contract.py`): the vitest suite writes `ts/elements/filter-tree/fixtures.canonical.json` (the serializer's actual output for the shared `fixtures.json` cases, gitignored) and the pytest test asserts each is `to_q()`-equivalent to the source filter — so the TS serializer cannot drift from the Python backend. The contract `skipif`-skips when the artifact is absent; `make check`/`make test` order `test-ts` first so it always runs there.

**Browser/E2E tests** live in `e2e/` and run with `make test-e2e` (`pytest-playwright` driving a real Chromium against pytest-django's `live_server`). `e2e/conftest.py` sets `DJANGO_ALLOW_ASYNC_UNSAFE` and prefers a system Chrome/Chromium; otherwise install browsers once via `uv run playwright install chromium`. All JS (including Alpine/Flowbite) is vendored in `games/static/js/`, so the tests run fully offline. Note that a bare `pytest` (`make test`) collects `e2e/` too, so it needs a browser as well. Key files: `test_widgets_e2e.py` (onSwap initialization lifecycle, FilterSelect/RangeSlider/add-purchase behavior), `test_search_select_e2e.py` (single-select edge cases on a synthetic page).

## Conventions for AI assistants

- **Never write to `GeneratedField`s** (`duration_calculated`, `duration_total`, `price_per_game`, `days_to_finish`). They are computed by the database.
- **Name variables with complete words** — readable, unabbreviated identifiers in both Python and JavaScript (e.g. `template` not `tpl`, `event` not `e`, `element` not `el`, `removeButton` not `removeBtn`, `option`/`value` not single letters in loops). This applies to new code and to code you touch.
- **Use `render_page()` not `render()`** for all full-page HTTP responses. Import from `common.layout`.
- **Build UI with Python components** from `common.components`, not raw HTML strings or Django templates. `SafeText` children pass through unescaped; plain strings are auto-escaped.
- **Components are nodes; use the named builders** — build with `Div()`, `Span()`, `Element("tag", ...)`, etc., which return `Node` objects. For a tag with no builder, add it to the whitelist in `primitives.py` (one line) or use `Element("tag", attrs, children)`. Use `Fragment(a, b, ...)` to group siblings (never `str(a)+str(b)`, which flattens the tree and drops media). Wrap trusted pre-rendered HTML in `Safe(html)` (the `mark_safe` analogue).
- **Builders take htpy form only** — write `Builder(class_="x", hx_get="/y")[child1, child2]`: static attributes as kwargs, children via `[]`. Dynamic attributes (a runtime list/dict) go through the single positional slot — `Builder(attrs_list, class_="x")` (a `list[(name, value)]` or a `Mapping`; see `AttrsArg`/`_coerce_attrs`). The generic and the six styled builders (`Input`, `Checkbox`, `Radio`, `Pill`, `ControlButton`, `SearchField`) **no longer accept `attributes=`/`children=` kwargs** — passing either raises `TypeError` (the `_attrs_from_kwargs` guard), so the verbose form is gone. Semantic params are keyword-only (`ControlButton(color="red")`, `Checkbox(name=…, checked=…)`, `Pill(label=…)`). Reach for the named builder a tag has (`Button`, `A`, `Div`, `Span`, `H1`/`H2`/`H3`, `Form`…) instead of raw `Element("button", ...)`; if a tag has no builder, add it to the whitelist in `primitives.py` (and export it from `common/components/__init__.py`). The low-level `Element(tag, attributes, children)` class keeps positional attributes/children — it is the node machinery and codegen target, not a call-site builder. Single-content-slot wrapping components support the htpy `[]` slot too: `Modal(id)[content]` and `DropdownActionItem(data_x="")[label]` are `BaseComponent` subclasses with a custom `__getitem__` that injects the children into the right inner element. Multi-slot or sibling-composing components (`Popover` has two content slots; `GameStatus`/`PageHeading` place content beside a generated dot/badge; `Icon` is a leaf `<svg>`) keep their own semantic `children=`/`attributes=` params — `[]` has no single natural target there. The badge page heading is `PageHeading`, not the generic `H1` builder. The node layer owns attribute merging (`normalize_attributes`): `class`/`style` accumulate, other attributes are first-wins, so a caller `class_` appends to a builder's baked class and duplicate-attribute HTML is impossible.
- **JS-bearing components declare `Media`, they don't rely on the view** — give a component `class Media: js = (...)` (a `BaseComponent`) or `return node.with_media(Media(js=...))`. `Page()` collects and emits it. Never re-add `scripts=ModuleScript(...)` threading in a view for a component that can declare its own dependency.
- **Filter views** accept `?filter=<JSON>` (structured); free-text search rides inside it as a `search` criterion on the `OperatorFilter` (there is no separate `?search_string=` param). New filter criteria go in `games/filters.py`; new criterion types go in `common/criteria.py`.
- **Read settings via `config()`** — new Django settings go through `config()` from `timetracker/config.py`, never bare `os.environ.get` in `settings.py`. Declare `cast`/`allow_file`/`required_in_prod` explicitly. Container-bootstrap flags belong in `entrypoint.sh`, not the Python config. See `docs/configuration.md`.
- **Signals handle side-effects** — do not manually recalculate `Game.playtime` or `Purchase.num_purchases`; the signals in `games/signals.py` do this on save/delete.
- **Buttons are `ControlButton`** — colors: `blue` (primary action), `red` (destructive), `gray` (secondary), `green` (positive); variants: `filled` (default), `segmented` (ButtonGroup members), plus the colorless single-look toggles that ignore `color` — `outline` (bordered dropdown toggle), `ghost` (transparent until hover; quick-facet dropdown triggers), `plain` (navbar nav-link). There is no size parameter and no `icon=` flag: buttons are compact by default and upsize inside an `@container` ancestor at least 28rem wide (form/modal/confirm containers declare `@container`); icon+text layout (`inline-flex items-center gap-2`) is baked in. Never wrap a button in `A(href=…)` — pass `href=` to `ControlButton` (renders a single styled `<a>`); `method="post"` renders a no-JS `<form>` submit.
- **Inline Alpine.js** is used for client-side reactivity in domain components (`GameStatusSelector`, `SessionDeviceSelector`). The pattern is `x-data="{...}"` with `fetchWithHtmxTriggers()` for PATCH API calls.
- **No styling-at-a-distance; elements carry their own classes**: `input.css` is document bootstrapping only (Tailwind import, theme, fonts, resets) — it contains **no form/component styling and no selectors that reach across the DOM** (`#id descendant`, `form input:disabled`, etc.) to style something a component owns. An element's appearance, **including state** (`disabled:`, `has-[:disabled]:`, `focus:`), comes from utility classes on that element, emitted by its component. This keeps state composable (no specificity wars) and robust to markup edits.
- **Forms render via `FormFields`/`AddForm`, never `form.as_div()`**: `FormFields(form, *, extras=...)` (in `primitives.py`) renders label + control + errors + row layout with their own classes; native controls get their classes from `PrimitiveWidgetsMixin` (`games/forms.py`, which stamps `INPUT/SELECT/TEXTAREA_CLASS` incl. `disabled:` variants by widget type, skipping SearchSelect + checkbox). Every form is on this path, including login (`LoginForm(PrimitiveWidgetsMixin, AuthenticationForm)`). `extras` appends a node into a named field's row (e.g. the session timestamp buttons).
- **Disabled form controls share one look**: every form element fades the same way when disabled, via the shared constants in `primitives.py` — `DISABLED_CONTROL_CLASS` (`disabled:opacity-50 disabled:cursor-not-allowed`, put on the control: native inputs via the mixin, `Checkbox`, etc.) and `DISABLED_WITHIN_CLASS` (the `has-[:disabled]:` wrapper variant, for composite controls like `SearchSelect` whose disabled state lives on an inner element). Reuse these constants; don't hand-roll a different disabled style per control.
- **Disabling composite widgets**: a composite widget (e.g. `SearchSelect`) carries its `id` on a wrapper `<div>`, which has no `disabled` state — setting `.disabled` on it is a no-op. Disable the inner control (for `SearchSelect`, the `[data-search-select-search]` input); the wrapper fades itself via `DISABLED_WITHIN_CLASS`, so callers toggle only the control's `disabled`, never styles.
- **Platform icons** are SVG snippets in `games/templates/icons/<slug>.html`, compiled to first-class `Element` node trees by `make gen-icons` (committed `common/components/icons_generated.py`; drift-guarded in `make check`). Add/edit a snippet, run `make gen-icons`, reference by slug in `Platform.icon`. `Icon(name, attributes=...)` returns a node: `class` merges onto the svg, `title` becomes a `<title>` child. Never edit `icons_generated.py` by hand.
- **Name compound types explicitly** — if a `tuple`, `dict`, or other compound value is passed between functions or appears in multiple signatures, give it a named type (`TypedDict`, `NamedTuple`, or a `type` alias) rather than repeating the structural annotation. This applies even to small types used in only a few places; the name carries intent that the structure cannot. Examples: `LabeledOption = tuple[str, str]` instead of repeating `tuple[str, str]` for (value, label) pairs; `RangeValues(min, max)` instead of `tuple[str, str]` for range bounds.
- **Name primitive roles too** — when a bare `str`/`int` stands for a domain concept (an id, a key, a token, a field name), give it a PEP 695 transparent alias (`type SortKey = str`) so signatures say *which* string/int goes where instead of a wall of `str`. These are zero-cost and need no wrapping (unlike `NewType`); reach for them especially when several distinct string roles meet in one function (e.g. a `dict[SortKey, SortSpec]` whose values reference an `AnnotationName`). Add a trailing comment on the alias noting an example value. Use `NewType` only when you actually want the checker to reject cross-assignment and are willing to wrap every literal.
