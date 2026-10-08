# Duration filters compare the stored duration exactly

Issue: KucharczykL/timetracker#1583.

## Contract

A duration filter compares the stored duration exactly. The value is a
decimal number of hours: `1.5` is 90 minutes. No modifier rounds, and no
modifier reads an hour bucket. The display profile has no effect.

- `is 0` selects exactly zero, or no play. A running session is 0 h until
  it ends.
- `is 1` selects exactly one hour. A 59 m 58 s session does not match.
- `is 1` and `≤ 1` agree at the boundary.
- `is not`, `<`, `>`, `≥`, `between` and `not between` compare the same
  number.

No play is 0 h on every duration field. A game with no sessions has a
session playtime of 0 h and a session average of 0 h. On the field's own
model, `x` and `is not x` split a scope into two complete sets. Through a
relation sub-filter, a game with no related rows matches neither, as for
every field.

Duration fields offer no presence pair. "None" is `is 0`. "Any" is `> 0`.
A stored presence modifier on a duration field is a `FilterError`.

A value that a `timedelta` cannot hold is a `FilterError`. A non-finite
number is a `FilterError` on every float field.

## Fields

| field | filter | source |
|---|---|---|
| `playtime_hours` | `GameFilter` | `playtime` alias |
| `duration_hours` | `PlayerSessionFilter` | `effective_duration` |
| `duration_hours` | `HistoricalPlaytimeFilter` | `duration` |
| `session_average` | `GameFilter` | `avg` aggregate |
| `session_playtime_hours` | `GameFilter` | `sum` aggregate |

## Rules in the code

- `duration_hours_to_q` in `common/criteria.py` compiles every duration
  comparison. It has no presence arm.
- `aggregate_to_q` wraps an aggregate whose spec states
  `unit == DURATION_HOURS` in `Coalesce(..., timedelta(0))`. A
  non-duration sum keeps NULL: `purchase_price_total` over no purchases is
  not free.
- `field_metadata` states an aggregate nullable only for `sum` or `avg`
  without a unit.
- The three handler fields take `FloatCriterion`. Its coercer keeps an
  integral value as `int` and refuses a non-finite value.
- `NumberFilter` labels every field with `NUMBER_MODIFIER_LABELS`. A
  duration `unit` removes the presence pair from the fallback list and
  sets `step="any"`, so the input accepts a decimal.
- The unit stays on `FilterField` and `FieldMeta`. `field_comparisons`
  compares two columns raw and does not read the unit.
- `review_filter()` states `duration_hours ≥ REVIEW_THRESHOLD_HOURS`.
  `reviewable_sessions()` compares the same column raw, so the link and
  the count agree.
