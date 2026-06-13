# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

| Task | Command |
|------|---------|
| Install dependencies | `make init` (installs Python via uv + npm packages, loads platform fixtures) |
| Development server | `make dev` (runs Django runserver + Tailwind CSS watcher) |
| Production-like dev | `make dev-prod` (Caddy + Gunicorn/Uvicorn + Django-Q cluster) |
| Run tests | `make test` (or `uv run --with pytest-django pytest`) |
| Make migrations | `make makemigrations` |
| Apply migrations | `make migrate` |
| CSS (Tailwind) | `make css` |
| Django shell | `make shell` |
| Create superuser | `make createsuperuser` |
| Format Python | `make format` (or `uv run ruff format`) |
| Lint Python | `make lint` (or `uv run ruff check`) |
| Auto-fix lint | `make lint-fix` (`ruff check --fix`) |
| Lint + format check + tests | `make check` (CI-style aggregate) |
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
- **Purchase** — ownership type, prices, currency conversion (`converted_price`, `price_per_game` is a `GeneratedField`), links to Game via M2M. `num_purchases` counts linked games. DLC/SeasonPass/BattlePass must have a `related_purchase`
- **Session** — `timestamp_start`/`timestamp_end`, `duration_manual`, `device` (FK), `note`, `emulated`. `duration_calculated` and `duration_total` are `GeneratedField`s (cannot be written directly)
- **Device** — `name`, `type` (PC/Console/Handheld/Mobile/SBC/Unknown)
- **PlayEvent** — marks when a game was started/finished (separate from Sessions), `days_to_finish` is a `GeneratedField`
- **ExchangeRate** — cached FX rates per currency pair per year
- **GameStatusChange** — audit log of status transitions, ordered by `-timestamp`
- **FilterPreset** — saved filter configuration; `mode` (games/sessions/purchases/playevents), `find_filter`, `object_filter`, `ui_options` (all JSON). Follows Stash's SavedFilter pattern

**Sentinel objects**: `get_sentinel_platform()` returns an "Unspecified" platform used when a Game has no platform. A similar sentinel Device ("Unknown") is created when a Session has no device.

**GeneratedField constraint**: `duration_calculated`, `duration_total`, `price_per_game`, `days_to_finish` are computed by the database and cannot be written from application code.

### Key patterns

**Layout system** (`common/layout.py`): Views call `render_page(request, content, title=...)` instead of Django's `render()`. This assembles a full HTML document via `Page()` — analogous to FastHTML's `fast_app()`. `Page()` handles the `<head>`, navbar, toast container, FOUC-prevention script, and **JS includes**: it calls `collect_media(content)` to gather every component's declared `Media` and emits the `<script>` tags automatically — so views do **not** pass `scripts=` for component-owned JS. The `scripts=` argument remains only for page-specific glue not owned by a reusable component (e.g. the add-form helper `add_*.js`). The navbar shows today's/last-7-days playtime from the `model_counts` context processor.

**Component system** (`common/components/`): a FastHTML-style **lazy node tree**. Components are `Node` objects that render to HTML only when asked (`str(node)` / `Page()`), so `Page()` can walk a finished tree and collect each component's JS. Split into submodules re-exported via `common/components/__init__.py`:

- **`core.py`** — the node layer. `Node` (base; `__html__`/`__str__` return a `SafeString`), `Element` (the single class for *any* HTML element), `Safe` (wraps pre-rendered/trusted HTML), `Fragment` (ordered children, no wrapper tag — use instead of `str(a)+str(b)`), `BaseComponent` (base for higher-level components: implement `render()`, declare `media`), and `Media` (declarative JS deps with order-preserving dedup merge; `collect_media()` sums them over a tree, `node.with_media(...)` attaches them). `_render_element()` is `@lru_cache`-memoized (4096). Attribute values are always escaped. **Children: every string child is escaped — `SafeText`/`mark_safe` included; only `Node` children (so `Safe`) render unescaped.** Trusted pre-rendered HTML must be wrapped in `Safe(...)`, never passed as a safe string. `randomid()` generates stable hash-based IDs.
- **`primitives.py`** — Generic HTML. Plain leaf builders (`Div`, `Span`, `P`, `Ul`, `Li`, `Strong`, `Label`, `Template`, `Td`, `Tr`, `Th`) are **generated from a whitelist** via the `_html_element(tag)` factory over `Element` — not hand-written per tag. Builders that add classes/behaviour are written out: `A()`, `Button()`, `ButtonGroup()`, `Input()`, `Checkbox()`, `Radio()`, `Pill()`, `Icon()`, `Popover()`, `PopoverTruncated()`, `SearchField()`, `H1()`, `Modal()`, `SimpleTable()`, `TableRow()`, `TableTd()`, `TableHeader()`, `paginated_table_content()`, `AddForm()`, `YearPicker()` (declares datepicker media), `CsrfInput()`/`ModuleScript()`/`StaticScript()` (script-tag string helpers used by `Page()`).
- **`domain.py`** — Domain-specific: `GameLink()`, `GameStatus()` (colored dot + label), `GameStatusSelector()` (Alpine.js PATCH dropdown), `SessionDeviceSelector()` (Alpine.js PATCH dropdown), `LinkedPurchase()`, `NameWithIcon()`, `PriceConverted()`, `PurchasePrice()`
- **`filters.py`** — Filter UI: `FilterBar()`, `SessionFilterBar()`, `PurchaseFilterBar()` (built from `FilterSelect` widgets)
- **`search_select.py`** — `SearchSelect()` (form combobox) + `FilterSelect()` (include/exclude filter combobox with pinned Any/None modifiers) + `SearchSelectOption`, all built on a shared `_combobox_shell`; wired by `games/static/js/search_select.js`

**Filter system** (`games/filters.py` + `common/criteria.py`): Stash-inspired structured filtering.

- `common/criteria.py` defines typed criterion classes: `StringCriterion`, `IntCriterion`, `FloatCriterion`, `DateCriterion`, `BoolCriterion`, `MultiCriterion`, `ChoiceCriterion`. Each has a `modifier` (`Modifier` enum: EQUALS, NOT_EQUALS, INCLUDES, EXCLUDES, GREATER_THAN, LESS_THAN, BETWEEN, IS_NULL, etc.) and a `to_q(field_name)` method.
- `OperatorFilter` base class provides AND/OR/NOT sub-filter composition and JSON serialization/deserialization.
- `games/filters.py` defines `GameFilter`, `SessionFilter`, `PurchaseFilter` (all `@dataclass` subclasses of `OperatorFilter`) and `FindFilter` (sort/pagination). Filters serialize to/from JSON and are passed in the `?filter=` query parameter.
- `parse_game_filter()`, `parse_session_filter()`, `parse_purchase_filter()` helpers deserialize from a JSON string.
- `FilterPreset` model stores named filter configurations that users can save and reload.

**Views** (`games/views/`): Function-based views decorated with `@login_required`. Organized by domain entity:

- `session.py`, `game.py`, `purchase.py`, `playevent.py`, `platform.py`, `device.py`, `statuschange.py` — CRUD for each entity
- `general.py` — `stats()`, `stats_alltime()`, `index()`, `model_counts` context processor, `global_current_year` context processor, `use_custom_redirect` decorator (redirects to `request.session["return_path"]` if set)
- `stats_data.py` — `compute_stats(year)` returns a `StatsData` TypedDict; pure computation, no HTTP
- `stats_content.py` — renders stats page content from a `StatsData` dict
- `filter_presets.py` — `list_presets`, `save_preset`, `delete_preset`, `load_preset`
- `auth.py` — custom `LoginView` subclassing Django's auth view, renders login page via `render_page()`

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

### Templates

Only a small number of HTML templates remain (platform icon snippets and partials). The bulk of the UI is built via Python components. Template files:

- `games/templates/icons/<slug>.html` — SVG icon snippets (loaded by `common/icons.py` via `get_icon()`)
- `games/templates/` — minimal partials for HTMX responses where needed

### Frontend stack

- **HTMX** (`games/static/js/htmx.min.js`) — partial page updates
- **Alpine.js** (vendored: `alpine.min.js`, `alpine-mask.min.js`) — reactive dropdowns (`GameStatusSelector`, `SessionDeviceSelector`), toast store
- **Flowbite** (vendored: `flowbite.min.js`; `datepicker.umd.js` for the stats YearPicker) — navbar collapse, dropdown toggles
- **Tailwind CSS** — utility classes, compiled from `common/input.css` → `games/static/base.css`
- All third-party JS is served locally from `games/static/js/` (no CDNs), so pages and browser tests work offline
- **Custom JS** in `games/static/js/`:
  - `toast.js` — Alpine.js toast store (listens for `show-toast` HTMX event); also defines `window.fetchWithHtmxTriggers`
  - `search_select.js` — SearchSelect/FilterSelect widgets (search-as-you-type, pills, include/exclude filter mode)
  - `utils.js` — shared ES-module helpers (`onSwap`, `toISOUTCString`, …)
- **Widget initialization**: widget JS registers with `onSwap(selector, initializeElement)` from `utils.js` — a port of FastHTML's `proc_htmx` built on `htmx.onLoad`. It runs the initializer once per matching element, on initial page load and inside every htmx-swapped fragment. Never hand-roll `DOMContentLoaded`/`htmx:afterSwap` listeners with per-element guard flags.

### Deployment

Docker-based: multi-stage Dockerfile (uv builder → slim runtime), Caddy as reverse proxy on port 8000, Gunicorn with UvicornWorker (ASGI), Supervisor to manage Caddy + Gunicorn + django-q2. `make dev-prod` mimics production locally. CI/CD via GitHub Actions (`.github/workflows/build-docker.yml`): builds Docker image; Drone CI (`.drone.yml`) also present for deployments via Portainer webhook.

### Database

SQLite with WAL journal mode. Connection timeout 20s. The `DATA_DIR` env var controls the database file location. Migrations live in `games/migrations/`. There are `GeneratedField`s on the models — these are computed by the database engine and cannot be written from application code.

### Configuration

- `DEBUG` is `True` unless `PROD` env var is set
- `TIME_ZONE` defaults to `Europe/Prague` in debug, otherwise reads `TZ` env var (default `UTC`)
- Django Admin, Debug Toolbar, and `django_extensions` are only available in `DEBUG` mode
- `CSRF_TRUSTED_ORIGINS` is parsed from a comma-separated env var
- `DATA_DIR` env var sets the SQLite database location (defaults to `BASE_DIR`)
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

**Browser/E2E tests** live in `e2e/` and run with `make test-e2e` (`pytest-playwright` driving a real Chromium against pytest-django's `live_server`). `e2e/conftest.py` sets `DJANGO_ALLOW_ASYNC_UNSAFE` and prefers a system Chrome/Chromium; otherwise install browsers once via `uv run playwright install chromium`. All JS (including Alpine/Flowbite) is vendored in `games/static/js/`, so the tests run fully offline. Note that a bare `pytest` (`make test`) collects `e2e/` too, so it needs a browser as well. Key files: `test_widgets_e2e.py` (onSwap initialization lifecycle, FilterSelect/RangeSlider/add-purchase behavior), `test_search_select_e2e.py` (single-select edge cases on a synthetic page).

## Conventions for AI assistants

- **Never write to `GeneratedField`s** (`duration_calculated`, `duration_total`, `price_per_game`, `days_to_finish`). They are computed by the database.
- **Name variables with complete words** — readable, unabbreviated identifiers in both Python and JavaScript (e.g. `template` not `tpl`, `event` not `e`, `element` not `el`, `removeButton` not `removeBtn`, `option`/`value` not single letters in loops). This applies to new code and to code you touch.
- **Use `render_page()` not `render()`** for all full-page HTTP responses. Import from `common.layout`.
- **Build UI with Python components** from `common.components`, not raw HTML strings or Django templates. `SafeText` children pass through unescaped; plain strings are auto-escaped.
- **Components are nodes; use the named builders** — build with `Div()`, `Span()`, `Element("tag", ...)`, etc., which return `Node` objects. For a tag with no builder, add it to the whitelist in `primitives.py` (one line) or use `Element("tag", attrs, children)`. Use `Fragment(a, b, ...)` to group siblings (never `str(a)+str(b)`, which flattens the tree and drops media). Wrap trusted pre-rendered HTML in `Safe(html)` (the `mark_safe` analogue).
- **JS-bearing components declare `Media`, they don't rely on the view** — give a component `class Media: js = (...)` (a `BaseComponent`) or `return node.with_media(Media(js=...))`. `Page()` collects and emits it. Never re-add `scripts=ModuleScript(...)` threading in a view for a component that can declare its own dependency.
- **Filter views** accept `?filter=<JSON>` (structured) and fall back to `?search_string=` (free-text). New filter criteria go in `games/filters.py`; new criterion types go in `common/criteria.py`.
- **Signals handle side-effects** — do not manually recalculate `Game.playtime` or `Purchase.num_purchases`; the signals in `games/signals.py` do this on save/delete.
- **Button colors**: `blue` (primary action), `red` (destructive), `gray` (secondary), `green` (positive). Icon buttons use `icon=True`.
- **Inline Alpine.js** is used for client-side reactivity in domain components (`GameStatusSelector`, `SessionDeviceSelector`). The pattern is `x-data="{...}"` with `fetchWithHtmxTriggers()` for PATCH API calls.
- **Platform icons** are SVG snippets in `games/templates/icons/<slug>.html`. Add new ones there and reference them by slug in `Platform.icon`.
- **Name compound types explicitly** — if a `tuple`, `dict`, or other compound value is passed between functions or appears in multiple signatures, give it a named type (`TypedDict`, `NamedTuple`, or a `type` alias) rather than repeating the structural annotation. This applies even to small types used in only a few places; the name carries intent that the structure cannot. Examples: `LabeledOption = tuple[str, str]` instead of repeating `tuple[str, str]` for (value, label) pairs; `RangeValues(min, max)` instead of `tuple[str, str]` for range bounds.
