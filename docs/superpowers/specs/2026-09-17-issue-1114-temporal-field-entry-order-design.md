# A temporal date is typed in the order it is shown

Issue: [#1114](https://github.com/KucharczykL/timetracker/issues/1114).
Element: [Expand date entry inline in the browser](2026-08-30-issue-965-temporal-field-element-design.md).
Grammar: [Temporal](../../temporal.md).

## Purpose

`<temporal-field>` shows its three date segments in the order the account's
profile states: year first under ISO 8601, day first under DD/MM/YYYY, month
first under MM/DD/YYYY. A person types them left to right. The element keeps
every typed part, in any order, and never clears one on its own.

## The rule that moves

Precision is derived from which parts are filled. That does not change.

What changes is where a hole is refused. A hole is a filled part with an empty
coarser part beside it: a day with no month, a month with no year. The element
used to clear the finer part on the keystroke that left the hole. Under a
day-first or month-first profile that is the keystroke that typed it, so the
part could never be typed at all.

The element no longer enforces growth. The server already refuses a hole with
a sentence, `_refuse_disagreement` in `timetracker/temporal.py`: "A day needs a
year and a month beside it." and "A month needs a year beside it." A hole
still there at submit meets that sentence, and the refused draft re-renders
the parts a person typed beside it.

## What the element does with a hole

- The segments keep every buffer.
- The named inputs carry every part as typed. `writeNamedParts` already does.
- The `kind` input reads `date` once the start would post any part, not once
  the coarsest prefix is whole. A start holding only a day therefore posts
  `kind=date`, and the server answers with the hole sentence rather than
  "Pick a shape for the date you typed, or clear it." While the whole-decade
  box is checked only the year counts, because that is all the endpoint
  posts; a hidden month or day buffer does not make a `date`.
- The live region names the hole: "Day needs a year and a month", "Day needs a
  year", "Day needs a month", "Month needs a year". Without a hole it states
  the precision as before. A range composes the two endpoint sentences as it
  does today, so "Range, day needs a month to year precision" is a legal
  reading. The region names the coarser hole only; the server's sentence
  names both parts whenever a day lacks either.
- A refused re-render whose end holds only a part now shows the end group,
  because the stored-shape read uses the same "would post any part" rule. It
  used to hide that group and resubmit the invisible part.

## The scratch codec

The shared engine in `ts/elements/date-field-core.ts` calls `onCommit` only
when the codec's value changed. The temporal codec encoded the coarsest
prefix, so a day typed before its year changed nothing, and the element ran a
`keyup` hook to commit anyway. That hook exists for the growth rule alone.

The codec now encodes every part: `year-month-day` with empty parts left
blank, so `2024--01` is a year and a day, and `""` is nothing typed. The value
is never posted. Any buffer change changes it, so `onCommit` fires by itself,
and the `keyup` hook goes.

## Clearing a coarser part

Clearing the year leaves the month and day standing. The live region says
what is missing, and the server refuses the hole at submit. The element does
not guess which part the person meant to keep.

The whole-decade box is unchanged: it hides the month and day cells and posts
neither, because a decade states no month. The hidden buffers stay. They come
back when the box is unchecked, and a hole among them is refused then, at
submit, like any other.

## Tests

The vitest fixture renders the segments in a stated order and every case that
types a date runs under each of the three profile orders. The growth case
becomes its opposite: a day typed before its year stays, the named day input
carries it, `kind` reads `date`, and the live region names the hole. The e2e
harness renders one day-first profile beside the default and types a whole
date from the day segment.

A form test posts a day with no year under `kind=date` and asserts the
sentence and the re-rendered day segment.

## Boundary

No grammar change, no server change, no stored shape change. The session
form's `date-time-field`, `date-picker` and `date-range-picker` already accept
every order and are not touched.
