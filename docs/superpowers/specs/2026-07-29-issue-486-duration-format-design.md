# Per-user duration display format (#486)

Follow-up to the settings epic (#381), sibling to the date/time format preference
(#389). Duration is a distinct semantic value — no timezone, no calendar, no
12/24-hour clock — so it gets its own contract rather than riding on
`DATETIME_FORMAT`.

## Problem

Nine call sites format durations today, through eight distinct
`format_duration()` pattern strings:

| site | pattern | renders |
|---|---|---|
| `Session.duration_formatted()` | `%02.1H` | `3.2` |
| `Game.playtime_formatted()` | `%2.1H` | `3.2` |
| `SessionQuerySet.total_duration_formatted()` | `%H hours` | `3 hours` |
| game detail filtered playtime (`game.py:124`, `:451`) | `%2.1H` | `3.2` |
| navbar today / last-7 (`general.py:82`) | `%H h %m m` | `3 h 12 m` |
| play-event range total (`playevent.py:166`) | `%Hh %mm` | `3h 12m` |
| stats longest session / average (`stats_data.py:306`, `:318`) | `%2.0Hh %2.0mm` | ` 3h 12m` |
| stats year total (`stats_data.py:279`) | `%2.0H` | `1234` |
| stats card durations (`stats_content.py:105`) | `%2.1H hours` | `3.2 hours` |

That is drift, not intent. There is no user preference, and the `%H`/`%m`
mini-language in `common/time.py` invites a ninth variant with every new surface.

## Shape of the solution

One profile ID per user selects how *every* human-visible duration renders.
Each duration also carries a popover listing the same value in the other
profiles, so no rendering is a dead end — the lossy profiles are exactly the
ones that need it.

Four profiles:

| id | settings label | 1 h 12 m renders as |
|---|---|---|
| `decimal_hours` | Decimal hours (1.2 h) | `1.2 h` |
| `hours_minutes` | Hours and minutes (1 h 12 m) | `1 h 12 m` |
| `whole_hours` | Whole hours (1 hour) | `1 hour` |
| `adaptive` | Adaptive units (3 d 11 h) | `1 h 12 m` |

Default is `decimal_hours` — what the session list and game playtime already
render, so an untouched install looks unchanged.

### Rendering rules

Grouped values below use `_` for the locale group separator, which is **U+00A0
NBSP under `cs`**, not an ASCII space (see Locale, below).

| value | `decimal_hours` | `hours_minutes` | `whole_hours` | `adaptive` |
|---|---|---|---|---|
| 0 | `0.0 h` | `0 h` | `0 hours` | `0 h` |
| 45 s | `0.0 h` | `1 m` | `0 hours` | `1 m` |
| 29 min | `0.5 h` | `29 m` | `0 hours` | `29 m` |
| 45 min | `0.8 h` | `45 m` | `1 hour` | `45 m` |
| 1 h 12 m | `1.2 h` | `1 h 12 m` | `1 hour` | `1 h 12 m` |
| 3 h 5 m | `3.1 h` | `3 h 05 m` | `3 hours` | `3 h 05 m` |
| 3 h 30 m | `3.5 h` | `3 h 30 m` | `4 hours` | `3 h 30 m` |
| 23 h 59 m 45 s | `24.0 h` | `24 h 00 m` | `24 hours` | `1 d 00 h` |
| 26 h | `26.0 h` | `26 h 00 m` | `26 hours` | `1 d 02 h` |
| 83 h 12 m | `83.2 h` | `83 h 12 m` | `83 hours` | `3 d 11 h` |
| 200 h | `200.0 h` | `200 h 00 m` | `200 hours` | `1 w 1 d` |
| 1234 h | `1_234.0 h` | `1_234 h 00 m` | `1_234 hours` | `7 w 2 d` |
| 9000 h | `9_000.0 h` | `9_000 h 00 m` | `9_000 hours` | `1 y 2 w` |

Invariants behind the table:

- **Round, never truncate**, each profile at its own resolution, half away from
  zero. Truncation renders `59 m` as `0 hours`, a lie the popover should not
  have to repair.
- **Round the total once, then decompose.** Rounding a component after the split
  produces `2 h 60 m` at 1 h 59 m 45 s. This is the single rule that keeps every
  profile's carry correct, including `adaptive`'s.
- **Seconds never appear.** Sessions are wall-clock ranges and aggregates are
  hours; nothing in the app records durations where seconds are meaningful.
- **Negative clamps to zero**, as `common/time.py` does today. `timestamp_end <
  timestamp_start` is bad data, not a negative duration.
- **`hours_minutes` suppresses a zero hour** (`45 m`, not `0 h 45 m`) and pads
  minutes to two digits when hours are present, so a table column stays aligned.
  Zero is the one special case: `0 h`, keeping the column's unit stable.
- **Zero-padding elsewhere:** `adaptive` pads its second unit to two digits only
  when that unit is the hour (`1 d 02 h`); day, week, and year second units are
  unpadded (`1 w 1 d`, `1 y 2 w`). Nothing else pads.
- **`whole_hours` pluralizes** on the rounded value: `1 hour`, `0 hours`,
  `4 hours`.
- **Hours never roll into days** in the first three profiles. Hours are this
  app's unit of account — the filter facets are `playtime_hours` and
  `duration_total_hours`, the stats headline is total hours. `adaptive` exists
  precisely so that wanting days does not force everyone else to have them.

### The `adaptive` ladder

Units are minute, hour, day (24 h), week (7 d), year (52 w = 364 d). A year is
not a whole number of weeks; 364 is the definition that keeps the ladder exact,
and nothing here is a calendar date, so the drift is harmless.

Algorithm: pick the largest unit the raw value reaches, round the total to the
*next unit down*'s resolution, decompose, and show the top two units. If the
rounding carries into a higher unit, re-pick — `6 d 23 h 40 m` becomes `1 w 0 d`,
not `6 d 24 h`.

`adaptive` and `hours_minutes` agree below 24 h **except at the carry
boundary**: 23 h 59 m 45 s rounds to 1440 minutes, which `hours_minutes` renders
`24 h 00 m` while `adaptive` re-picks to `1 d 00 h`. This is why popover dedup is
computed on rendered strings, never on a "which profiles are equivalent" rule.

### The popover

Every human-visible duration renders as a `Popover` listing the same value under
the *other* profiles, labelled:

```
1.2 h                          ← visible, underline decoration-dotted
  Hours and minutes  1 h 12 m
  Whole hours        1 hour
```

- **Distinct renderings only**, compared as strings after rendering. Drop any
  alternate equal to the visible value or to an earlier alternate. In practice
  most values show two lines and long ones show three, but the count is a
  consequence, never an assumption — see the carry boundary above.
- **Bare label/value rows**, no panel title. The panel is `role="tooltip"`; a
  title is a word every screen reader reads before the data, for no information.
- **Values get `tabular-nums`**, as does the visible cell, which today gets its
  fixed width from the `%02.1H` pattern being deleted.
- **`tap=True`** (the default) — the trigger is a real `<button>`, operable by
  mouse, touch, and keyboard. See Accessibility.

**Every popover needs a caller-supplied DOM id.** `Popover()` otherwise derives
one by hashing its own content (`primitives.py:450`), so two rows with the same
duration collide, and `assert_unique_element_ids()` raises during DEBUG page
assembly (`core.py:506`). `Game.playtime` defaults to `timedelta(0)`, so any
game list with two never-played games would trip it — and
`tests/test_html_validity.py:187` asserts exactly this on `games:list_games`.
`PurchasePrice` already carries a comment about being bitten by this
(`domain.py:281`). So `Duration()` takes a required id scope, and every call site
supplies one: `f"session-{pk}-duration"`, `f"game-{pk}-playtime"`,
`"navbar-today"`, `"stats-total-hours"`, and so on.

### The manual-session mark

`duration_formatted_with_mark()` appends `*` for manual sessions. The mark stays
**inside the trigger, after the visible value**, is covered by the same
`aria-hidden`, and the `sr-only` text ends with ", manual" so the information
survives for screen readers. It does not appear in popover alternates — it
qualifies the value, not its formatting.

### Accessibility

The visible text is `aria-hidden`; a sibling `sr-only` span carries the value in
full words, **independent of profile**: hours and minutes only (never days or
weeks — "375 days" helps nobody), each component pluralized, a zero component
omitted, and a zero duration spoken as "0 hours". So `1 h 12 m` is "1 hour 12
minutes", `45 m` is "45 minutes", and `9000 h` is "9000 hours".

`1.2 h` spoken is "one point two h", and `3 d 11 h` is worse — abbreviation is
exactly what screen readers mangle. The spoken form is more precise than
`decimal_hours` shows; that is fine, it is the same value said unambiguously.

`aria-describedby` is **dropped** on duration popovers (a new `describedby=False`
option on `Popover`; the panel stays for sighted users). Without it, Orca would
read the same number three ways on every row. This is safe for the element's JS:
`ts/elements/pop-over.ts` addresses `[data-pop-over-panel]` and
`[data-pop-over-trigger]` and never reads `aria-describedby`, and no existing
test asserts it is unconditionally present.

**The trigger stays a real `<button>` (`tap=True`).** Both alternatives
considered — `tap=False`, and a `<span>` carrying the tap bindings — reach the
panel by pointer but not by keyboard, which fails WCAG 2.1.1 for a sighted
keyboard-only user: they would see one format where a mouse user sees four. The
"it exposes no unique information" defence is too thin to rest on.

The cost is one tab stop per duration. That is ordinary: `DEFAULT_PAGE_SIZE` is
25, and a session row already carries a game link, a device dropdown, Edit, and
Delete, so this is roughly a 20% increase in a row's tab stops rather than a new
class of problem. A user who selects the 1000-row page size has opted into a
dense page in which every existing per-row control multiplies identically.

Verify with a real Orca pass on a session list before merge.

## Architecture

### `common/duration_presentation.py`

Mirrors `common/date_time_presentation.py`:

- `type DurationProfileId = str` and a `MappingProxyType` registry of the four
  profiles, each a frozen dataclass of its rendering rules.
- `DurationPresentation(profile, locale)` — frozen, immutable, one per request.
  `format(value) -> str` for the visible rendering, `alternates(value) ->
  tuple[tuple[str, str], ...]` for the deduplicated (label, rendering) pairs,
  `spoken(value) -> str` for the sr-only form.
- `duration_presentation_for_request(request)` — resolves via
  `resolve_str_for_user(user, "DURATION_FORMAT")`, caches on the request object,
  exactly as the date/time equivalent does.
- A module-level `format_decimal_hours(value) -> str`, preference-independent,
  for `Session.__str__` and any other non-request caller.

No `to_client_config()` and no TypeScript counterpart — see the prerequisite.

### Locale: grouping is opt-in per call

`USE_THOUSAND_SEPARATOR` is **absent from settings**, so Django's default
`False` applies and `number_format()` does no grouping. Flipping it globally
would retroactively regroup every price on the site, so instead the formatter
passes `force_grouping=True` explicitly.

`DATE_FORMAT_LOCALE` is deliberately never activated request-wide —
`common/middleware.py:49` stashes it on the request precisely so date formatting
cannot change application translations. The duration formatter follows the
`day_periods_for_locale()` precedent (`date_time_presentation.py:293`) and scopes
`override(locale)` around its own `number_format()` call only.

The `cs` separator is U+00A0 (`django/conf/locale/cs/formats.py`). Tests must
assert the NBSP, not an ASCII space.

### `Duration()` component

A new builder in `common/components/domain.py`, taking the value, the
presentation, and a required id scope (see above). Call sites never assemble the
popover themselves, so a surface cannot forget it — or forget its id.

### Registry entry

`DURATION_FORMAT` in `timetracker/settings_registry.py`, as a
`SettingDefinition`: `SettingScope.USER`, `ApplyTiming.LIVE`,
`SettingWidget.SELECT`, a `label`, a `DURATION_FORMAT_CHOICES` tuple (the
`__post_init__` guard at `:150` rejects a SELECT without `choices`, and `:148`
rejects a USER setting without a widget), `reload_after_save=True`,
`default_factory` returning `"decimal_hours"`, and a `_validate_duration_format`
rejecting unregistered IDs the way `_validate_datetime_format` does.

**No migration.** Unmapped keys fall through `UserPreferences.extra_preferences`
(`games/models.py:570`), as `SESSION_TIME_ZONE_DISPLAY` already does.

Pinned test fixtures that enumerate settings by hand and will fail until
updated: `tests/test_settings_registry.py:21` (`USER_KEYS`),
`tests/test_admin_settings_page.py:25` (`SITE_SETTING_KEYS`, order-sensitive),
`tests/test_admin_settings_page.py:326` (a literal count of SELECT widgets),
plus the env-scrub fixtures at `tests/test_admin_settings_page.py:38` and
`e2e/test_admin_settings_page_e2e.py:13`.

### Formatting moves off the models

`Session.duration_formatted()`, `Session.duration_formatted_with_mark()`, and
`Game.playtime_formatted()` are **deleted**. A model method has no request and
therefore cannot resolve a per-user preference; the date/time contract already
established that formatting lives in views and components.

- `Session.__str__` calls `format_decimal_hours()` directly — it is a
  debug/admin/log string, not UI.
- `SessionQuerySet.total_duration_formatted()` and
  `calculated_duration_formatted()` have **no callers anywhere** (verified across
  Python, templates, `ts/`, `dist/`, e2e, management commands, and the API).
  Deleted, not ported. Their `*_unformatted()` siblings do have callers and stay.
- `tests/test_session_formatting.py:37` asserts `duration_formatted()` and must
  be updated; it also holds unrelated datetime tests, so it cannot simply be
  deleted alongside `tests/test_time.py`.

### Stats layering

`compute_stats()` is documented as pure computation with no HTTP, and it must
stay that way rather than take a presentation. So it returns **`timedelta`**
values and `stats_content` formats them. That changes `StatsData.total_hours`
from `str` to `timedelta`, and `longest_session_time` /
`highest_session_average` from `Any` (currently `timedelta`-or-integer-`0`) to
`timedelta | None` — the `0` fallback becomes `None`. Consumers at
`stats_content.py:149`, `:199`, `:212` follow. `playevent.py:166` has the same
shape: return the `timedelta`, format at the call site.

### `common/time.py` cleanup

`format_duration()`, `durationformat`, and `durationformat_manual` are deleted
outright, along with the `%H`/`%m` mini-language. `tests/test_time.py`'s duration
half is replaced by the new formatter's tests. Keeping a second duration
formatter around is the drift this work exists to end.

## Prerequisite: retire the finish/reset row swap (#583)

**Separate, separately-landable PR, merged first.**

Finish and reset currently PATCH `/api/session/{id}` and rebuild the row
client-side (`ts/session-row.ts`, driven by `ts/elements/session-actions.ts`).
That is the only client-rendered duration in the app. Keeping it would force a
TypeScript duration formatter, a cross-language parity contract, and a real
locale hazard — Django's `number_format` and JS `Intl.NumberFormat` do not
reliably agree on the `cs` group separator.

Replacing the swap with a plain POST and a full page reload deletes that entire
half of the feature, and a second hand-port with it: `formatSessionTimeRange`
re-implements the server's zone-label and date-line rules in TypeScript (verified
to have `session-row.ts` as its only consumer).

**`<session-actions>` shrinks; it is not deleted.** `custom_element_builder`
auto-attaches `Media(js="dist/elements/<tag>.js")` (`primitives.py:252`), and
`HashedStaticStorage` treats a missing manifest entry as a hard error — so
deleting the TS file while keeping the element emits a `<script>` for a file that
does not exist. The element survives as a ~15-line browser-time-zone stamper (see
below); the props drop to what that needs.

**Deletes** — `ts/session-row.ts`, `ts/session-row.test.ts`,
`tests/test_session_row.py`, the row-swap and modal logic inside
`ts/elements/session-actions.ts`, the `api_url` prop, the inline reset `Modal`
and its body-portal hack in `SessionActions`, and `formatSessionTimeRange` plus
its tests.

Removing that modal also orphans `Modal(self_dismiss=False)` — its only
consumer — and the `data-manage="false"` branch in `ts/elements/modal-dialog.ts`,
along with `tests/test_components.py:1088` and
`ts/elements/modal-dialog.test.ts:51`. Either delete the branch too or leave it
deliberately, but do not leave the stale comments at `primitives.py:1679` and
`modal-dialog.ts:9` pointing at a component that no longer exists.

**Adds** — `games:finish_session` and `games:reset_session`, both POST-acting,
both classified `ORIGIN_AWARE` in `games/views/returns.py`, both ending in
`redirect(return_url(request, fallback="games:list_sessions"))`. Finish is a
`ControlButton(method="post")`. Reset answers GET with a `ConfirmPage` and acts
on POST at the same URL. Both targets built with
`action_url(name, session.pk, origin=origin)`.

`ORIGIN_AWARE` is correct and verified: `tests/test_returns_classification.py`
enforces only exactly-one-bucket membership, and every `games:delete_*` route —
all GET-confirms/POST-acts at one URL — already sits there.

**`confirm_and_delete()` cannot be reused as-is**: it hardcodes
`instance.delete()` (`deletion.py:54`) and `confirm_label="Delete"` (`:50`).
Generalize it into a `confirm_and_apply(action, confirm_label, ...)` with
`confirm_and_delete()` kept as a thin wrapper, so the seven existing delete views
are untouched.

**Browser time zone.** The client currently sends
`timestamp_end_timezone: browserTimeZone()`. A plain POST does not know it, and
`SESSION_TIME_ZONE_DISPLAY` defaults to `"own"`, so recording the account zone
would visibly lie for a travelling user — the exact case #473 exists for. The
shrunken `<session-actions>` fills a hidden input using the same
`Intl.DateTimeFormat().resolvedOptions()` detection `ts/elements/time-zone-row.ts`
already uses. The zone is data, not presentation.

**`PATCH /api/session/{id}` stays.** It becomes UI-unused (verified: no other UI
caller), but it is a documented REST surface next to the device PATCH.

**Rewrites** — `e2e/test_session_finish_e2e.py`, `e2e/test_session_reset_e2e.py`,
and `e2e/test_time_zone_row_e2e.py:100` (`test_finish_stamps_the_end_zone`),
which clicks `[data-finish]` and asserts the row updates *without* a reload. It
is also the only regression guard for the browser-zone hazard above, so it must
be rewritten rather than dropped. `tests/test_rendered_pages.py:467` and
`tests/test_components.py:307` assert the `api-url` attribute and fail outright
once the prop goes — not touch-ups.

Consequence for #486: "server-rendered and client-rebuilt content are
byte-identical" is satisfied by construction; no client rebuild exists. Already
moved to out-of-scope on the issue.

## Audit: surfaces that consume the formatter

| surface | file |
|---|---|
| session list duration cell | `games/views/session.py:62` |
| game detail sessions table | `games/views/game.py:612` |
| game list playtime | `games/views/game.py:505` |
| game detail filtered playtime | `games/views/game.py:124`, `:451` |
| navbar today / last-7 | `games/views/general.py:82` |
| play-event range total | `games/views/playevent.py:166` |
| stats total, longest session, session average | `games/views/stats_data.py:279`, `:306`, `:318` |
| stats card durations | `games/views/stats_content.py:105` |

Threading: the navbar values come from the `model_counts` context processor,
which has the request. Stats formats in `stats_content`, which receives one.
Neither needs new plumbing; `compute_stats()` deliberately gets none.

## Untouched, canonical

Database values, `GeneratedField` computation, all filtering and sorting
(DB-side), the `duration_manual` form input (`HH:MM:SS`), the API's
`duration_manual_seconds` integer, and the `playtime_hours` /
`duration_total_hours` filter facets. None of these are presentation.

## Testing

- Table-driven unit tests over every cell above, plus the carry boundaries
  (`1 h 59 m 45 s`, `23 h 59 m 45 s`, `6 d 23 h 40 m`, `29 m 30 s`).
- Locale tests asserting `force_grouping` output and the decimal separator under
  `cs` and `en-us`, with the NBSP written explicitly as `\xa0`.
- Popover dedup by rendered string, including the 23 h 59 m 45 s case where
  `adaptive` and `hours_minutes` diverge below 24 h.
- Popover id uniqueness on a list page with two equal-duration rows — the case
  `tests/test_html_validity.py:187` already guards for other components.
- Registry tests: unregistered profile ID rejected; clearing the user value
  restores the site default; live-save and source metadata behave like
  `DATETIME_FORMAT`.
- Rendered-page assertions on the audited surfaces.
- One e2e pass changing the preference and confirming a session list re-renders.

## Tracking

- #583 — retire the finish/reset row swap. #486 is blocked on it.
- #486 — design section points here; TypeScript parity moved to out-of-scope.

## Open

- `docs/configuration.md` is convention for a new setting but is not
  drift-tested and is already stale (`SESSION_TIME_ZONE_DISPLAY` missing, a wrong
  "eight live site defaults" count at `:118`). Decide explicitly whether this
  work fixes that or only appends.

## Out of scope

Calendar date, clock time, datetime, timezone, and formatting-locale behaviour
(#388, #389, #473). Changing stored duration precision or calculation semantics.
A days-based option for the non-`adaptive` profiles.
