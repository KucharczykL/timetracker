# A temporal date is typed in the order it is shown

Issue: [#1114](https://github.com/KucharczykL/timetracker/issues/1114).
Element: [Expand date entry inline in the browser](2026-08-30-issue-965-temporal-field-element-design.md).
Grammar: [Temporal](../../temporal.md).

## Rule

`<temporal-field>` shows three date segments in the order the account profile
states. A person types them from left to right. The element keeps each typed
part. It does not clear a part on its own.

Precision comes from the parts that are filled. A hole is a filled part with
an empty coarser part beside it: a day with no month, or a month with no year.
The element does not refuse a hole. The server refuses it at submit, with the
sentence from `_refuse_disagreement` in `timetracker/temporal.py`. The refused
draft shows the typed parts again, beside the sentence.

## Why the element does not enforce growth

A growth rule clears a finer part when a coarser part is empty. Under a
day-first or month-first profile, the keystroke that types the day is the
keystroke that leaves the hole. A growth rule in the element makes the day
impossible to type.

## What the element does with a hole

- The segments keep each buffer.
- The named inputs carry each part as typed.
- The `kind` input reads `date` when the start would post any part. A start
  with only a day posts `kind=date`, so the server answers with the hole
  sentence and not with "Pick a shape for the date you typed, or clear it."
  When the whole-decade box is checked, only the year counts, because a
  decade posts the year alone.
- The live region names the hole: "Day needs a year and a month", "Day needs
  a year", "Day needs a month", "Month needs a year". Without a hole it states
  the precision. A range composes the two endpoint sentences. The region names
  the coarser hole only; the server sentence names each missing part.
- A refused draft whose end holds one part shows the end group, because the
  stored-shape read uses the same rule.

## The scratch codec

The shared engine in `ts/elements/date-field-core.ts` calls `onCommit` only
when the codec value changes. The temporal codec encodes each part, filled or
not: `year-month-day`, so `2024--01` is a year and a day, and `""` is nothing
typed. The value is not posted. Each buffer change changes it, so the engine
fires each commit. The element has no keyup hook.

## Clearing a coarser part

When the year is cleared, the month and day stay. The live region names the
hole. The server refuses it at submit.

The whole-decade box hides the month and day cells and posts neither. The
hidden buffers stay. They show again when the box is unchecked, and a hole
among them is refused at submit.

## Tests

vitest types a date under the three profile orders and covers a day typed
before its year, the hole sentence, the decade box, and a cleared year. A
form test posts a day alone and asserts the sentence and the re-rendered
segment. An e2e harness types a whole date from the day segment under a
day-first profile.

## Boundary

No grammar change. No server change. No stored shape change. The session
form's date fields accept each order and are not touched.
