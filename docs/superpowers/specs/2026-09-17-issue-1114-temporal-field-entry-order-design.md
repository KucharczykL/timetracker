# A temporal date is typed in the order it is shown

Issue: [#1114](https://github.com/KucharczykL/timetracker/issues/1114).
Element: [Expand date entry inline in the browser](2026-08-30-issue-965-temporal-field-element-design.md).
Grammar: [Temporal](../../temporal.md).

## Rule

`<temporal-field>` shows three date segments in the order the account profile
states. A person types them from left to right. The element keeps each typed
part and clears no part in answer to a keystroke.

A hole is a filled part with an empty coarser part beside it. The element
names a hole. The server refuses it at submit, and the refused draft shows
the typed parts again beside the sentence.

The element enforces no growth rule. Such a rule clears a finer part while a
coarser part is empty. Under a day-first profile that is the keystroke that
typed the day, so the day cannot be typed at all.

## What the element does with a hole

- Each segment keeps its buffer, and each named input carries it as typed.
- `kind` reads `date` when the start holds a part and the end holds none, so
  the server answers with the hole sentence rather than asking for a shape.
- The live region names the hole, one sentence per missing part. The server
  names the same hole. Neither half asks for a part that is filled.
- A refused draft whose end holds one part shows the end group.

## The scratch codec

The shared engine calls `onCommit` only when the codec value changes. The
temporal codec therefore encodes each part, filled or not: `2024--01` is a
year and a day. The value is never posted, and the element needs no keyup
hook.

The value must mirror the buffers after each commit. A buffer written outside
the engine leaves it stale, and the next keystroke that lands back on the
stale value commits nothing. The server renders the input empty beside filled
segments, and the decade snap and its restore rewrite the year. Each commit
therefore re-encodes each endpoint, and the element seeds the value once it
binds.

## The whole decade

The box hides the month and day cells and posts neither. The hidden buffers
stay, and show again when the box is unchecked, which gives back the year the
snap took and never a year typed since. A year of fewer than four digits
posts as typed, so the server refuses it rather than storing an unknown date
without a word.

## Types

`PartValues` is keyed by the contract's segment names, so a misspelt part is
a compile error. `Hole` names the holes the server refuses, and one table
renders them.

## Tests

vitest types a date under the three profile orders, and covers a day typed
before its year, each hole, a cleared stored year, a retype after the snap,
and the codec giving each buffer state its own value. A form test states each
hole's sentence. An e2e harness types a date from the day segment, and a hole
answered by its own sentence.

## Boundary

No grammar change. No stored shape change. The server's day sentence splits
in three, one per hole, and no code changes with it. The session form's date
fields accept each order and are not touched.
