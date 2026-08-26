# Segmented date/time fields — spec, then a phase 0 fix and four phases

## Context

[#511](https://github.com/KucharczykL/timetracker/issues/511) asks for the
account's `DATETIME_FORMAT` preference to reach the last three native controls:
`SessionForm.timestamp_start`/`timestamp_end` and `GameStatusChangeForm.timestamp`.
#485 did this for every `DateField` with a segmented `<date-picker>` and
explicitly deferred these.

Taken literally that's "add a datetime variant". Reviewing the code we decided it
isn't, because three pieces of the existing design are accidental — and a
datetime field is exactly what exposes them:

1. **The presentation profile is asymmetric.** Dates are described structurally
   (an ordered `date_parts` tuple); time is procedural — `_format_time()`
   hard-codes `HH{sep}mm` with the day period always trailing. A datetime widget
   would re-derive the time shape in Python *and* TypeScript, and
   day-period-first locales stay inexpressible. Tell:
   `ts/date-time-presentation.ts:7` already declares
   `NUMERIC_PART_NAMES = ["day","month","year","hour","minute"]`.
2. **`ts/elements/date-field-core.ts` is only half data-driven.** Per-segment
   state lives in the DOM, but "this is a date" is hard-coded in five places —
   including a `partRange` fall-through (lines 71–77) that silently treats any
   unrecognised part as a day (1–31): a live latent bug the moment an hour part
   appears.
3. **The `<noscript>` fallback is a one-off.** One component
   (`common/components/date_picker.py:134`), and the forms it protects already
   require JS (`PurchaseForm.games`, `SessionForm.game` are required
   `SearchSelect`s).

**Deliverable of this session: the design doc and the phase issues, not code.**

**How this lands.** This document is committed to the repo as
`docs/superpowers/plans/2026-07-26-segmented-date-time-fields.md` (the existing
convention, alongside `2026-07-26-table-widths-phase-0.md`), on the current branch
`claude/issue-511-planning-b75979`, and pushed as a draft PR so the work can be
picked up later. Nothing else is changed — no source, no tests. The spec doc under
`docs/superpowers/specs/` and the phase issues are the *next* session's work, done
against this plan.

### This plan was adversarially reviewed

Three reviewers (correctness, scope, UX/accessibility) attacked a prior draft.
What they broke is fixed below; what they confirmed is noted so it isn't
relitigated. Two of my own recommendations were wrong and are reversed — the
tinted sub-groups (contrast) and the crosshair icon.

**Confirmed sound, do not revisit:** `DateTimeField.to_python` calls
`parse_datetime` before any strptime, so an offset-qualified value binds aware and
`from_current_timezone` no-ops on it — **no server-side change needed**
(`forms/fields.py:542-560`, `forms/utils.py:220`); `prepare_value` →
`to_current_timezone` hands the widget naive local (`fields.py:537-540`,
`utils.py:239-246`) unlike `DateField`, which is why `DatePickerWidget._iso_value`
localizes explicitly; the degraded gap path produces the exact pinned error string;
`render()` returns a string so widget Media cannot bubble, making the explicit
`ModuleScript` in `purchase.py` **necessary, not redundant**; Temporal is already
loaded via polyfill, before module scripts (`common/layout.py:650`);
`data-date-field-side` is real and unconsumed; the seconds truncation is real
(`Session.finish_now`, `clone_session_by_id` store microseconds).

The DST matrix was **verified empirically** against the repo's own
`temporal-polyfill.js` under node: `disambiguation: "reject"` throws
`Ambiguous offset` on both the `2026-03-08T02:30` gap and the `2026-11-01T01:30`
ambiguity, while `"earlier"` + round-trip yields exactly the decided behaviour
(gap resolves to 01:30 so the wall clock differs and is detectable; ambiguity
matches at `-04:00`).

### Second verification pass

A later reviewer re-checked every claim against the code. Seven corrections are
merged in below and flagged inline as **[corrected]**; the rest confirmed. The two
substantive ones: phase 2a's "byte-identical markup" and its ARIA work were
contradictory as written, and one quoted contrast figure was attributed to the
wrong token.

**Line numbers in this document drifted by one** relative to `main` after the
branch point. Treat every `file:line` here as approximate and re-locate by
content; the phase issues carry the corrected figures.

---

## Decisions

### Architecture

| Decision | Rationale |
|---|---|
| **Presentation contract → version 2**: one ordered segment list covering date parts, time parts, and day-period placement. **All fields total** — `common/components/ts_codegen.py` has no optional-field support | Kills the structural/procedural asymmetry; one source for server rendering, client formatting, and the widget |
| **One configured element, four configs** (date / time / datetime / range); engine becomes a `SegmentedField` built from an explicit parts config | Composition belongs at the parts-list layer. Deletes the hard-coded part table and its fall-through |
| **Wire value: offset-qualified wall clock** `YYYY-MM-DDTHH:MM:SS.ffffff±HH:MM` | Binds aware with no server change, and keeps *both* the typed wall clock and the chosen offset in the payload — which is what makes the timezone follow-up cheap |
| **DST: resolve with `disambiguation: "earlier"` unconditionally, then round-trip** — if `zdt.toPlainDateTime()` ≠ the typed wall clock it was a gap → submit the bare wall clock and let Django reject | `"reject"` throws on **ambiguity as well as gaps** (`temporal-polyfill.js:762`), so it cannot express the decided matrix. One call + a comparison can: ambiguity resolves to the earlier occurrence with an explicit offset, gaps degrade to today's server rejection and today's message |
| **Residual = seconds *and* microseconds** | `duration_calculated` is a DB `GeneratedField` over the two timestamps, so dropping microseconds still shifts durations by up to a second on every edit — the same bug class the residual exists to close |
| **Bound-form re-hydration is explicit** | On a bound form `BoundField.value()` returns the raw POST string. `DatePickerWidget` gets this free because its wire format *is* its render format; this widget's isn't, so it must re-hydrate segments from **both** the offset-qualified and the degraded naive shapes — otherwise a DST rejection re-renders an empty field and eats the user's input |
| **Drop the `<noscript>` fallback**, from `<date-picker>` too | Single outlier protecting already-JS-required forms |

### Interaction

| Decision | Rationale |
|---|---|
| **AM/PM is an inline segment**, visually like a numeric one (`inputmode="text"`, `--` placeholder) | It behaves like one and native pickers render it this way |
| **Day-period keys come from `day_periods`, not literal `a`/`p`** | Django's `cs` locale renders "dop."/"odp." — both start with neither `a` nor `p` |
| **Ctrl+C copies the whole field value**; **Ctrl+V parses it back** | Replaces the deleted "Toggle text" escape hatch. Intercept Ctrl+C **only when the segment has no text selection**, handle `metaKey`, and give feedback — otherwise it hijacks a universal convention silently |
| **The copy-to-other-field button stays**, as a directional arrow | Ctrl+C/Ctrl+V is keyboard-only: no Ctrl key on a phone, and long-press on a `caret-transparent` segment yields at most one segment. Removing it would delete a pointer- and touch-accessible feature. Direction is derived client-side from document order, not a prop |
| **"Now" is a labelled text button in the calendar footer**, beside Clear | Matches the existing "Today"/"Yesterday" preset vocabulary 24px away. No crosshair, no new icon file, no second cramped 24px target on the field. Costs a click |
| **Calendar stays a popup** | Always-open is ~400px per field; `add_session` has two timestamps, so ~800px before duration/device/note. `date_calendar_shell(static=True)` exists if this is ever revisited for single-timestamp forms |
| **"Set to now" resolves in the account timezone** | Shipped as phase 0 — see below |

### Visual

- **A separator glyph, not tinted sub-groups.** The profile's
  `date_time_separator` renders as a visible `text-body` span between the date
  and time runs — precisely what `DateRangeField` already does with its en-dash
  (`Span(class_="text-body select-none px-0.5")["–"]`).
- **Reversed from the prior draft, with the repo's own gate as evidence.** Running
  `scripts/contrast_audit.py`'s math on the tint I had recommended:
  `bg-neutral-tertiary-medium` on `bg-neutral-secondary-medium` is **1.05:1 in
  light, 1.42:1 in dark**, against the 3:1 a fill boundary needs — that alone
  kills it, in a codebase that advertises "WCAG-AA-clean, programmatically
  verified". `neutral-tertiary-medium` is also the documented *hover* token; using
  it as a resting fill inverts the vocabulary.
- **[corrected]** The prior draft added that the tint pushes `text-body`
  separators and placeholders to **4.39:1 / 3.96:1**, "below AA in both themes".
  Only the dark figure is `text-body` (gray-400 on gray-700 = **3.96:1**, a real
  AA failure). In light, `text-body` on the tint is gray-600 on gray-100 =
  **6.87:1** and passes; **4.39:1 is `text-body-subtle`**, which neither the
  separators (`date_range_picker.py:287`) nor the placeholders (`:57`) use. The
  companion claim that "no palette step reaches 3:1 as a fill boundary in light
  mode" is also false as stated (gray-500 on white is 4.84:1) — no *plausible
  resting tint* does. Do not carry the wrong numbers into the spec doc.
- **One shell, one flat segment run**, the existing `FIELD_CONTAINER_CLASS`, with
  one trailing calendar toggle and the copy arrow.
- **Wrapping, not breakpoints.** `flex-wrap`, continuous. Correct arithmetic at
  1ch = 9.6px: date run 104px + separator + time run 92px + actions 50px + shell
  chrome 30px ≈ **280px**, not the 240px the prior draft claimed (it omitted the
  action cluster). Fits 375/390; wraps at 320px. Do **not** use `flex-1` on the
  runs — on a `max-w-xl` form it stretches them into dead space.
- **Blank-shell mousedown must focus the *nearest* segment**, not the first
  (`date-field-core.ts:282–290`) — on a wrapped field, tapping beside the minutes
  currently teleports focus to the month.

### Accessibility — a required section, not a clause

The prior draft's entire a11y design was "carried by ARIA", with ARIA designed
nowhere. Today's segments are bare `<input aria-label>` with `caret-transparent`
and zeroed focus ring; a datetime field makes that **six** of them, replacing a
native control with full platform semantics. The spec must define, and phase 2a
must implement:

- `role="spinbutton"` with `aria-valuemin`/`valuemax`/`valuenow` per numeric
  segment — a JS write to a focused text input's `.value` is not reliably
  announced, so today's arrow-stepping is silent to a screen reader.
- `aria-valuetext` for the day period, whose role as free-text input is simply
  wrong (it's a two-state toggle) — a 4.1.2 Name/Role/Value failure as specced.
- The segments are already bound into one named field by the server's
  `role="group"` + `aria-label`, pinned at `tests/test_date_picker.py:129`. That
  satisfies 1.3.1; **[corrected]** the prior draft's `aria-labelledby` would swap a
  working attribute for an equivalent one and break the pin for nothing. Keep
  `aria-label` unless a visible label element actually exists to point at.
- **[corrected] ARIA is stamped client-side, in `connectedCallback`** — not
  server-rendered. This is what makes phase 2a's byte-identical-markup contract
  survivable (see that phase), and it is independently right: `aria-valuenow` and
  `aria-valuetext` change on every keystroke, so they are widget state, not
  document structure. The server keeps emitting exactly what it emits today.
- **Touch-target policy, decided and written down.** Segments are 19.2 × 24px.
  **[corrected]** `e2e/test_touch_targets_e2e.py` contains two tests — the
  truncated-text reveal button (`:37-60`) and the calendar toggle plus month nav
  (`:63-93`) — and **never measures a segment**, so the prior draft's "either they
  are exempted or the suite fails" describes a forcing function that does not
  exist. The policy must therefore be *added*: write the WCAG 2.5.8
  spacing-exception rationale down (it does cover the segments at ~32px centres)
  and add the test that asserts it, rather than waiting to be failed into it. The
  trailing buttons must be sized from `ControlButton(variant="ghost")` like the
  calendar nav buttons, not the hand-rolled 24×24 `p-1` pattern that already
  produced one failure in #485.

**Sequencing rule:** the ARIA work lands in phase 2a, *before* phase 2c removes
the last fallback. Do not delete escape hatches while the primary path is unproven.

### Why composition is by parts, not by nesting

Nesting `<date-picker>` + `<time-picker>` breaks four ways: the value doesn't
decompose (Django binds one field under one name, so the parent owns the hidden
input and codec, making the children hollow); the segment run must cross the seam
(auto-advance, arrows, one paste target); the calendar can't live in the date
child because picking a day must preserve the typed time; and `<time-picker>` has
no consumer. The composition axis is the parts list:

```
date field      parts = date_segments(profile)
time field      parts = time_segments(profile)                        ← falls out free, not built
datetime field  parts = date_segments(profile) + time_segments(profile)
range field     parts = date_segments(profile, side="min") + date_segments(profile, side="max")
```

The range case is the proof: `<date-range-picker>`'s "one flat run, hidden-sync
scoped per side" already *is* hand-rolled parts composition.

---

## Deliverable now

1. `docs/superpowers/specs/2026-07-26-segmented-date-time-fields-design.md` — the
   three accidents with evidence, the decisions above, the parts model, the wire
   format and DST rules, the ARIA design, the visual treatment, and the
   approaches ruled out (nested elements; `...Z`; `disambiguation: "reject"`;
   tinted sub-groups, with the contrast numbers; the crosshair icon;
   always-open calendars).
2. Phase issues below, plus the timezone follow-up. #511 is rescoped as phase 3.

---

## Phase 0 — ship the "Set to now" fix now

Independent of everything else, ~10 lines, in the existing element.
`ts/elements/session-timestamp-buttons.ts:28` writes the **browser's** wall clock
into a field the server interprets in the **account** zone, so every click by a
user whose zones differ stores a wrong instant *today*. Compute "now" from the
contract's `time_zone` (already on `<html data-date-time-presentation>`). Fix the
`return`-instead-of-`continue` bug at line 25 in the same PR.

**[corrected]** "~10 lines" undersells it slightly: the element has **no import
statements at all** today, and `ts/date-time-presentation.ts` exports only its
three formatting functions — neither the compiled presentation nor its `timeZone`
is reachable. The fix needs a new export there first (#535 already specifies
`nowInPresentationZone()`), not just an edit in place. Temporal itself is fine —
the polyfill loads before module scripts.

Do not wait for a design doc to fix an active data bug.

## Phase 1 — presentation contract v2

`common/date_time_presentation.py` grows an ordered segment list replacing
`date_parts` + hard-coded `_format_time`; `_format_date`/`_format_time` become
list walks; `to_client_config()` emits `version: 2`. Mirror in
`ts/date-time-presentation.ts`, whose validator asserts `version === 1` and
exactly day/month/year (lines 68, 96–98). Three profiles re-express unchanged;
**no visible output changes** is the phase's own test.

Blast radius — source: `common/date_time_presentation.py`,
`ts/date-time-presentation.ts`, `common/components/date_range_picker.py`. Tests:
`tests/test_date_time_presentation.py`, `ts/date-time-presentation.test.ts`,
`tests/test_session_formatting.py`, `tests/test_date_time_rendering_paths.py`, the
two picker suites, **and three e2e suites the prior draft missed** —
`e2e/test_settings_page_e2e.py:256,268` (asserts `date_parts[0].name` against the
live contract), `e2e/test_date_range_picker_e2e.py:117` (builds a profile
directly), `e2e/test_date_picker_e2e.py:204` (serializes the contract into a
synthetic page).

**[corrected]** Two more: `e2e/test_admin_settings_page_e2e.py:198-200` is a
**fourth** raw reader of `data-date-time-presentation` (it only asserts
`time_zone`, so it should survive v2 — but it belongs on the list), and
`ts/date-time-presentation.test.ts:50` currently asserts that a `{version: 2}`
contract is **rejected**. That case does not get re-pointed, it gets *inverted*.

## Phase 2a — engine parts config, markup byte-identical

Replace `date-field-core.ts`'s free functions + dataset state with a
`SegmentedField` built from an explicit parts config (name, kind, width,
placeholder, side, bounds — note **bounds are profile-dependent**: h12 hour is
1–12, h23 is 0–23). Keep both existing tags and **emit byte-identical markup** —
that is what lets the existing suites pin this phase verbatim, and it is the claim
the prior draft's phase 2 contradicted by smuggling a restyle in.

Land the ARIA design here (spinbutton roles, valuetext, nearest-segment focus).
`date-calendar-core.ts:22` is a **fourth** consumer of the core (`addDays`,
`isoFromDate`) the prior draft missed — keep those helpers exported.

**[corrected] "Byte-identical markup" and "land the ARIA design" contradict each
other unless the split is stated, and the prior draft did not state it.** ARIA
attributes *are* markup, and `tests/test_date_picker.py` pins the server output
exactly (`:91-99`, `:129-132`, `:233-252`). The resolution, per the a11y section:
**the server's markup does not change at all; every ARIA attribute this phase adds
is stamped in `connectedCallback`.** `role="group"`/`aria-label` already exist
server-side and stay as they are. With that split the phase's contract holds
literally — and if a suite still needs editing here, that is the signal that
something non-ARIA leaked in.

**[corrected]** One caveat on "the suites pin this phase": the nearest-segment
focus change is a behaviour change that the suites do *not* actually catch.
`e2e/test_date_range_picker_e2e.py:297-304` pins container-click → first segment,
but it clicks at `(5, 5)`, where nearest *is* first — so it passes by coincidence,
not by proving anything. Add a far-position click case.

## Phase 2b — collapse the elements

One element, proposed tag `<date-time-field>`, configured by its parts list;
introduce the separator-glyph layout and the wrapping behaviour. Python: one
component module replacing `common/components/date_picker.py` and the widget half
of `date_range_picker.py` (calendar shell, class tables, codegen exports stay).
Add Ctrl+C copy (selection-aware, `metaKey`-aware, with feedback).

This is the churn-heavy phase — it rewrites or renames much of #485's
`tests/test_date_picker.py`, `date-picker.test.ts`, and
`e2e/test_date_picker_e2e.py`, including exact-HTML pins at
`tests/test_date_picker.py:233–252`. Budget for rewriting those assertions, not
re-pointing them.

**[corrected] The blast radius above is the date-picker half only — the range
half, which this phase also migrates, reaches the filter tier.**
`common/components/filters.py:412` builds `DateRangePanel`/`DateRangePicker` for
the quick bar and the nested builder, so add: `tests/test_date_range_picker.py`,
`tests/test_field_widget.py`, `tests/test_quick_filter_bar.py`,
`tests/test_node_tree.py`, `e2e/test_date_range_picker_e2e.py`,
`e2e/test_filter_count_e2e.py`, `ts/elements/date-range-picker.test.ts`. Both tags
are also *registered* elements (`common/components/custom_elements.py:216-221` for
`date-range-picker`), so collapsing them means retagging those registrations and
regenerating `ts/generated/props.ts` — unmentioned anywhere in the prior draft.

## Phase 2c — remove the `<noscript>` fallback

Delete the noscript input, its `common/input.css:317–321` rule (**[corrected]**),
and the tests
pinning it. **Answer the pre-upgrade question explicitly**: `date-picker:not(:defined)`
also governs what shows during script load. Removing the rule leaves dead,
focusable segments visible before JS lands; keeping it without the noscript input
leaves the field blank. Pick one and write it down.

## Phase 3 — #511: the datetime fields

- Datetime parts config; `DateTimeFieldWidget` in `games/forms.py` beside the date
  one, added to the self-styled skip tuple in `apply_primitive_widget_classes`;
  bound-form re-hydration from both wire shapes.
- `SessionForm` / `GameStatusChangeForm` take `presentation` and install the
  widget in `__init__`; delete `custom_datetime_widget`. **Four** `SessionForm`
  sites (`games/views/session.py:183,190,201,220` — the POST branch of
  `add_session` is easy to miss) and **both** `GameStatusChangeForm` sites
  (`games/views/statuschange.py:27,39`), each page's `scripts=` gaining the
  element's `ModuleScript`. **[corrected]** line numbers, +1 from the prior draft.
- Wire value, DST round-trip, and the seconds+microseconds residual per the
  decisions table.
- **Extend paste parsing to the datetime shape** — `parsePastedDate`
  (`date-field-core.ts:143–167`) requires exactly 3 all-numeric groups, so it
  rejects everything Ctrl+C produces here. Must handle time parts, seconds, and
  localized day-period tokens. Without this, Ctrl+V silently no-ops.
- Copy-to-other-field button on the two Session timestamps, direction derived
  from document order.
- `_timestamp_buttons()` and `ts/elements/session-timestamp-buttons.ts` deleted,
  their functions absorbed into the field — **[corrected]** together with the
  element *registration* at `common/components/custom_elements.py:190-200`
  (`SessionTimestampButtonsProps` + `register_element` + builder). Deleting only
  the Python helper and the `.ts` leaves a live registration codegenning props for
  a tag nothing renders.

**Test corrections the prior draft got wrong:**
`tests/test_datetime_local_presentation.py` imports `custom_datetime_widget` at
line 9, so deleting it breaks the module *import*; and `SessionForm(data=…)` at
lines 33/53 has no `presentation`. The two timezone **assertions** survive
verbatim; the **file** needs edits. `tests/test_rendered_pages.py:337–350`
(**[corrected]**, +6) dies whole, not by dropping one literal. `e2e/test_widgets_e2e.py:208` and
`e2e/test_settings_page_e2e.py:180` load the add-session page for unrelated
assertions and can be perturbed. `GameStatusChange.timestamp` is nullable —
blank round-trip needs its own cover.

---

## Follow-up to file separately

**Session-local timezone.** `DISPLAY_TIME_ZONE` is one global account setting, so
a session logged abroad re-renders in whatever zone you're in now — the Japan →
Czechia case, where hand-"correcting" the displayed time is what corrupts the
instant. Phase 3's wire format is the enabler: the offset is in the payload and
Django discards it on binding.

- **Storage** — nullable IANA zone id **per timestamp**, not the bare offset (the
  zone derives the offset for any instant, survives DST, renders "JST"). Per
  timestamp because a session can start in one zone and end in another, and the
  two are already captured at different moments — `session-actions.ts` finishes an
  open session separately from when it started. `NULL` = "assume the display
  zone" = today's behaviour, so no backfill. `GameStatusChange` stays out.
- **Capture** — the browser's zone at commit time, editable.
- **Editing** — a "Time zone" disclosure row under the field, composed from
  existing pieces (`ComboboxDropdown(ghost=True, content=SearchSelect(options=…))`,
  the quick-filter facet shape) — **no widget variant needed**. Wants a small
  `/api/timezones/search` endpoint; inlining ~600 zones twice per form is ~35KB.
  Two open details: the server can't know the browser zone at render, so
  "auto-open when zones disagree" is a post-load reveal and therefore a layout
  shift; and per-timestamp storage implies **two** rows on the session form.
- **Display** — a preference, "my current timezone" vs "the session's own"; the
  second **must render the zone label**, or a sorted list lies.
- **Calculation — no change, confirmed.** Durations are instant arithmetic;
  day/week/year bucketing goes through `__date`/`TruncDate`/`localdate()`, which
  Django resolves in the active timezone the middleware sets — already one chosen
  zone.
- **Out of scope** — when *during* a session the boundary was crossed.

Also retarget **#516** at the phase-2b element.

---

## Verification

Each phase green before the next. `make check` is the gate — lint, format-check,
mypy, ts-check, icon drift, vitest, and the whole pytest suite **including
`e2e/`**. Never a subset; `ARGS` is for iterating.

- **Phase 0** — set a `display_time_zone` different from the browser's, click "Set
  to now", confirm the stored instant matches the account wall clock.
- **Phase 1** — proved by *unchanged* output across `test_session_formatting.py`
  and `test_date_time_rendering_paths.py`, plus the three e2e suites above.
- **Phase 2a** — existing picker suites pass **unmodified**; that is the phase's
  contract. Plus a screen-reader pass on the date field before any fallback is
  removed in 2c.
- **Phase 2b** — re-pointed suites, and a touch-target run at 390px (the fixture
  viewport, not 375) with the segment-exemption policy asserted explicitly.
- **Phase 3**, driven via `make dev`:
  - Add Session → one segment run across the date/time separator; the copy button
    fills the other timestamp; Ctrl+C then Ctrl+V round-trips; calendar pick
    preserves the typed time; footer "Now" sets both.
  - Switch to `mdy_12h` (segmented order `MM-DD-YYYY`), reload → month-first plus
    an AM/PM segment; the persisted instant is unchanged.
  - Edit a session with non-zero stored microseconds, save untouched → duration
    unchanged.
  - Submit `2026-03-08T02:30` on `America/New_York` → the existing DST-gap error
    appears **and the typed segments survive the re-render**.
  - Submit `2026-11-01T01:30` on `America/New_York` → accepted, stored at the
    earlier offset.
  - Add **and edit** a status change under `mdy_12h`, including a blank timestamp
    round-trip.
