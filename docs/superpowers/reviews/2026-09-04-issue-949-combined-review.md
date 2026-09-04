# Review: #1008 + #1009 as one change

Four reviewers read `main...claude/midnight-flakes` and
`main...claude/issue-949-preset-display-zone` together: general code, test
coverage, silent failures, comment accuracy. Every load-bearing claim below was
checked against the source; two were wrong and are recorded as downgraded.

**#1009** is the product fix for #949. `todayInPresentationZone()` in
`ts/date-time-presentation.ts` reads the date/time presentation contract and
answers with `Temporal.Now.plainDateISO(zone)`; `todayInDisplayZone()` in
`ts/elements/date-field-core.ts` shapes that into a `Date` and falls back to the
browser's day when the contract is unreadable. Six call sites in
`date-range-picker.ts` and `date-calendar-core.ts`.

**#1008** anchors two clock-bound tests away from midnight.

## Fix before merge

### 1. Merge order is load-bearing

`e2e/test_quick_filter_e2e.py:288` now expects `datetime.now(UTC).date()`. That
is only right once #1009 makes the preset answer in the display zone, whose
default is `UTC` (`timetracker/settings_registry.py:337`). On #1008 alone the
preset still states the browser's day, so a non-UTC machine fails in exactly the
window the branch closes. CI runs UTC and stays green, which is the worst shape
for it.

Merge #1009 first, or land both as one commit.

### 2. Stale comment — `e2e/test_quick_filter_e2e.py:250`

"The preset states the browser's day (#949)" states the defect #1009 removes.
After the merge the preset and the filter answer in one zone: two clocks, not
three. "Noon, so every clock reads one day" is also over-broad — noon UTC is the
next day in UTC+13 and UTC+14, which is the zone the sibling branch's own e2e
uses.

### 3. Dead lint ignore — `pyproject.toml:84`

`date.today()` is gone from `e2e/test_quick_filter_e2e.py`, so its `DTZ011`
per-file ignore no longer applies (verified). `e2e/test_date_range_picker_e2e.py`
still needs its entry, and the shared rationale above both entries still names
the browser's local "today".

### 4. Two of six call sites are revert-proof

Revert `ts/elements/date-calendar-core.ts:66` (`todayView`) and `:258` to
`new Date()` and no test fails. `date-picker.test.ts:17` and
`date-time-field.test.ts:29` both mock `todayInPresentationZone: () => null`, so
they run the fallback, which is the pre-fix behaviour; the one month assertion in
`date-range-picker.test.ts:189` compares against a mocked constant.

The bug this admits: with the display zone a day ahead, an empty date field opens
its calendar on last month and highlights the wrong cell.

Two lines in the static-calendar describe cover both:

```ts
expect(formatCalendarMonthYear).toHaveBeenCalledWith(2027, 2);
expect(
  picker.querySelector('[data-date="2027-03-05"]')!.getAttribute("aria-current"),
).toBe("date");
```

`aria-current="date"` is asserted nowhere in the repo today.

### 5. The new `catch` is untested

`ts/date-time-presentation.test.ts`'s "returns null on a missing contract" counts
a `reportClientError` emitted by `getPresentation()`, not by the new function —
the `!presentation` early return reports nothing. So the only new error handling
in the diff has no test, behind one that reads like its coverage.

The branch may also be unreachable: `compilePresentation` already refuses any
zone `Intl` refuses, so a compiled contract's zone is Intl-valid by construction.
Prove the Temporal/Intl divergence with a case, or take the branch out.

### 6. Docstring compares against something that does not happen

`ts/date-time-presentation.ts:438` says "The sibling above toasts because a click
waits on it". `nowInPresentationZone` toasts only when `timeZoneOverride !==
null` (`:428`), and its own comment says so. The stated reason for `toast: false`
rests on a contrast that does not hold.

"logged" is also loose: the missing-contract path logs nothing here.
`getPresentation()` logs, once, and memoizes `null` after.

## Downgraded — checked against source

**The browser-day fallback is not a live hazard.** It was reported as critical
("a wrong date with no signal"). Both triggers are unreachable on a rendered
page: `common/layout.py:459` stamps `data-date-time-presentation` on `<html>`
unconditionally, and `:549` loads the Temporal polyfill as a classic script ahead
of the deferred modules. The path is defensive.

**The dedup claim is wrong.** `reportClientError` keys on `` `${context}|${detail}` ``
(`ts/client-errors.ts:65`), not on the context alone, so a differing detail is not
swallowed. The conclusion survives by another route: `getPresentation()` caches
`null` and reports only on the first compile failure, so a later preset click
gets a silent `null` and the one log line is attributed to page load.

## Follow-up, not blocking

- `ts/elements/year-picker.ts:50` and `ts/elements/date-field-core.ts:125` still
  read `new Date().getFullYear()`. Same bug class as #949, wrong for hours around
  New Year. Record the verdict in #949 rather than leaving it here.
- `invalidContracts` (`ts/date-time-presentation.test.ts:119`) has no consumer:
  17 malformed-contract cases, orphaned since `f13c9445` took the describe block
  that held them. Pre-existing, own issue. Nothing exercises a present-but-unusable
  contract for any consumer.
- `e2e/test_date_preset_zone_e2e.py` never asserts the browser honoured
  `timezone_id`. One line pins its own premise:
  `page.evaluate("Intl.DateTimeFormat().resolvedOptions().timeZone")`.
- `date-field-core.test.ts:278` asserts `getHours() === 0`. False in browser zones
  that spring forward at 00:00 (Africa/Cairo, America/Santiago, Cuba), where
  `new Date(y, m, d)` answers 01:00.
- `todayInDisplayZone` returns the display zone's calendar day as a
  **browser-local** midnight `Date`. Every caller reads local parts, so it is right
  today; a future caller reaching for `.toISOString()` is off by the zone gap.
- Both new zone tests read the clock twice and race it, the defect class #1008
  exists to remove. The window is seconds a day.

## What holds up

- The 25-hour Kiritimati/Niue pair is the right call, and
  `assert display_today != browser_today` makes the premise self-checking rather
  than asserted in prose. Swept every hour of a year: the two never share a date.
- `e2e/test_date_preset_zone_e2e.py` is the first test anywhere to exercise
  `DISPLAY_TIME_ZONE` → `to_client_config()` → `<html>` → preset → `?filter=` →
  the queried row. It fails on revert.
- `date-range-picker.test.ts:222` tightened from `toMatch(/^\d{4}-\d{2}-\d{2}$/)`
  to `toBe("2027-03-05")`. The old shape regex could never have caught #949.
- `tests/test_library_page_isolation.py:117` is a correct fix, and it pins the
  duration as well as the start — reverting `timestamp_end` to `now` would restore
  the flake.
