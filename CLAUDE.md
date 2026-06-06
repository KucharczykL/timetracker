# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

| Task | Command |
|------|---------|
| Install dependencies | `make init` (installs Python via uv + npm packages) |
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

## Architecture

A Django 6+ monolith with a single app (`games/`) for tracking video game purchases, play sessions, and statistics. Uses HTMX for interactivity with a custom server-side component system, plus a Django Ninja REST API.

### Directory layout

```
games/          — Django app: models, views, templates, forms, signals, tasks, API
common/         — Shared utilities: time formatting, component system, HTML helpers
timetracker/    — Django project: settings, URL root, ASGI/WSGI
tests/          — Pytest tests
contrib/        — One-off scripts (exchange rate import)
```

### Models (in `games/models.py`)

- **Game** — name, platform, status (Unplayed/Played/Finished/Retired/Abandoned), mastered, playtime
- **Platform** — name, group, icon slug
- **Purchase** — ownership type, prices, currency conversion (`converted_price`, `price_per_game` is a GeneratedField), links to Game via M2M
- **Session** — start/end timestamps, manual duration, device. `duration_calculated` and `duration_total` are GeneratedFields (cannot be written directly)
- **Device** — name, type (PC/Console/Handheld/Mobile/SBC/Unknown)
- **PlayEvent** — marks when a game was started/finished (separate from Sessions), `days_to_finish` is a GeneratedField
- **ExchangeRate** — cached FX rates per currency pair per year
- **GameStatusChange** — audit log of status transitions

### Key patterns

**Component system** (`common/components.py`): Python functions return HTML via django-cotton templates. Every component wraps `Component()` which calls `render_to_string` (LRU-cached in production). Key helpers: `A()`, `Button()`, `Icon()`, `Popover()`, `PopoverTruncated()`, `NameWithIcon()`, `LinkedPurchase()`, `Div()`, `Form()`.

**Views** (`games/views/`): Function-based views decorated with `@login_required`. Organized by domain entity: `session.py`, `game.py`, `purchase.py`, `playevent.py`, `platform.py`, `device.py`, `statuschange.py`, `general.py`. The `general.py` has two context processors: `model_counts` and `global_current_year`.

**Signals** (`games/signals.py`):
- `pre_save` on Purchase: snapshots old price/currency for change detection
- `post_save` on Purchase: sets `needs_price_update` if price/currency changed
- `m2m_changed` on Purchase.games: updates `num_purchases` count
- `pre_delete` on Game: decrements `num_purchases` on related Purchases
- `post_save/post_delete` on Session: recalculates Game.playtime
- `pre_save` on Game: creates GameStatusChange audit records

**Background tasks**: django-q2 cluster runs `games.tasks.convert_prices()` on a schedule to fetch exchange rates and convert purchase prices to CZK.

**HTMX toast middleware** (`games/htmx_middleware.py`): Converts Django messages into `HX-Trigger` headers with `show-toast` event. Skips if `HX-Redirect` is present.

**REST API** (`games/api.py`): Django Ninja with routers for playevents, games, and sessions. Game status and session device can be PATCHed via the API.

### Templates

Templates live in `games/templates/`. The layout uses django-cotton components in `templates/cotton/` — a reusable component library with `button.html`, `table.html`, `popover.html`, etc. Platform icons are stored as individual HTML snippet files under `cotton/icon/<slug>.html`. Partials for HTMX responses are in `templates/partials/`.

### Deployment

Docker-based: multi-stage Dockerfile (uv builder → slim runtime), Caddy as reverse proxy on port 8000, Gunicorn with UvicornWorker (ASGI), Supervisor to manage Caddy + Gunicorn + django-q2. `make dev-prod` mimics production locally. CI/CD via Drone (`.drone.yml`): runs tests, builds Docker image, deploys via Portainer webhook.

### Database

SQLite with WAL journal mode. Connection timeout 20s. The `DATA_DIR` env var controls the database file location. Migrations live in `games/migrations/`. There are GeneratedFields on the models — these are computed by the database engine and cannot be written from application code.

### Configuration

- `DEBUG` is `True` unless `PROD` env var is set
- `TIME_ZONE` defaults to `Europe/Prague` in debug, otherwise reads `TZ` env var
- Django Admin and Debug Toolbar are only available in DEBUG mode
- `CSRF_TRUSTED_ORIGINS` is parsed from a comma-separated env var
