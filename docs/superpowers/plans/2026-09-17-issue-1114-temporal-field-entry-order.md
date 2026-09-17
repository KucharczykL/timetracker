# A temporal date is typed in the order it is shown — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (inline) or superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `<temporal-field>` keeps every typed part in any order. A hole (a
day with no month, a month with no year) is named by the live region and
refused by the server at submit, never cleared by the element.

**Architecture:** The temporal scratch codec encodes every part, so the shared
engine's own change detection drives every commit and the `keyup` hook goes.
`enforceGrowth` goes. `currentKind` reads "any part filled". The live region
names the hole. Tests render every profile order.

**Tech Stack:** TypeScript custom element, vitest (jsdom), Playwright e2e,
Django form tests.

**Spec:** `docs/superpowers/specs/2026-09-17-issue-1114-temporal-field-entry-order-design.md`

## Global Constraints

- **Drive everything through `make`.** `make test-ts`, `make test ARGS="…"`,
  `make test-e2e`. Run `make ts` after editing any `.ts` so e2e sees fresh
  output. Never run e2e while `make dev` is up.
- **Wrap every pytest run** in `flock /home/lukas/git/timetracker/.cache/heavy-tests.lock make …`.
- **The verification gate is the full `make check`**, `e2e/` included.
- **Full words in identifiers.** **Refused words** (`make vale`) apply to
  comments and docs; the list is in `docs/vocabulary.md`.
- **Comments state present design**, no issue references.
- **Rebase onto `origin/main` before the first edit.**

---

## File Structure

**Modified**

| Path | Change |
|---|---|
| `ts/elements/temporal-codec.ts` | `temporalCodec.encode` joins every part, blank or not; `coarsestPrefix` goes if nothing else reads it |
| `ts/elements/temporal-field.ts` | Remove `enforceGrowth` and the `keyup` hook; `endpointHasValue` reads any filled part; `endpointSentence` names a hole |
| `ts/elements/temporal-codec.test.ts` | Encoding of partial and hole-bearing values |
| `ts/elements/temporal-field.test.ts` | Fixture takes a part order; date-typing cases run under all three orders; growth case inverted; hole sentence; `kind` under a hole |
| `e2e/test_temporal_field_e2e.py` | Harness renders `dmy_24h` at a second path; one test types a whole date from the day segment |
| `tests/test_temporal_form_field.py` | A posted day with no year under `kind=date` is refused with the sentence and re-renders the day segment |
| `docs/superpowers/specs/2026-08-30-issue-965-temporal-field-element-design.md` | "How the field grows": replace the clearing sentence with a pointer to the new spec |
| `docs/temporal.md` | One sentence: a hole is refused at submit, not cleared while typing |

---

## Task 1: The codec encodes every part

- [ ] `temporal-codec.test.ts`: `encode({year:"2024", month:"", day:"01"})` is
  `"2024--01"`; `encode({year:"", month:"12", day:"01"})` is `"-12-01"`; all
  blank is `""`; `decode` of each round-trips. Existing prefix cases keep
  passing (`"2024"` is now `"2024--"`; update them).
- [ ] `temporal-codec.ts`: encode `${year}-${month}-${day}`, `""` when all
  three are blank. `decode` already splits on `-`. Remove `coarsestPrefix`
  once Task 2 stops importing it, and its `describe("coarsestPrefix")` block
  in `temporal-codec.test.ts`.
- [ ] `date-field-core.ts`, the `FieldCodec.encode` doc: it says `""` when the
  field is incomplete, which the temporal codec never honoured. Say instead
  that a codec decides what an incomplete field encodes.
- [ ] `make test-ts` green.

## Task 2: The element keeps every part

- [ ] `temporal-field.test.ts`: `endpointMarkup` takes `order: readonly
  string[]` (default ISO); the order drives both the cell sequence and the
  `index > 0` prefix span. The existing `type()` helper dispatches every digit
  to the one segment it focused, so add `typeFrom(host, endpoint, digits)`
  that focuses the endpoint's first segment and dispatches each digit to
  `document.activeElement`, so auto-advance carries focus (jsdom has no
  presentation contract; `segmentSpec` falls back to per-name bounds, under
  which `0`,`1` completes a day and `1`,`2` a month). Add `describe.each`
  over `["year","month","day"]`, `["day","month","year"]`,
  `["month","day","year"]` for: "writes a whole typed day" through
  `typeFrom` with the digits in that order, "writes a typed year". Replace
  "clears a part no coarser part can carry" with:
  - "keeps a day typed before its year": under day-first order type `22`
    into day; segment shows `22`, `start_day` is `22`, `kind` is `date`.
  - "names the hole": live region reads "Day needs a year and a month";
    after typing the year, "Day needs a month"; after the month, "Day
    precision".
  - "leaves finer parts when a coarser one is cleared": Backspace on the year
    keeps month and day; region names the hole.
  - "a hidden buffer states no date under a decade": under day-first order
    type `22` into day, check `whole_decade_start`; `kind` is `unknown` and
    `start_day` is `""`. Uncheck; `kind` is `date` and the region names the
    hole.
- [ ] `temporal-field.ts`: remove `enforceGrowth` and the `keyup` listener.
  `endpointHasValue` returns what `writeNamedParts` would post: the year is
  non-empty while the whole-decade box is checked, else any of year, month,
  day is non-empty. `endpointSentence` checks holes first, then precision.
  Keep `decadeStart`.
- [ ] The `type()` helper may keep dispatching `keyup`; nothing listens.
- [ ] `make test-ts` green, `make ts-check` green.

## Task 3: A refused hole re-renders

- [ ] `tests/test_temporal_form_field.py`: post `kind=date`, `start_day=22`,
  no year or month; the form is invalid with "A day needs a year and a month
  beside it." and the rendered day segment carries `22`. Copy the shape of
  `test_a_refused_submission_re_renders_what_was_typed`. Assert on the
  segment input, not the native one: `date_segment_input` emits `value="22"`
  right before `data-date-part="day" data-date-side="start"`.
- [ ] Expect no production change; if the segment does not carry the part,
  the widget's refused-draft path is the defect, not the test.
- [ ] `flock … make test ARGS="tests/test_temporal_form_field.py"` green.

## Task 4: The browser proves day-first entry

- [ ] `e2e/test_temporal_field_e2e.py`: `_presentation(profile_id)` reads
  `date_time_format_profile(profile_id)` from
  `common/date_time_presentation.py`; a second form class and view at
  `test-temporal-dmy/`. Test: click the day segment, type `01122024`,
  submit, stored is `2024-12-01`. The page's `<html
  data-date-time-presentation>` still states the anonymous request's ISO
  profile, which is harmless: `segmentRules` is per name, paste order comes
  from the DOM, and nothing reads the contract's segment order.
- [ ] `make ts`, then `flock … make test-e2e ARGS="-k temporal"` (ARGS does
  not scope e2e; the whole `e2e/` runs — accept it).

## Task 5: Docs

- [ ] #965 spec, "How the field grows": "A person types a year, then a month,
  then a day, in one box" becomes "A person types the three parts in the
  order the profile shows them, in one box"; replace "Clearing a coarser part
  clears every finer part, because `1984--12` states no month." with "A hole
  is named by the live region and refused by the server at submit; see
  [the entry-order spec](2026-09-17-issue-1114-temporal-field-entry-order-design.md)."
- [ ] `docs/temporal.md`, the `<temporal-field>` paragraph: add "A part typed
  before its coarser part stays; the server refuses the hole at submit."
- [ ] `make vale` green.

## Gate

- [ ] `flock /home/lukas/git/timetracker/.cache/heavy-tests.lock make check`
  green, read from a log with its exit code.
- [ ] Commit per task; PR body names #1114 and the spec.
