# Per-user duration display format (#486)

Follow-up to the settings epic (#381), sibling to the date/time format preference
(#389). Duration is a distinct semantic value — no timezone, no calendar, no
12/24-hour clock — so it gets its own contract rather than riding on
`DATETIME_FORMAT`.

## Problem

Six call sites format durations today, each with its own `format_duration()`
pattern string:

| site | pattern | renders |
|---|---|---|
| `Session.duration_formatted()` | `%02.1H` | `3.2` |
| `Game.playtime_formatted()` | `%2.1H` | `3.2` |
| `SessionQuerySet.total_duration_formatted()` | `%H hours` | `3 hours` |
| navbar today / last-7 | `%H h %m m` | `3 h 12 m` |
| stats longest session / session average | `%2.0Hh %2.0mm` | ` 3h 12m` |
| stats year total | `%2.0H` | `1234` |

That is drift, not intent. There is no user preference, and the `%H`/`%m`
mini-language in `common/time.py` invites a seventh variant with every new
surface.

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

| value | `decimal_hours` | `hours_minutes` | `whole_hours` | `adaptive` |
|---|---|---|---|---|
| 0 | `0.0 h` | `0 h` | `0 hours` | `0 h` |
| 45 s | `0.0 h` | `1 m` | `0 hours` | `1 m` |
| 29 min | `0.5 h` | `29 m` | `0 hours` | `29 m` |
| 45 min | `0.8 h` | `45 m` | `1 hour` | `45 m` |
| 1 h 12 m | `1.2 h` | `1 h 12 m` | `1 hour` | `1 h 12 m` |
| 3 h 5 m | `3.1 h` | `3 h 05 m` | `3 hours` | `3 h 05 m` |
| 3 h 30 m | `3.5 h` | `3 h 30 m` | `4 hours` | `3 h 30 m` |
| 26 h | `26.0 h` | `26 h 00 m` | `26 hours` | `1 d 02 h` |
| 83 h 12 m | `83.2 h` | `83 h 12 m` | `83 hours` | `3 d 11 h` |
| 200 h | `200.0 h` | `200 h 00 m` | `200 hours` | `1 w 1 d` |
| 1234 h | `1 234.0 h` | `1 234 h 00 m` | `1 234 hours` | `7 w 2 d` |
| 9000 h | `9 000.0 h` | `9 000 h 00 m` | `9 000 hours` | `1 y 2 w` |

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
- **Locale owns grouping and the decimal separator.** `DATE_FORMAT_LOCALE`
  already resolves per request; `1 234,0 h` under `cs`, `1,234.0 h` under
  `en-us`.
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
not `6 d 24 h`. Below 24 h `adaptive` is identical to `hours_minutes` by
construction, which is why the two profiles collapse to one popover line there
(see below).

### The popover

Every human-visible duration renders as a `Popover` listing the same value under
the *other* profiles, labelled:

```
1.2 h                          ← visible, underline decoration-dotted
  Hours and minutes  1 h 12 m
  Whole hours        1 hour
```

- **Distinct renderings only.** Drop any alternate equal to the visible value or
  to an earlier alternate. `hours_minutes` and `adaptive` are identical below
  24 h, so most rows show two lines and only long values show three.
- **Bare label/value rows**, no panel title. The panel is `role="tooltip"`; a
  title is a word every screen reader reads before the data, for no information.
- **Values get `tabular-nums`** so a column does not jitter.
- **`tap=False`** — the trigger is the hover/focus-only `<span>`, not a
  `<button>`. A 1000-row session list would otherwise add 1000 tab stops to a
  control that announces nothing extra (see accessibility below). Cost: touch
  users see only the visible profile. Accepted, because the sr-only text below
  means nobody loses information.

### Accessibility

The visible text is `aria-hidden`; a sibling `sr-only` span carries the value in
full words, **independent of profile**: hours and minutes only (never days or
weeks — "375 days" helps nobody), each component pluralized, a zero component
omitted, and a zero duration spoken as "0 hours". So `1 h 12 m` is "1 hour 12
minutes", `45 m` is "45 minutes", and `9000 h` is "9000 hours".

```html
<span aria-hidden="true">1.2 h</span><span class="sr-only">1 hour 12 minutes</span>
```

`1.2 h` spoken is "one point two h", and `3 d 11 h` is worse — abbreviation is
exactly what screen readers mangle. The spoken form is more precise than
`decimal_hours` shows; that is fine, it is the same value said unambiguously.

`aria-describedby` is **dropped** on duration popovers (a new `describedby=False`
option on `Popover`; the panel stays for sighted users). Without it, Orca would
read the same number three ways on every row.

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

No `to_client_config()` and no TypeScript counterpart — see the prerequisite
below.

### `Duration()` component

A new builder in `common/components/domain.py` returning the popover node.
Takes the value and the presentation; call sites never assemble the popover
themselves, so a surface cannot forget it.

### Registry entry

`DURATION_FORMAT` in `timetracker/settings_registry.py`: `SettingScope.USER`,
`ApplyTiming.LIVE`, `SettingWidget.SELECT`, `reload_after_save=True` (the
preference only affects server-rendered content), `default_factory` returning
`"decimal_hours"`, and a `_validate_duration_format` rejecting unregistered IDs
the way `_validate_datetime_format` does.

### Formatting moves off the models

`Session.duration_formatted()`, `Session.duration_formatted_with_mark()`, and
`Game.playtime_formatted()` are **deleted**. A model method has no request and
therefore cannot resolve a per-user preference; the date/time contract already
established that formatting lives in views and components. Only three UI call
sites reference them.

- `Session.__str__` keeps a fixed, preference-independent decimal-hours
  rendering. It is a debug/admin/log string, not UI.
- `SessionQuerySet.total_duration_formatted()` and
  `calculated_duration_formatted()` have no callers. Deleted, not ported.

### `common/time.py` cleanup

`format_duration()`, `durationformat`, and `durationformat_manual` are deleted
outright, along with the `%H`/`%m` mini-language. After the migration only
`tests/test_time.py` exercises them, and it is replaced by the new formatter's
tests. Keeping a second duration formatter around is the drift this work exists
to end.

## Prerequisite: retire the finish/reset row swap

**Separate, separately-landable PR, merged first.**

Finish and reset currently PATCH `/api/session/{id}` and rebuild the row
client-side (`ts/session-row.ts`, driven by `ts/elements/session-actions.ts`).
That is the only client-rendered duration in the app. Keeping it would force a
TypeScript duration formatter, a cross-language parity contract, and a real
locale hazard — Django's `number_format` and JS `Intl.NumberFormat` do not
reliably agree on the `cs` group separator (narrow NBSP vs NBSP).

Replacing the swap with a plain POST and a full page reload deletes that entire
half of the feature. It also removes a second hand-port: `formatSessionTimeRange`
re-implements the server's zone-label and date-line rules in TypeScript.

**Deletes** — `ts/session-row.ts`, `ts/session-row.test.ts`,
`ts/elements/session-actions.ts`, `tests/test_session_row.py`, the
`SessionActionsProps` `api_url`/`csrf` props, the inline reset `Modal` and its
body-portal hack in `SessionActions`, and `formatSessionTimeRange` plus its
tests in `ts/date-time-presentation.test.ts`.

**Adds** — `games:finish_session` and `games:reset_session`, both POST-acting,
both classified `ORIGIN_AWARE` in `games/views/returns.py`, both ending in
`redirect(return_url(request, fallback="games:list_sessions"))`. Finish is a
`ControlButton(method="post")`. Reset answers GET with a `ConfirmPage` and acts
on POST at the same URL — the `confirm_and_delete()` shape, which is why it is
`ORIGIN_AWARE` rather than `CONFIRMATION` (that bucket is for separate-URL
confirm pages like refund/split). Both targets are built with
`action_url(name, session.pk, origin=origin)`, matching the Edit/Delete members
already in that `ButtonGroup`.

**Browser time zone.** The client currently sends
`timestamp_end_timezone: browserTimeZone()`. A plain POST does not know it, and
`SESSION_TIME_ZONE_DISPLAY` defaults to `"own"`, so recording the account zone
would visibly lie for a travelling user — the exact case #473 exists for. Keep
a hidden input filled by the same `Intl.DateTimeFormat().resolvedOptions()`
detection `ts/elements/time-zone-row.ts` already uses. The zone is data, not
presentation.

**`PATCH /api/session/{id}` stays.** It becomes UI-unused, but it is a
documented REST surface next to the device PATCH, not UI glue.

**Rewrites** — `e2e/test_session_finish_e2e.py`, `e2e/test_session_reset_e2e.py`,
plus touch-ups in `e2e/test_control_sizing_e2e.py`, `tests/test_components.py`,
`tests/test_rendered_pages.py`.

Consequence for #486: the acceptance criterion "server-rendered and
client-rebuilt content are byte-identical" is satisfied by construction — no
client rebuild exists. The issue should be updated to say so.

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

## Untouched, canonical

Database values, `GeneratedField` computation, all filtering and sorting
(DB-side), the `duration_manual` form input (`HH:MM:SS`), the API's
`duration_manual_seconds` integer, and the `playtime_hours` /
`duration_total_hours` filter facets. None of these are presentation.

## Testing

- Table-driven unit tests over the rendering rules above — every profile against
  zero, sub-minute, sub-hour, hour-plus, 24-hour-plus, week-plus, and year-plus,
  plus the carry boundaries (`1 h 59 m 45 s`, `6 d 23 h 40 m`, `29 m 30 s`).
- Locale tests asserting grouping and decimal separator under `cs` and `en-us`.
- Popover dedup: two lines below 24 h, three above; no line equal to the visible
  value.
- Registry tests: unregistered profile ID rejected; clearing the user value
  restores the site default; live-save and source metadata behave like
  `DATETIME_FORMAT`.
- Rendered-page assertions on the audited surfaces.
- One e2e pass changing the preference and confirming a session list re-renders.

## Follow-up issues to file

- Retire the finish/reset row swap (the prerequisite above) — its own issue,
  referenced from #486.
- Update #486's acceptance criteria to drop the TypeScript-parity clause once
  the prerequisite lands.

## Out of scope

Calendar date, clock time, datetime, timezone, and formatting-locale behaviour
(#388, #389, #473). Changing stored duration precision or calculation semantics.
A days-based option for the non-`adaptive` profiles.
