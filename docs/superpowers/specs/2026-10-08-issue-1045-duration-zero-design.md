# Duration filters: none and the hour bucket

Issue: KucharczykL/timetracker#1045.

## Contract

A duration filter takes whole hours. The value `h` selects the hour bucket
`[h, h+1)`. `= 0` therefore selects durations from zero to one hour.

The presence pair selects by absence of time:

- `IS_NULL` selects rows with no duration. A row with zero duration matches.
  A game with no row at all matches.
- `NOT_NULL` selects rows with more than zero duration.

The two modifiers partition every scope. A game is in exactly one set.

Duration fields that can have no time offer the pair: `playtime_hours`,
session `duration_hours`, `session_average` and `session_playtime_hours`. The
historical playtime `duration_hours` never offers it, because its rows
always hold a positive duration.

Sub-hour input is out of scope.

## Wire format

The wire format does not change. `EQUALS h` keeps `[h, h+1)`, and `NOT_EQUALS`
keeps its complement. Saved presets keep their meaning. One stored meaning
changes: a stored `IS_NULL` on a session aggregate now also matches games with
no sessions. No migration is needed.

## Presentation

The presence labels read "is 0 (none)" and "is more than 0". The widget and
the builder summary use them. `EQUALS` and `NOT_EQUALS` keep "is" and "is
not".

A duration input shows the hour range under it. Example: "0 h up to 1 h", or
"outside 0 h up to 1 h" for `NOT_EQUALS`. The hint is empty for other
modifiers and for an empty value. The builder summary names the same range.

Every duration label ends in "(hrs)".

## Code

- `duration_hours_to_q` in `common/criteria.py` is the one compile point.
- A duration handler marks its unit. `FilterField.unit` and `FieldMeta.unit`
  read the mark. The key is absent for other fields.
- `FilterField.nullable` states the presence pair on a handler field.
- `bool_nonzero_duration_handler` is removed. It had no caller.
- The Python hint, `duration_bucket_hint`, and the TypeScript hint,
  `durationBucketHint`, follow one table. The contract fixtures check the
  summary.

## Follow-up issues

- KucharczykL/timetracker#1580: widgets rewrite a modifier they do not offer.
- KucharczykL/timetracker#1581: one precision for duration values.
- KucharczykL/timetracker#1582: whether duration sums coalesce to zero.
- KucharczykL/timetracker#1583: whether the bucket confuses ordering modifiers.
- KucharczykL/timetracker#1584: correct the issue restatement.
