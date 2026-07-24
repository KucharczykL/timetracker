# Temporal Session-Row Parity Implementation Plan

**Goal:** After a session PATCH, rebuild changed cells with the exact date/time presentation Django used for the initial row, even when the browser and server use different timezones.

**Architecture:** Maintain a bounded v1 presentation contract. It contains date-part order and punctuation, independent input and display-width semantics, clock cycle, and Django-owned AM/PM text. The browser reads and validates it once, converts instants with native Temporal, gets numeric fields with Intl.DateTimeFormat.formatToParts(), and assembles only those supported pieces. If configuration or a timestamp is bad, no text is replaced, preserving the cloned server cells.

**Tech stack:** Native Temporal (Chrome 144+, Firefox 139+, Node 26), Intl, TypeScript 7, Vitest 4/jsdom, Playwright, Django.

## Decisions locked in

- Correct the schema in contract **version 1**. This is development work; do not introduce a v2 merely to retain an ambiguous pre-release shape.
- Do not create strftime or a general pattern language. The grammar stays bounded: day/month/year once each, their order and separators, h12/h23, numeric display padding, and server-supplied AM/PM text.
- Replace overloaded `DatePartSpec.length` with two values:

      DatePartSpec(
          name: DatePartName,
          placeholder: str,
          input_length: int,
          display_min_digits: int,
      )

  `input_length` controls only the date-picker segment maxlength and visual width. `display_min_digits` controls only zero-padding in visible dates. It is a minimum, not truncation: year 2026 remains 2026 if its minimum is 2.
- Add root `day_periods: { am: string, pm: string }`. Django derives these strings for the configured locale and uses the same helper when rendering h12 time. The browser selects AM or PM using `Temporal.PlainDateTime.hour` and must not take a browser Intl day-period word.
- Target Chrome and Firefox only. Do not add a Temporal polyfill or Safari fallback.
- Preserve API JSON fields and ISO timestamp shapes.

## Global guardrails

- Run repository commands through `direnv exec .`.
- Before implementation, prove that the active environment is Node 26 with native Temporal:

      direnv exec . node -e 'console.log(process.version, typeof Temporal?.Instant)'

  If it reports Node 24 or `undefined`, reload/rebuild the local direnv environment before diagnosing formatter failures.
- Add `ESNext.Intl` and `ESNext.Temporal` to TypeScript libraries.
- Accept only `version === 1` and never choose a client-side fallback profile.
- Use `calendar: "iso8601"` and `numberingSystem: "latn"` for numeric browser output, matching Django's Gregorian ASCII digits.
- Report an absent/malformed root contract once via `reportClientError(..., { toast: false })` and return `null`.
- Validate every field. `display_min_digits` is an integer in 1..21, the range `Intl.NumberFormat` accepts; 22 invalidates the contract instead of crashing a session action.
- Finish with `direnv exec . make check` and `git diff --check`.

---

### Task 1: Make the server v1 contract unambiguous

**Files:**

- Modify: `common/date_time_presentation.py`
- Modify: `common/components/date_range_picker.py`
- Modify: `tests/test_date_time_presentation.py`
- Modify: `tests/test_date_range_picker.py`
- Modify: `tests/test_session_formatting.py`
- Regenerate: `ts/generated/date-time-presentation.ts` with `make gen-element-types`

- [ ] **Step 1: Write server regression tests first**

Migrate every `DatePartSpec` fixture to pass both widths. Add assertions that:

1. default day/month/year config emits input widths 2/2/4 and display minimum digits 2/2/4;
2. a custom profile can retain day/month `input_length=2` but use display minimum 1, rendering `2/7/2026` rather than `02/07/2026`;
3. DateRangePicker maxlength and segment sizing use `input_length`, not `display_min_digits`;
4. an h12 server time ends in the exact `day_periods["pm"]` emitted by `to_client_config()`, including for a non-English locale; and
5. generated TypeScript contains `input_length`, `display_min_digits`, and root `day_periods`.

Run:

      direnv exec . uv run --frozen pytest \
        tests/test_date_time_presentation.py \
        tests/test_date_range_picker.py \
        tests/test_session_formatting.py -v

Expected: failures against the old `length` schema.

- [ ] **Step 2: Separate input and display in Python**

1. Rename `DatePartSpec.length` and `DatePartConfig.length` to `input_length`; add `display_min_digits`. Migrate every constructor so no positional call silently retains old semantics.
2. Use current defaults: day (2, 2), month (2, 2), year (4, 4).
3. Render numeric date parts through a helper that pads to `display_min_digits` and never truncates.
4. Add `DayPeriodsConfig` and a cached locale helper that gets Django AM/PM text through `date_format` inside `translation.override(locale)`.
5. Make `_format_time()` use that helper for h12 and emit the exact same `{am, pm}` from `to_client_config()`.
6. In `common/components/date_range_picker.py`, change all `part.length` reads to `part.input_length`. Default markup must not change.

- [ ] **Step 3: Regenerate and verify**

      direnv exec . make gen-element-types
      direnv exec . uv run --frozen pytest \
        tests/test_date_time_presentation.py \
        tests/test_date_range_picker.py \
        tests/test_session_formatting.py -v

- [ ] **Step 4: Commit**

      git add common/date_time_presentation.py common/components/date_range_picker.py \
        tests/test_date_time_presentation.py tests/test_date_range_picker.py \
        tests/test_session_formatting.py ts/generated/date-time-presentation.ts
      git commit -m "feat: clarify date-time presentation contract"

### Task 2: Add the contract-driven native Temporal formatter

**Files:**

- Modify: `tsconfig.json`
- Create: `ts/date-time-presentation.ts`
- Create: `ts/date-time-presentation.test.ts`
- Read only: `ts/generated/date-time-presentation.ts` and `ts/client-errors.ts`

**Public boundary:**

    formatSessionTimeRange(startISO: string, endISO: string | null): string | null

`null` means “retain the cloned server time cell.”

- [ ] **Step 1: Add failing formatter tests**

Make a jsdom test with a hoisted `reportClientError` mock and dynamic import after `vi.resetModules()`, isolating the one-time cache. Its valid fixture includes:

    {
      version: 1,
      locale: "en-US",
      time_zone: "Europe/Prague",
      day_periods: { am: "AM", pm: "PM" },
      profile: {
        date_parts: [
          { name: "day", placeholder: "DD", input_length: 2, display_min_digits: 2 },
          { name: "month", placeholder: "MM", input_length: 2, display_min_digits: 2 },
          { name: "year", placeholder: "YYYY", input_length: 4, display_min_digits: 4 },
        ],
        date_separator: "/", segmented_date_separator: "-",
        time_separator: ":", date_time_separator: " ", hour_cycle: "h23",
      },
    }

Cover:

1. default finished range gives `02/07/2026 19:05 — 21:15`;
2. UTC 2026-01-01 23:30 becomes 2 January in Pacific/Kiritimati before date parts are extracted;
3. non-default order, punctuation, and display minimum 1 work independently of input width;
4. h12 uses deliberate non-Intl labels such as `{am: "before", pm: "after"}`, proving it ignores browser `dayPeriod`;
5. absent config, invalid JSON, v2, non-record profile, duplicate/missing parts, non-string separators, bad hour cycle, bad locale/timezone, input width 0, and display widths 0/22 each return `null` and report the contract error once across two calls; and
6. a malformed API timestamp returns `null` without throwing.

      direnv exec . pnpm test:ts -- ts/date-time-presentation.test.ts

Expected: fail before implementation.

- [ ] **Step 2: Implement parser, validation, and formatter**

1. Add `ESNext.Intl` and `ESNext.Temporal` to `tsconfig.json`.
2. On first call, read `html[data-date-time-presentation]`, parse unknown JSON, validate it, then cache compiled state or `null`. A validation failure reports one silent `date-time-presentation` error.
3. Validate version; nonempty locale/timezone strings; string AM/PM labels; plain-object profile; one each day/month/year; string placeholders; positive integral input widths; display widths in 1..21; four string separators (empty remains valid); and h12/h23.
4. Construct `Intl.DateTimeFormat` and width-keyed `Intl.NumberFormat` while validating. Use ISO calendar, Latin numbering, no grouping, and `minimumIntegerDigits`. This construction validates the locale and IANA zone.
5. Convert each ISO with `Temporal.Instant.from(iso).toZonedDateTimeISO(timeZone).toPlainDateTime()`. Feed the plain value to `formatToParts()`; use numeric day/month/year/hour/minute parts only; then assemble the contract's order and punctuation. Never use browser `Date` getters or a hand-written padding helper.
6. For h12 append one ordinary space plus AM when hour is under 12, otherwise PM. Ignore Intl's `dayPeriod`.
7. Catch formatting errors, report them silently, and return `null`.

- [ ] **Step 3: Verify and commit**

      direnv exec . pnpm test:ts -- ts/date-time-presentation.test.ts
      direnv exec . make ts-check
      git add tsconfig.json ts/date-time-presentation.ts ts/date-time-presentation.test.ts
      git commit -m "feat: add client date-time presentation formatter"

### Task 3: Delegate the session row and protect both fallbacks

**Files:** modify `ts/session-row.ts`; create `ts/session-row.test.ts`.

- [ ] **Step 1: Add row tests**

Mock `formatSessionTimeRange` in a jsdom test. Start from a cloned row holding server-rendered time and duration. Assert a normal result replaces time, calculates duration, and keeps finish/reset cleanup. Assert `null` keeps old time while valid duration updates. Add an invalid timestamp case that preserves **both** old cells and does not throw; action cleanup remains independent.

      direnv exec . pnpm test:ts -- ts/session-row.test.ts

- [ ] **Step 2: Replace browser-local rendering**

1. Import and call `formatSessionTimeRange()` once.
2. Delete `pad2`, `formatTimeRange`, its browser-timezone caveat, and all browser Date getters.
3. Write time only for a non-null formatter result.
4. Calculate duration with `Temporal.Instant` epoch milliseconds inside a try block. Make `formatDurationWithMark()` return `string | null` on invalid timestamps and write duration only when it returns text.
5. Preserve row cloning, manual-duration marks, and action cleanup.

This prevents a successful PATCH from appearing failed because post-response local formatting threw.

- [ ] **Step 3: Verify and commit**

      direnv exec . pnpm test:ts -- ts/session-row.test.ts
      direnv exec . make test-ts
      git add ts/session-row.ts ts/session-row.test.ts
      git commit -m "feat: format rebuilt session rows from presentation contract"

### Task 4: Prove timezone parity in Playwright

**File:** `e2e/test_session_finish_e2e.py`

- [ ] **Step 1: Add a cross-timezone finish regression**

Use `@override_settings(TIME_ZONE="Europe/Prague")` with a new context whose `timezone_id` is `Pacific/Honolulu`. Log in there, create a session beginning at 2026-01-01 00:30 UTC, and load the list.

Assert the browser reports Honolulu. Capture the initial server time cell (default profile: `01/01/2026 01:30`), click Finish inside `page.expect_response(...)`, assert status 200, wait for the finish button to disappear, then compare the substring before ` — ` byte-for-byte with the captured start. Close the custom context in `finally`.

      direnv exec . uv run --frozen pytest \
        e2e/test_session_finish_e2e.py::test_finish_preserves_server_rendered_start_across_browser_timezone -v

- [ ] **Step 2: Complete verification and commit**

      direnv exec . uv run --frozen pytest e2e/test_session_finish_e2e.py -v
      direnv exec . make check
      git diff --check
      git add e2e/test_session_finish_e2e.py
      git commit -m "test: cover session row timezone parity"

## Completion criteria

- Django, generated TypeScript, and client validation share the clarified v1 contract; generated code is never hand-edited.
- A completed row matches the initial server presentation across the intentionally different browser zone, including Django's exact AM/PM text.
- Invalid contract data reports once and preserves server time. Invalid API timestamps preserve server time and duration instead of making the session action appear to fail.
- No pattern parser, polyfill, browser-local Date formatter, or API schema change is added.
