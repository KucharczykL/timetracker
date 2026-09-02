POSTGRES_MK = .cache/postgres.mk

ifneq ($(filter stop-postgres,$(MAKECMDGOALS)),)
ifneq ($(MAKECMDGOALS),stop-postgres)
$(error stop-postgres must be invoked alone)
endif
else
include $(POSTGRES_MK)

$(POSTGRES_MK): scripts/ensure_postgres.py FORCE
	uv run --frozen python scripts/ensure_postgres.py --makefile $@

.PHONY: FORCE ensure-postgres
FORCE:
ensure-postgres: $(POSTGRES_MK)
endif

.PHONY: stop-postgres
stop-postgres:
	uv run --frozen python scripts/ensure_postgres.py --stop


all: ensure-postgres css migrate

PYTHON_VERSION = 3.14
DEV_HOST ?= 127.0.0.1
DEV_PORT ?= 8000

# The JS toolchain needs Node >= 26: ts/date-time-presentation.ts uses Temporal,
# which lands in 26. On an older node Temporal is `undefined`, the date/time
# formatters return null, and ~11 vitest assertions fail with
# "expected null to be '2026-07-02 19:05 …'" — breakage that looks like the code's
# fault rather than the runtime's.
#
# uv already makes Python version-proof; this does the same for Node. Where PATH
# already supplies 26 — the Nix shell's nodejs_26, CI's setup-node, the node:26
# Docker stage — it is used as-is and this costs nothing. Where it doesn't, pnpm
# is told the exact version and fetches it (env form of the `use-node-version`
# setting), so every JS command below runs on 26 and `make check` works on a box
# with an older system node and no Nix shell. Every node invocation in this file
# goes through pnpm, which is what makes one switch enough.
NODE_VERSION = 26.4.0
NODE_MAJOR_VERSION = 26
# Do not redirect this probe on Windows: GNU make can use either cmd.exe or
# Git-Bash there, and their null-device paths are incompatible.
ifeq ($(OS),Windows_NT)
PATH_NODE_SUPPORTED := $(shell node -e "process.exit(+process.versions.node.split('.')[0] >= $(NODE_MAJOR_VERSION) ? 0 : 1)" && echo yes || echo no)
else
PATH_NODE_SUPPORTED := $(shell node -e "process.exit(+process.versions.node.split('.')[0] >= $(NODE_MAJOR_VERSION) ? 0 : 1)" 2>/dev/null && echo yes || echo no)
endif
ifneq ($(PATH_NODE_SUPPORTED),yes)
export npm_config_use_node_version = $(NODE_VERSION)
endif

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

# Two gates, deliberately separate. `ensure-node-runtime` answers "is there a
# usable interpreter", `ensure-node-deps` answers "is this project installed
# into it". Consumer targets want both, but `npm` — the target whose whole job
# is to CREATE the install — must depend on the runtime alone: gate it on the
# dependency check and it refuses to run in the one state it exists to repair,
# advising you to run the target that just refused. Every other node-using
# target depends on `ensure-node-deps`, which pulls the runtime gate in behind
# it, so the ordering holds without each call site restating it.
#
# Both verify what the JS commands will ACTUALLY run on — `pnpm exec`, so it
# accounts for the version pnpm was told to fetch above, not just PATH. Make
# runs a given prerequisite once per invocation, so this costs one pnpm call
# each per `make`. On the first run without a suitable PATH node the download
# happens in the runtime gate, so it also fails there (with a reason) rather
# than deep inside vitest. node itself does the comparison and sets the exit
# status, keeping the recipes free of shell-specific arithmetic for the Windows
# cmd.exe case.
ifeq ($(OS),Windows_NT)
ensure-node-runtime:
	@pnpm exec node -e "process.exit(+process.versions.node.split('.')[0] >= $(NODE_MAJOR_VERSION) ? 0 : 1)" || powershell -NoProfile -Command "Write-Host '==> Could not get Node >= $(NODE_MAJOR_VERSION) for the JS toolchain. pnpm could not supply $(NODE_VERSION); the first fetch needs network access.'; exit 1"
else
ensure-node-runtime:
	@pnpm exec node -e "process.exit(+process.versions.node.split('.')[0] >= $(NODE_MAJOR_VERSION) ? 0 : 1)" || \
	( \
		echo "==> Could not get Node >= $(NODE_MAJOR_VERSION) for the JS toolchain."; \
		echo "    PATH has $$(node --version 2>/dev/null || echo 'no node'), and pnpm could not"; \
		echo "    supply $(NODE_VERSION) either — the first fetch needs network access."; \
		echo "    ts/date-time-presentation.ts uses Temporal (Node 26+); without it the"; \
		echo "    date/time formatters return null and vitest fails as if the code were broken."; \
		echo "    Offline? Run from the Nix dev shell instead: nix-shell --run 'make $(MAKECMDGOALS)'"; \
		exit 1 \
	)
endif

# No OS split and no `||` message: the script prints its own diagnosis, so the
# text lives next to the comparison that produced it instead of being echoed
# twice in two shell dialects around a bare exit status.
ensure-node-deps: ensure-node-runtime
	@pnpm exec node scripts/check-typescript-pin.mjs

# The rebuild is not redundant. @vvago/vale declares a `bin` that its own
# postinstall creates, so pnpm tries to link a file that does not exist yet,
# warns, and leaves no `vale` on PATH — even with the package allowlisted in
# `pnpm.onlyBuiltDependencies`. Running the script afterwards fixes the order.
# Named explicitly rather than a bare `pnpm rebuild`, so this stays the one
# dependency permitted to run code at install time.
npm: ensure-node-runtime
	pnpm install
	pnpm rebuild @vvago/vale

css: ensure-node-deps common/input.css
	pnpm tailwindcss -i ./common/input.css -o  ./games/static/base.css

# --noinput, because the autodetector's questions can only end badly here. It
# asks one whenever a change is ambiguous — adding a unique field with a
# callable default (every `UUIDv7Field`), or tightening a nullable field to NOT
# NULL without a default. What happens next is decided by whatever stdin the
# caller happened to have: a terminal prompts, /dev/null raises `EOFError`, and
# a live pipe or socket (an agent runner, a CI step, an editor task) blocks
# forever with the question buried in a redirected log. --noinput makes all
# three deterministic — the unique-callable case proceeds, which is the answer
# a manual backfill migration wants anyway, and a genuinely un-migratable
# change exits non-zero with the reason instead of waiting on an answer that
# is never coming.
#
# Usage: make makemigrations ARGS="games --name edition_name"
# Without a name, the autodetector titles the file after the first operation
# and appends `_and_more`, which says nothing about the change.
makemigrations: ensure-postgres
	uv run --frozen python manage.py makemigrations --noinput $(ARGS)

# Drift guard for the aggregates. Bare `makemigrations` is not a substitute: on
# drift it writes a new migration and exits 0, so an un-regenerated model change
# reaches CI as a passing run.
check-migrations: ensure-postgres
	uv run --frozen python manage.py makemigrations --check --dry-run --noinput

# Read back the DDL a migration actually emits, for the cases the migration file
# does not show plainly: raw-SQL operations, and fields whose column definition
# is decided by the field class rather than the call site.
# Usage: make sqlmigrate ARGS="games 0023_library_event_schema"
sqlmigrate: ensure-postgres
	uv run --frozen python manage.py sqlmigrate $(ARGS)

# Generating first is deliberate: an un-generated model change would otherwise
# apply nothing and read as a clean run. It calls the command rather than the
# `makemigrations` target, because that target reads ARGS too and this one's
# ARGS names a migration — the autodetector would take it for an app label.
#
# Usage: make migrate ARGS="games 0024_libraryidempotencyrecord"
migrate: ensure-postgres
	uv run --frozen python manage.py makemigrations --noinput
	uv run --frozen python manage.py migrate $(ARGS)

# Drop the development database and build it again from the migrations.
#
# A migration that no deployment has run may still be edited in place, and the
# event-era ones qualify. A database that already applied the old file keeps the
# old column names while the migration state claims the new ones, and nothing
# reports it: `check-migrations` compares the models against the migration
# files, never against the schema. This target is the repair. The data is
# disposable -- `loadplatforms` and `loadsample` put it back.
reset-db: ensure-postgres
	uv run --frozen python manage.py reset_db --noinput
	$(MAKE) migrate

devlogin: migrate
	uv run --frozen python manage.py devlogin

init: ensure-python ensure-postgres
	uv sync --frozen
	$(MAKE) npm
	$(MAKE) css
	$(MAKE) migrate
	$(MAKE) loadplatforms
	$(MAKE) gen-icons

server: ensure-postgres ensure-node-deps gen-element-types
	@pnpm concurrently \
		--names "Django,TS" \
		--prefix-colors "blue,green" \
		"uv run --frozen python -Wa manage.py runserver $(DEV_HOST):$(DEV_PORT)" \
		"pnpm exec tsc --watch"

gen-element-types: ensure-postgres
	uv run --frozen python manage.py gen_element_types

gen-icons: ensure-postgres
	uv run --frozen python manage.py gen_icons

check-icons: ensure-postgres
	uv run --frozen python manage.py gen_icons --check

# Prose, in docs and in comments. The words this codebase refuses live in
# .vale/styles; docs/vocabulary.md says why each one is refused. Through pnpm
# like every other node target, so a box without Nix gets the same binary.
vale: ensure-node-deps
	pnpm exec node scripts/run-vale.mjs

ts: ensure-node-deps gen-element-types
	pnpm exec tsc

ts-check: ensure-node-deps gen-element-types
	pnpm exec tsc --noEmit -p tsconfig.check.json

# Vitest consumes generated modules, and the classic bootstrap tests inspect its
# emitted script, so a clean checkout needs the complete TypeScript build first.
test-ts: ts
	pnpm test:ts

dev: export DEV_LOGIN_PREFILL := admin:admin
dev: ensure-postgres ensure-python ensure-node-deps gen-element-types
	@pnpm concurrently \
		--names "Django,Tailwind,TS" \
		--prefix-colors "blue,green,magenta" \
		"uv run --frozen python -Wa manage.py runserver $(DEV_HOST):$(DEV_PORT)" \
		"pnpm tailwindcss -i ./common/input.css -o ./games/static/base.css --watch" \
		"pnpm exec tsc --watch"

# `make dev` reachable from another device on the LAN (phone testing of touch
# targets, responsive layout). Binds every interface instead of loopback, and
# points APP_URL at the LAN address — that one variable feeds BOTH ALLOWED_HOSTS
# and CSRF_TRUSTED_ORIGINS, so without it Django refuses the request and form
# POSTs fail CSRF. The address is auto-detected from the default route, so this
# needs no per-machine config; override with `make dev-lan LAN_HOST=<ip>`.
#
# NB: this serves a DEBUG=True server (tracebacks, settings, the admin/admin
# dev login) to everything that can reach the port — including any VPN subnet
# the host is on, not just the LAN. Run it while you need it, not permanently.
ifeq ($(OS),Windows_NT)
LAN_HOST ?= $(shell powershell -NoProfile -Command "Find-NetRoute -RemoteIPAddress 1.1.1.1 | Where-Object { $$_.IPAddress } | Select-Object -First 1 -ExpandProperty IPAddress")
LAN_HOST_CHECK = powershell -NoProfile -Command "if (-not '$(LAN_HOST)') { Write-Host '==> Could not detect a LAN address; pass LAN_HOST=<ip>.'; exit 1 }"
else
LAN_HOST ?= $(shell ip -4 -o route get 1.1.1.1 2>/dev/null | grep -oP 'src \K[\d.]+')
LAN_HOST_CHECK = test -n "$(LAN_HOST)" || { echo "==> Could not detect a LAN address; pass LAN_HOST=<ip>."; exit 1; }
endif

dev-lan: export DEV_LOGIN_PREFILL := admin:admin
# Both origins: APP_URL alone REPLACES the derived hosts, so listing only the
# LAN address makes http://localhost:8000 fail with DisallowedHost on the very
# machine running the server (and the browser preview with it).
dev-lan: export APP_URL = http://$(LAN_HOST):$(DEV_PORT),http://localhost:$(DEV_PORT)
dev-lan: ensure-python ensure-node-deps gen-element-types
	@$(LAN_HOST_CHECK)
	@echo "==> Open http://$(LAN_HOST):$(DEV_PORT) on your phone (login admin/admin)."
	@pnpm concurrently \
		--names "Django,Tailwind,TS" \
		--prefix-colors "blue,green,magenta" \
		"uv run --frozen python -Wa manage.py runserver 0.0.0.0:$(DEV_PORT)" \
		"pnpm tailwindcss -i ./common/input.css -o ./games/static/base.css --watch" \
		"pnpm exec tsc --watch"


caddy:
	caddy run --watch

dev-prod: ensure-postgres ensure-node-deps migrate collectstatic
	@pnpm concurrently \
		--names "Caddy,Django,Django-Q" \
		"caddy run --config Caddyfile.dev" \
		"$(MAKE) gunicorn-prod" \
		"$(MAKE) qcluster-prod"

# These two run the production-like servers with PROD=1 scoped to them only (not
# to dev-prod's migrate/collectstatic prereqs). Each is a SINGLE target written in
# two lines: the `... : export PROD := 1` line attaches a target-specific env var,
# the following `... :` line is the rule + recipe. Make merges them — not a redefinition.
gunicorn-prod: export PROD := 1
gunicorn-prod: ensure-postgres
	uv run --frozen python -m gunicorn --bind 0.0.0.0:8001 timetracker.asgi:application -k uvicorn.workers.UvicornWorker

qcluster-prod: export PROD := 1
qcluster-prod: ensure-postgres
	uv run --frozen manage.py qcluster

dumpgames: ensure-postgres
	uv run --frozen python manage.py dumpdata --format yaml games --output tracker_fixture.yaml

# The deployed database, on a local scratch copy. docs/deployment.md writes the
# raw commands out for an operator with no checkout; these fill in the blanks
# from .env (PROD_SSH_HOST, PROD_DB_CONTAINER) and guard the ones worth
# guarding — a restore never lands in the development database, and a copy is
# dropped only after its migration succeeded.
#
#   make fetch-dump                 -> .dumps/timetracker-<today>.dump
#   make restore-dump               -> newest dump into $(DUMP_DB), prints its URL
#   make verify-dump                -> restore, migrate, drop
#   make verify-dump KEEP=1         -> ... and keep the copy to look at
#
# DUMP=<path> names a dump other than the newest; DUMP_DB=<name> names the
# scratch database. Rehearse anything else against the copy by passing the URL
# restore-dump printed: make migrate DATABASE_URL=<url>
DUMP ?=
DUMP_DB ?= timetracker_restore_verify

fetch-dump:
	uv run --frozen python scripts/db_dump.py fetch $(if $(strip $(OUT)),--output "$(OUT)")

restore-dump: ensure-postgres
	uv run --frozen python scripts/db_dump.py restore \
		$(if $(strip $(DUMP)),--dump "$(DUMP)") --database "$(DUMP_DB)"

verify-dump: ensure-postgres
	uv run --frozen python scripts/db_dump.py verify \
		$(if $(strip $(DUMP)),--dump "$(DUMP)") --database "$(DUMP_DB)" \
		$(if $(strip $(KEEP)),--keep)

loadplatforms: ensure-postgres
	uv run --frozen python manage.py loadplatforms

audit-uuid-identity: ensure-postgres
	uv run --frozen python manage.py audit_uuid_identity

# Usage: make bench ARGS="--seed 10000 --gate"
bench: ensure-postgres
	uv run --frozen python manage.py benchmark_events $(ARGS)

loadall: ensure-postgres
	uv run --frozen python manage.py loaddata data.yaml

loadsample: ensure-postgres
	$(if $(and $(filter command line,$(origin USER)),$(strip $(USER))),,$(error USER is required: make loadsample USER=<username>))
	uv run --frozen python manage.py load_sample_data --user "$(USER)"

anonymize-sample: ensure-postgres
	$(if $(and $(filter command line,$(origin USER)),$(strip $(USER))),,$(error USER is required: make anonymize-sample USER=<username>))
	uv run --frozen python manage.py anonymize_sample --user "$(USER)" --seed 42 --force

createsuperuser: ensure-postgres
	uv run --frozen python manage.py createsuperuser

shell: ensure-postgres
	uv run --frozen python manage.py shell

# psql against the development database. Reads stdin, so a heredoc or a pipe
# runs a one-off query without spelling the URL out again.
dbshell: ensure-postgres
	uv run --frozen python manage.py dbshell $(ARGS)

collectstatic: ensure-postgres
	uv run --frozen python manage.py collectstatic --clear --no-input

uv.lock: pyproject.toml
	uv sync

# Extra pytest arguments for `test` / `test-e2e`, so a focused run needs no raw
# tooling: make test ARGS="tests/test_filters.py -k relation -x"
ARGS ?=

# The suite is dominated by browser page loads rather than CPU, so it shards
# well: 2507 tests drop from ~370s to ~55s on a 32-core box.
#
# Half the cores is a headroom choice, not the throughput peak. Measured on an
# idle 32-core box, e2e only, interleaved runs: 16 workers 30.1s, 24 workers
# 25.3s, 28 workers 25.5s, 32 workers 29.6s plus a flaked test. So throughput
# peaks at 24 and 28 buys nothing — but 24 costs a third of the machine to save
# ~5s on a ~55s suite, and the saturation failure mode is a flaky test rather
# than a slow one. Anything else running on the box (a browser, a compile) eats
# that margin, which makes an aggressive default behave like the 32-worker run.
# Leave half the machine usable; that is also why this is not `-n auto`.
#
# CI takes one worker per vCPU instead, because what it waits on is not the
# CPU. Measured on `ubuntu-latest` (4 vCPU), three runs each: serial 1491s, 2
# workers 974s, 4 workers 696/776/797s. So a full worker per vCPU is worth
# ~3.5min over the half-the-machine ratio, and all nine runs were green. A
# runner has nothing else on it, which is the headroom a desktop spends on
# whatever else is open — that is why the ratios differ.
#
# Halve it again if a flaky failure ever appears here. Saturation shows up as a
# red run on a green tree, not as a slow one.
#
# Override to debug (`make test PYTEST_WORKERS=0`): parallel output interleaves
# and `-x` stops only the worker that hit the failure. `-n 0` runs in-process,
# so xdist is inert rather than merely single-worker.
ifneq ($(CI),)
PYTEST_WORKERS ?= $(shell cores=$$(nproc 2>/dev/null || echo 4); \
	if [ $$cores -gt 16 ]; then cores=16; fi; \
	echo $$cores)
else ifeq ($(OS),Windows_NT)
PYTEST_WORKERS ?= $(shell powershell -NoProfile -Command "[Math]::Max(1, [Math]::Min(16, [int]([Environment]::ProcessorCount / 2)))")
else
PYTEST_WORKERS ?= $(shell cores=$$(nproc 2>/dev/null || echo 2); \
	workers=$$((cores / 2)); \
	if [ $$workers -lt 1 ]; then workers=1; fi; \
	if [ $$workers -gt 16 ]; then workers=16; fi; \
	echo $$workers)
endif

# base.css (Tailwind) and js/dist (TS) are build artifacts, gitignored and not
# tracked — build both before tests so e2e/static serving has fresh assets.
test: ensure-postgres ensure-python uv.lock css ts test-ts
	uv run --frozen --with pytest-django pytest -n $(PYTEST_WORKERS) $(ARGS)

# The iteration counterpart to `test`: everything except e2e/, which is 83% of
# the suite's wall time (269 browser tests ~ 306s, against 2238 others ~ 64s).
test-fast: ensure-postgres ensure-python uv.lock css ts test-ts
	uv run --frozen --with pytest-django pytest tests/ -n $(PYTEST_WORKERS) $(ARGS)

test-e2e: ensure-postgres uv.lock css ts
	uv run --frozen pytest e2e/ -n $(PYTEST_WORKERS) $(ARGS)

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

check: ensure-python lint format-check typecheck vale ts-check check-icons check-migrations test-ts test

# Same gate minus the browser suite, for iterating. NOT the verification gate:
# `check` is, and only it can catch e2e breakage. Run this while working, `check`
# before pushing.
check-fast: ensure-python lint format-check typecheck vale ts-check check-icons check-migrations test-ts test-fast

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
