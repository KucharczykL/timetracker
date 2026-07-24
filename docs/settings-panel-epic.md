# Epic: Settings Panel

> Design doc for the settings-panel epic. Tracking issue and per-stage issues:
> [#381](https://github.com/KucharczykL/timetracker/issues/381) (Stages 1–10 → #382–#392,
> deferred follow-up → #393).

## Context

At the outset of this epic, Timetracker had **no runtime-configurable settings and almost no per-user preferences**.
All 9 config values (`DEBUG`, `SECRET_KEY`, `APP_URL`, `DEV_LOGIN_PREFILL`, `ALLOWED_HOSTS`,
`DATA_DIR`, `TZ`, `DEFAULT_CURRENCY`, `HASHED_STATIC`) resolve **once at boot** via `config()`
(env → `.env` → `settings.ini` → default) in [timetracker/config.py](timetracker/config.py) /
[timetracker/settings.py](timetracker/settings.py). The only per-user DB state is `FilterPreset`
([games/models.py:487](games/models.py)); even dark/light theme was browser-`localStorage`-only
([common/layout.py:44](common/layout.py)).

This epic introduces a **settings panel** so that (a) users set personal preferences that persist
against their account and follow them across devices, (b) admins change the "soft" site globals
without a redeploy, and (c) anyone with access can see the resolved value and **origin** of every
setting — and, when a value is pinned by env/file/ini, see it locked with the reason. Settings stay
settable by the existing means (env, file-based env, `settings.ini`); the web UI adds a database
layer *underneath* those, so env always wins and locks the field.

Deliverable: **one GitHub tracking (epic) issue + one open issue per stage**, each self-contained
enough for a later per-issue planner to execute.

## Locked design decisions (from brainstorming)

1. **Layered resolver.** A DB layer sits **below** env/`.env`/`ini` and **above** code defaults.
   The web UI writes the DB layer; any higher source wins and renders the field read-only/locked
   with its source. Uniform `resolve_with_origin(key) -> (value, source, locked)`.
2. **Registry-driven.** A single declarative `SettingDefinition` registry (key, scope
   `user|site|infra`, type, default, env-name, validator, widget, label, help, `superuser_only`,
   `apply_timing` live|restart) is the source of truth for resolver, introspection API, and widgets.
3. **Runtime writes → DB, with optional `settings.ini` export.** No new app-writable config file;
   env/file/ini stay read-only inputs. An export snapshots current DB site settings to
   `[timetracker]` ini for backup / promotion to env-pinned.
4. **Split pages.** `/settings` (personal prefs, every logged-in user) and `/admin-settings` (site
   settings + infra inspector, `is_superuser` only). Settings, Admin settings (superusers only), and
   POST Logout live inside the existing navbar Menu dropdown.
5. **Scope in-epic:** new per-user prefs + runtime site settings + infra inspector, **and** the
   harder prefs (theme, date/time format) via their own prerequisite stages.
6. **Responsive: mobile-first, desktop-enhanced.** Section-nav + content reflowing via container
   queries — native on both, not a font-size reskin. Built once as a reusable kit; **no ad-hoc
   components per page later.**

## Overriding principle: enhance, don't duplicate

Every UI stage **first checks for an existing component/util and extends it**. Verified reuse
targets and the corrections from adversarial review:

- **Forms + type→widget:** `FormFields` / `AddForm` ([common/components/primitives.py:955](common/components/primitives.py))
  with `PrimitiveWidgetsMixin` ([games/forms.py](games/forms.py)) already map plain field types to
  styled controls via Django forms — **this is the settings-widget path.** Add field-**grouping** to
  `FormFields`. **Do NOT reuse `field_widget`** ([common/components/filters.py:331](common/components/filters.py)):
  it is filter-*criterion* machinery (modifier dropdowns, `FilterSelect`, `DateRangePicker`,
  `FieldMeta`/`OperatorFilter`-typed) — wrong for plain settings and would force duplication.
- **Badge:** the static count/label `Badge` (primitives.py, used by `PageHeading`) for the
  source/locked badge — **not `Pill`** ([primitives.py:752](common/components/primitives.py)), which
  is a *removable filter tag* with JS hooks.
- **Locked/disabled look:** reuse `DISABLED_CONTROL_CLASS` / `DISABLED_WITHIN_CLASS` — locked =
  disabled control + source badge; no new disabled styling.
- **Live-save behavior:** the **custom element** `SelectDropdown` behavior
  ([ts/elements/behaviors/select.ts:63](ts/elements/behaviors/select.ts)) behind
  `SessionDeviceSelector`/`GameStatusSelector` ([common/components/domain.py:241](common/components/domain.py)) —
  optimistic `fetchWithHtmxTriggers` PATCH with revert-on-error. It is a **custom element, not
  Alpine** (Alpine only backs the toast store). It currently toasts on *error* only — success is
  silent — so Stage 3's "saved" feedback is a small **addition**, not pure reuse. New behavior
  follows the `register_element`/`gen_element_types` recipe
  ([common/components/custom_elements.py](common/components/custom_elements.py)).
- **Save feedback:** toast middleware (`HX-Trigger`→`show-toast`,
  [games/htmx_middleware.py:60](games/htmx_middleware.py)); confirmed it fires for Ninja PATCH
  (API already uses `django.contrib.messages`, [games/api.py:112](games/api.py)).
- **Page shell / width:** `render_page()` + `ContentContainer` ([common/layout.py](common/layout.py)).
- **Per-user store + API shape:** copy `FilterPreset` + its preset router
  ([games/api.py:382](games/api.py)) — `request.user` scoping, `NinjaAPI(auth=django_auth)` CSRF.
- **Responsive section navigation:** the kit uses one same-DOM link list. At narrow scaffold
  widths it moves into a native-dialog bottom sheet behind a full-width `Settings sections` /
  `Jump to a section` trigger; at wide widths it returns to the sticky rail. The generic
  `Dropdown` trigger/panel shell is reused, but the sheet has its own modal controller and
  never inherits quick-filter priority-plus or ARIA-menu semantics.

Genuinely net-new (nothing to reuse): the responsive **section-nav scaffold**, the
**source+locked badge** composite (on `Badge`), the **masked-secret** field.

## Verified constraints to honor (from adversarial review)

- **No DB access at settings import.** `resolve_with_origin` is lazy/runtime-only; the DB layer
  never participates in `settings.py` module load.
- **Live display timezone is not infrastructure `TZ`.** Stage 8 edits
  `DISPLAY_TIME_ZONE` alongside the other seven live site defaults. Boot-time `TZ` is absent from
  that page and remains deferred to Stage 9's read-only infrastructure inspector; changing `TZ`
  still requires configuration plus a restart.
- **Currency has request-aware and context-free consumers.** Purchase-entry views resolve
  `DEFAULT_CURRENCY` for the authenticated user, including blank submissions and separate-per-game
  purchases. `Purchase.save()` without request/user context and the FX conversion/reporting target
  deliberately use the site-wide resolution chain.
- **One command owns site mutations.** `change_site_setting()` in
  `timetracker/settings_commands.py` validates, normalizes, enforces higher-source locks, and returns
  a deterministic resolved result. Resolver mutation helpers do not exist. Cache invalidation is
  scheduled by model signals on transaction commit; other processes converge within the TTL.
- **Superuser gating has no 403 template** (`games/templates/` holds only `icons/`). Gate views with
  an `is_superuser` check and render an error page via `render_page()`.
- **Navbar needs `is_superuser` threaded** into `NavbarMenu()` ([common/layout.py](common/layout.py))
  so Admin settings can be included in the existing Menu dropdown for superusers only.
- **Theme FOUC:** `TimetrackerDocument()` renders account-authoritative theme state
  on the root element, and a synchronous external bootstrap applies it before
  CSS. Anonymous pages alone read `localStorage`; theme cookies and
  browser-to-account migration are intentionally absent.
- **Date/time presentation is now a shared server/client contract.** Stage 6 routes application
  display through `common.date_time_presentation.DateTimePresentation` and its versioned browser
  mirror; session rows and date-picker calendar chrome consume that contract rather than independent
  format strings or browser-default locale APIs. Stage 6.5 adds the remaining per-user timezone and
  formatting-locale prerequisite before the later date/time preference work.
- **ini export must match the reader.** `_unquote` applies only to `.env`, not ini
  ([config.py:75](timetracker/config.py)); the ini path returns raw `dict(parser[INI_SECTION])`
  ([config.py:110](timetracker/config.py)) under default `BasicInterpolation`. So export must **not**
  quote values and must use `interpolation=None`/escape `%` — otherwise `%`-bearing values (strftime
  formats, secrets) raise `InterpolationSyntaxError` and quoted values re-import with quotes.

---

## Stages (each becomes an open issue)

Dependency summary: **1** blocks all. **2** needs 1. **3** blocks all pages. **4** needs 1+2+3 and
**owns the shared `/settings` view module + navbar plumbing**. **4b** needs 4. **5** needs 2+3+4.
**6** independent. **6.5** needs 1+2+3+4+6 and blocks 7. **7** needs 1+2+3+4+6+6.5. **8** needs
1+2+3+4 (reuses 4's module + navbar). **9** needs 1+3+8. **10** needs 1+8.

### Stage 1 — Config registry + layered resolver + SiteSetting store (backend)
**Depends on:** none.
**Deliverables:**
- `SettingDefinition` dataclass + central registry declaring the boot configuration and the live
  personal/site-default settings (`DEFAULT_CURRENCY`, `DEFAULT_DEVICE`, `DEFAULT_LANDING_PAGE`,
  `DEFAULT_PAGE_SIZE`, `THEME`, `DISPLAY_TIME_ZONE`, `DATE_FORMAT_LOCALE`, and `DATETIME_FORMAT`).
  `TZ` remains `infra`/restart.
  Meta-knobs `ENV_FILE`/`INI_FILE`/deprecated `PROD` are intentionally **not** registered (note why).
  Each definition carries `apply_timing` and, for `DEV_LOGIN_PREFILL`, a note that it must stay
  `restart` (its value is read from the boot-frozen `settings` object; the `@lru_cache` in
  [games/dev_login.py](games/dev_login.py) is value-keyed and would pin a changed value).
- `SiteSetting` model (global key→value; JSON/text value). **No `swappable_dependency`** (no user FK).
- `resolve_with_origin(key) -> (value, source, locked)` — precedence env/`.env`/`ini` (locked) >
  `SiteSetting` (DB) > registry default; **lazy, never at settings import**; with TTL-bounded
  cross-process convergence and transaction-commit invalidation in the writing process.
- Route context-free `DEFAULT_CURRENCY` consumption through the site resolver in
  `games/tasks.py` and `Purchase.save()`. Request/view purchase entry uses
  `resolve_str_for_user(request.user, "DEFAULT_CURRENCY")`.
**Acceptance:** unit tests for precedence, locking, origin, "no DB query during settings import,"
invalidation only after commit, request-aware purchase entry, and site-wide context-free/reporting
currency; existing behavior unchanged with an empty table. Update
[docs/configuration.md](docs/configuration.md).
**Key files:** [timetracker/config.py](timetracker/config.py), `games/models.py`, new registry module, migration.

### Stage 2 — Per-user preferences store + resolution + Ninja API (backend)
**Depends on:** 1.
**Deliverables:**
- `UserPreferences` model (`OneToOne` to user, `related_name="preferences"`; typed columns + JSON
  bag), `get_or_create` on access. Migration uses `swappable_dependency(AUTH_USER_MODEL)` (this is
  the model that needs it). Django admin is not a mutation path.
- Per-user resolution: user value → registry site default → default (reuses Stage 1).
- Ninja `/api/settings` router: user-scoped `GET`/`PATCH` (`request.user`) + superuser `GET`/`PATCH`
  for site settings (`if not request.user.is_superuser: raise HttpError(403)`). Copy preset-router
  auth/scoping ([games/api.py:382](games/api.py)). Server-side value validation per registry validator.
**Acceptance:** tests for scoping (A can't read/write B), superuser gate, resolution precedence, validation.
**Key files:** `games/models.py`, `games/api.py`, migration.

### Stage 3 — Settings UI kit (audit-first, enhance existing, mobile-first)
**Depends on:** none (pairs with 1 for widget types). **Blocks:** 4, 7, 8, 9.
**First task:** an inventory mapping each needed piece to reuse / extend / new (per "enhance, don't
duplicate").
**Deliverables:**
- **Responsive section-nav scaffold** (net-new): mobile = stacked labeled sections + a full-width,
  self-explanatory trigger opening a native-dialog bottom sheet; desktop = sticky section-nav rail
  beside content. Container-query driven, with the same semantic link list moved—not cloned—between
  both sizes. Reuse `ContentContainer` and the generic dropdown trigger/panel shell, but do not apply
  anchored-menu positioning or ARIA-menu keyboard semantics to the sheet.
- **Field grouping**: extend `FormFields` to render grouped fieldsets (not a new renderer).
- **Setting widgets**: via the Django-form + `FormFields`/`PrimitiveWidgetsMixin` path (checkbox /
  select / number / text). **Not** `field_widget`.
- **Source + locked badge** (net-new, built on `Badge`) and **locked field** = disabled control
  (reuse `DISABLED_*`) + badge + reason.
- **Masked-secret field** (net-new; read-only, value hidden).
- **Live-save + saved feedback**: reuse the `behaviors/select.ts` custom-element PATCH pattern +
  toast; add the (currently-missing) success toast.
- Unit/e2e-test each piece in isolation before any page consumes it.
**Acceptance:** kit renders/behaves at mobile + desktop widths (e2e); inventory doc lists
reuse/extend/new per piece with justification; `make check` green.
**Key files:** [common/components/primitives.py](common/components/primitives.py), `ts/elements/`, new scaffold module.

### Stage 4 — `/settings` page + wire easy prefs; owns shared module + navbar
**Depends on:** 1, 2, 3.
**Deliverables:**
- New `games/views/settings.py` + `/settings` route (`@login_required`) + navbar entry (all users),
  rendered via the scaffold. **This stage owns the shared settings-view module and the navbar
  plumbing** that Stage 8 reuses.
- Easy prefs wired end-to-end (control → `/api/settings` → resolution → consumption), covering **all**
  initial paths:
  - **default currency** — `add_purchase`/`edit_purchase` `initial` ([games/views/purchase.py:294](games/views/purchase.py), :348)
    and the `_create_separate_purchases` currency source.
  - **default device** — both `SessionForm(initial=…)` constructions in `add_session` (including the
    `game_id` branch, [games/views/session.py:193](games/views/session.py), :202-208) and `edit_session`.
  - **default landing page** — `index()` redirect ([games/views/general.py:209](games/views/general.py));
    validate the stored URL name on save.
**Acceptance:** each pref persists and changes the target behavior on every path; e2e mobile+desktop.
**Key files:** new `games/views/settings.py`, `games/urls.py`, forms/views above, [common/layout.py](common/layout.py) navbar.

### Stage 4b — Default list page size (per_page / preset contract)
**Depends on:** 4.
**Background:** carved out of Stage 4 because per_page is a cross-cutting contract, not a localized
default. `FindFilter.per_page = 25` ([games/filters.py:70](games/filters.py)) is a semantic constant:
the preset API stores **nothing** when size equals the default (#337: [games/api.py:419](games/api.py)
`_preset_per_page`, :432 `_stored_per_page`), the URL builder omits it at default
([games/views/filtering.py:66](games/views/filtering.py)), and the TS side treats empty as default
(`ts/elements/filter-url.ts`, `presets.ts`, `quick-filter-bar.ts`).
**Deliverables:**
- An explicit sub-decision: does "no stored size" mean *site default* or *the saving user's default*?
  Then fold the per-user default into `FindFilter` resolution accordingly, updating the API
  store/omit semantics and the TS "empty = default" contract + its tests.
**Acceptance:** per-user page size applies with no `?per_page=`/preset; preset round-trip is correct
across users with different defaults; Python + vitest tests updated; `make check` green.
**Key files:** `games/filters.py`, `games/views/filtering.py`, `games/api.py`, `ts/elements/*`.

### Stage 5 — Server-side theme persistence
**Depends on:** 2, 3, 4.
**Deliverables:**
- `UserPreferences.theme` (`system|light|dark`, nullable to inherit). The root
  document state is authoritative for accounts; anonymous pages retain a
  separate `localStorage` preference. One shared coordinator owns immediate
  application, account PATCHes, and rollback. No theme cookies or migration.
- Surface theme as a control in `/settings`.
**Acceptance:** theme follows the account on a fresh browser; e2e asserts **no**
flash-of-wrong-theme, including the login page, and verifies inherited rollback.
**Key files:** [common/layout.py](common/layout.py), [games/views/auth.py](games/views/auth.py), `ts/`, `games/api.py`, `UserPreferences`.

### Stage 6 — Prerequisite: centralize date/time formatting (server + client)
**Depends on:** none. **Completed by:** #470, #471, #472.
**Delivered behavior:**
- `common.date_time_presentation.DateTimePresentation` is the sole server display contract;
  legacy `local_strftime`, Django `date_filter`, display `.strftime()`, and old format constants
  are retired from application rendering paths.
- Its versioned v1 root-document contract drives client session-row formatting and calendar chrome.
  Invalid/missing contracts report silently once and have no browser-default fallback.
- Session rebuilds convert instants with native Temporal into the configured zone, preserving the
  initial server-rendered wall-clock value across browser zones. Calendar headings and Monday-first
  weekday labels use the explicit contract locale/timezone; visible segment order, placeholders, and
  separators remain profile-driven.
- Hidden date bounds, calendar `data-date` values, and emitted filter criteria remain ISO
  `YYYY-MM-DD`; presentation never changes filter serialization.
**Acceptance:** server/client presentation consumes this one contract; snapshots and e2e are unchanged
except for the approved explicit-locale, footer-minute, and cross-timezone corrections.
**Key files:** [common/date_time_presentation.py](common/date_time_presentation.py),
[games/formatting.py](games/formatting.py), `ts/date-time-presentation.ts`, `ts/session-row.ts`,
`ts/elements/date-range-picker.ts`.

### Stage 6.5 — Per-user timezone and formatting locale
**Depends on:** 1, 2, 3, 4, and Stage 6. **Blocks:** Stage 7. See #473.
**Deliverables:** nullable user timezone and formatting-locale preferences with validated, normalized
values; request-scoped timezone activation; datetime-local form interpretation in the selected zone;
and live settings controls/API persistence. The timezone remains distinct from boot-time infrastructure
`TZ`; formatting locale changes calendar/date conventions only, never application-copy translation.
**Acceptance:** server and client wall-clock displays agree after timezone/locale changes; date-only
values and UTC/API storage remain stable; DST validation and concurrent-user isolation are covered.

### Stage 7 — Per-user date/time format preference
**Depends on:** 1, 2, 3, 4, 6, 6.5.
**Deliverables:** `UserPreferences.datetime_format` (choice set), resolved per request, fed to the
Stage 6 server formatter **and** exposed to the client mirror; control surfaced in `/settings`.
**Acceptance:** changing the pref changes rendered dates app-wide, server- and client-rendered rows
consistent; tests.
**Key files:** `UserPreferences`, Stage 6 formatter (server + client), `/settings`, `games/api.py`.

### Stage 8 — `/admin-settings` page: site settings (superuser)
**Depends on:** 1, 2, 3, 4 (reuses Stage 4's settings module + navbar plumbing).
**Deliverables:**
- `/tracker/admin-settings` is login-protected and gated to `is_superuser`; authenticated
  non-superusers receive a component-rendered 403 page. **Admin settings** is present only for
  superusers and lives inside the existing navbar **Menu** dropdown beside Settings and POST
  Logout.
- The page exposes exactly `DEFAULT_CURRENCY`, `DEFAULT_DEVICE`, `DEFAULT_LANDING_PAGE`,
  `DEFAULT_PAGE_SIZE`, `THEME`, `DISPLAY_TIME_ZONE`, `DATE_FORMAT_LOCALE`, and
  `DATETIME_FORMAT`. All eight are live site defaults inherited by users without personal
  overrides.
- The site PATCH API delegates every mutation to `change_site_setting()` in
  `timetracker/settings_commands.py`. Values owned by environment, environment-file, `.env`, or
  `settings.ini` are disabled with their source and explanation; a direct PATCH returns HTTP 409.
  Clearing an editable value removes its DB override and returns the configured or built-in
  fallback.
- Infrastructure `TZ` is not on this page. `DISPLAY_TIME_ZONE` is the editable wall-clock
  presentation default and uses the existing reload flow to rebuild the document contract. The
  navbar theme switcher is unavailable on settings pages.
- Currency remains scope-aware: purchase-entry views use the user's resolved preference, while
  `Purchase.save()` without user context and FX conversion/reporting use the site default.
**Acceptance:** page/API/navbar authorization; exact eight-key surface; normalized set/select/clear
PATCH responses; committed source badges; locked disabled fields and HTTP 409; display-timezone
reload contract; usable mobile/desktop section navigation and Menu-dropdown link.
**Key files:** `timetracker/settings_commands.py`, `games/api.py`,
`games/views/settings.py`, `games/urls.py`, [common/layout.py](common/layout.py), browser tests.

### Stage 9 — Infrastructure config inspector
**Depends on:** 1, 3, 8.
**Deliverables:** add a read-only section to `/admin-settings` listing infrastructure settings via
`resolve_with_origin`, including boot-only `TZ`, with effective value, source, and restart
semantics. Render `SECRET_KEY` only through the masked-secret field. There is no edit or PATCH path;
Stage 9 is an inspector, not a replacement Django admin.
**Acceptance:** every infra setting shows its correct resolved value/source and whether a restart is
required; `TZ` is visibly distinct from live `DISPLAY_TIME_ZONE`; secret material never appears in
HTML or API output; mutation controls and endpoints are absent.
**Key files:** `/admin-settings` view, Stage 1 introspection, Stage 3 kit.

### Stage 10 — Export site settings → `settings.ini` snapshot
**Depends on:** 1, 8.
**Deliverables:** superuser download action on `/admin-settings` serializing current DB site settings
to a `[timetracker]` ini. **Match the reader:** no quoting, `interpolation=None` (or escape `%`), so
`%`-bearing values don't raise `InterpolationSyntaxError` and values re-import identically via
`config.py`'s ConfigParser ([timetracker/config.py:101](timetracker/config.py)). This is also the
promotion path for `TZ` (edit ini → restart).
**Acceptance:** exported file re-imports to identical values, including a value containing `%`; tests.
**Key files:** `/admin-settings` view, [timetracker/config.py](timetracker/config.py).

---

## Cross-cutting (apply across stages)

- **Docs:** each stage touching config surface updates [docs/configuration.md](docs/configuration.md).
- **CHANGELOG:** the repo maintains `CHANGELOG.md`; user-facing stages update it.
- **Administration:** Django admin is removed. Django auth/superusers remain, and debug builds retain
  `django_extensions` plus the debug toolbar. Site-default writes use
  `timetracker/settings_commands.py`.
- **Caching:** model signals invalidate resolver snapshots on transaction commit. Other web workers
  and qcluster processes converge through the shared TTL; commands return their canonical result
  without a resolver readback or immediate pre-commit invalidation.
- **Verification gate:** every stage runs the full `direnv exec . make check` (lint, format, mypy,
  ts-check, vitest, pytest incl. `e2e/`) in the Nix shell — never a subset. UI stages add e2e at
  mobile + desktop viewports; Stage 5 adds a no-FOUC assertion.
- **Manual epic check:** set a value via env and panel → env wins, the field is disabled with its
  source/reason, and direct PATCH returns 409. Change site `DEFAULT_CURRENCY` → inheriting
  purchase-entry views, context-free `Purchase.save()`, and the FX task use it; save a personal
  currency → only that user's purchase-entry flow changes.
- **SOURCE-BADGE DELETION GATE (must be resolved before closing #381):**
  - [ ] List at least one concrete shipped unlocked/editable setting where an inline source badge
    adds user value beyond the field label and help text.
  - [ ] Verify every badged control still has a visible field label; source metadata must never act
    as the field's identity.
  - [ ] If no such unlocked use case exists, delete unlocked inline source badges from
    `prepare_setting_fields`, the preview gallery/variants, tests, and documentation. Keep
    source/lock provenance only for concrete locked/read-only use cases in Stages 8 and 9.

## Deferred — file as its own issue, linked from the epic, NOT executed here

- **Env-lock per-user prefs** (brainstorm group 4): let admins hard-lock a per-user pref site-wide via
  env (e.g. force everyone to CZK), adding a per-user-vs-site precedence dimension.

## Execution note (issue creation)

After approval: create the epic tracking issue first, then the stage issues (1, 2, 3, 4, 4b, 5, 6, 7,
8, 9, 10) + the deferred follow-up, then edit the epic body to link them as a task list with the
dependencies above.
