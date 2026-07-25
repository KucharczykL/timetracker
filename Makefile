all: css migrate

initialize: npm css migrate loadplatforms

PYTHON_VERSION = 3.14
# ts/date-time-presentation.ts uses Temporal, which lands in Node 26. On an older
# node it is simply `undefined`, the formatters return null, and vitest fails with
# ~11 "expected null to be '2026-07-02 19:05 …'" assertions that read like real
# breakage. shell.nix pins nodejs_26; this guard stops a stray older node on PATH
# from turning that into a mystery.
NODE_MAJOR_VERSION = 26
DEV_HOST ?= 127.0.0.1
DEV_PORT ?= 8000

# Ensure a usable CPython 3.14 exists for uv before any target that needs it.
# Fast no-op when one is already available (a Nix shell puts it on PATH; a
# provisioned .venv counts too). Otherwise try uv's own downloader, and only if
# THAT can't reach the interpreter — e.g. the Claude Code cloud sandbox blocks
# the python-build-standalone download on github — stop with a pointer to the
# bootstrap script instead of failing cryptically deep inside uv/pytest.
ifeq ($(OS),Windows_NT)
# On Windows the recipe shell is NOT fixed: make runs recipes through Git-Bash `sh`
# when it's on PATH (Bash/direnv/CI), else cmd.exe (e.g. make launched from
# PowerShell without Git's usr/bin on PATH). The two disagree on the null device —
# `sh` wants `/dev/null` (and treats `NUL` as a plain file, littering the tree),
# cmd.exe wants `NUL` (and treats `/dev/null` as a bad path) — so redirect to
# NEITHER: let `uv python find` print its one line. `||` and the `<`/`>`-quoting
# both behave the same in either shell. This branch also drops the POSIX-only
# `.venv/bin/python` fallback + cloud hint from the `else` recipe (irrelevant here).
ensure-python:
	@uv python find ">=3.14,<4" || uv python install $(PYTHON_VERSION)
else
ensure-python:
	@uv python find '>=3.14,<4' >/dev/null 2>&1 && exit 0; \
	test -x .venv/bin/python && exit 0; \
	uv python install $(PYTHON_VERSION) && exit 0; \
	echo "==> Python $(PYTHON_VERSION) is required but couldn't be provisioned here."; \
	echo "    (In the Claude Code cloud sandbox the interpreter download is blocked.)"; \
	echo "    Run  ./scripts/bootstrap-cloud-env.sh  then retry your make target."; \
	exit 1
endif

# Fail loudly, before any JS build or test, when PATH's node predates Temporal.
# Written to run under both `sh` and cmd.exe: node itself does the comparison and
# sets the exit status, so the recipe needs no shell-specific arithmetic.
ensure-node:
	@node -e "process.exit(+process.versions.node.split('.')[0] >= $(NODE_MAJOR_VERSION) ? 0 : 1)" || \
	( \
		echo "==> node $$(node --version 2>/dev/null) is too old — this repo needs node >= $(NODE_MAJOR_VERSION)."; \
		echo "    ts/date-time-presentation.ts uses Temporal (Node 26+). On an older node the"; \
		echo "    date/time formatters return null and vitest fails as if the code were broken."; \
		echo "    shell.nix pins nodejs_26: run from the Nix dev shell, e.g."; \
		echo "        nix-shell --run 'make $(MAKECMDGOALS)'"; \
		exit 1 \
	)

npm: ensure-node
	pnpm install

css: ensure-node common/input.css
	pnpm tailwindcss -i ./common/input.css -o  ./games/static/base.css

makemigrations:
	uv run --frozen python manage.py makemigrations

migrate: makemigrations
	uv run --frozen python manage.py migrate

devlogin: migrate
	uv run --frozen python manage.py devlogin

init: ensure-python
	uv sync --frozen
	pnpm install
	$(MAKE) migrate
	$(MAKE) loadplatforms
	$(MAKE) gen-icons

server: ensure-node gen-element-types
	@pnpm concurrently \
		--names "Django,TS" \
		--prefix-colors "blue,green" \
		"uv run --frozen python -Wa manage.py runserver $(DEV_HOST):$(DEV_PORT)" \
		"pnpm exec tsc --watch"

gen-element-types:
	uv run --frozen python manage.py gen_element_types

gen-icons:
	uv run --frozen python manage.py gen_icons

check-icons:
	uv run --frozen python manage.py gen_icons --check

ts: ensure-node gen-element-types
	pnpm exec tsc

ts-check: ensure-node gen-element-types
	pnpm exec tsc --noEmit -p tsconfig.check.json

# Vitest consumes generated modules, and the classic bootstrap tests inspect its
# emitted script, so a clean checkout needs the complete TypeScript build first.
test-ts: ts
	pnpm test:ts

dev: export DEV_LOGIN_PREFILL := admin:admin
dev: ensure-python ensure-node gen-element-types
	@pnpm concurrently \
		--names "Django,Tailwind,TS" \
		--prefix-colors "blue,green,magenta" \
		"uv run --frozen python -Wa manage.py runserver $(DEV_HOST):$(DEV_PORT)" \
		"pnpm tailwindcss -i ./common/input.css -o ./games/static/base.css --watch" \
		"pnpm exec tsc --watch"


caddy:
	caddy run --watch

dev-prod: migrate collectstatic
	@npx concurrently \
		--names "Caddy,Django,Django-Q" \
		"caddy run --config Caddyfile.dev" \
		"$(MAKE) gunicorn-prod" \
		"$(MAKE) qcluster-prod"

# These two run the production-like servers with PROD=1 scoped to them only (not
# to dev-prod's migrate/collectstatic prereqs). Each is a SINGLE target written in
# two lines: the `... : export PROD := 1` line attaches a target-specific env var,
# the following `... :` line is the rule + recipe. Make merges them — not a redefinition.
gunicorn-prod: export PROD := 1
gunicorn-prod:
	uv run --frozen python -m gunicorn --bind 0.0.0.0:8001 timetracker.asgi:application -k uvicorn.workers.UvicornWorker

qcluster-prod: export PROD := 1
qcluster-prod:
	uv run --frozen manage.py qcluster

dumpgames:
	uv run --frozen python manage.py dumpdata --format yaml games --output tracker_fixture.yaml

loadplatforms:
	uv run --frozen python manage.py loadplatforms

loadall:
	uv run --frozen python manage.py loaddata data.yaml

loadsample:
	uv run --frozen python manage.py loaddata sample.yaml.gz

anonymize-sample:
	uv run --frozen python manage.py anonymize_sample --seed 42 --force

createsuperuser:
	uv run --frozen python manage.py createsuperuser

shell:
	uv run --frozen python manage.py shell

collectstatic:
	uv run --frozen python manage.py collectstatic --clear --no-input

uv.lock: pyproject.toml
	uv sync

# Extra pytest arguments for `test` / `test-e2e`, so a focused run needs no raw
# tooling: make test ARGS="tests/test_filters.py -k relation -x"
ARGS ?=

# base.css (Tailwind) and js/dist (TS) are build artifacts, gitignored and not
# tracked — build both before tests so e2e/static serving has fresh assets.
test: ensure-python uv.lock css ts test-ts
	uv run --frozen --with pytest-django pytest $(ARGS)

test-e2e: uv.lock css ts
	uv run --frozen pytest e2e/ $(ARGS)

lint:
	uv run --frozen ruff check

lint-fix:
	uv run --frozen ruff check --fix

format:
	uv run --frozen ruff format

format-check:
	uv run --frozen ruff format --check

typecheck:
	uv run --frozen mypy .

check: ensure-python lint format-check typecheck ts-check check-icons test-ts test

date:
	uv run --frozen python scripts/print_local_time.py

ifeq ($(OS),Windows_NT)
cleanstatic:
	if exist static rmdir /s /q static
else
cleanstatic:
	rm -r static/*
endif

clean: cleanstatic
