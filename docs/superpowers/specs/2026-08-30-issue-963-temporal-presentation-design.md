# Present a stored date at its own precision

A stored temporal value knows a precision and a qualifier. A reader must see
both. `str(value)` prints the canonical string, `1984-06~`, which is the storage
form and not a sentence.

The code goes in `common/temporal_presentation.py`, beside
`common/date_time_presentation.py`. The first caller is `games/views/game.py`.

## Two entry points

`present_temporal_value(value, presentation)` takes a `TemporalValue | None` and
a `DateTimePresentation`, and answers text.

`TemporalText(value, presentation)` answers a `Node` that holds the same words.
A page calls the node. A title attribute, a log line, or an API answer calls the
text.

## The precision decides the words

| Precision | Reads |
| --- | --- |
| Day | `DateTimePresentation.format(date, "date")` |
| Month | `DateTimePresentation.format(date, "month_year")` |
| Year | the four digits |
| Decade | `decade_start_year` and `s`, thus `1980s` |
| Unknown value, or `None` | `Unknown` |

A day and a month go through the account profile, because the account owns the
order of the parts. A year and a decade hold one part, thus no profile decides
anything.

Never build a `date` from a value that knows no day. `1984-06` has a lower bound
of 1984-06-01, and 1 is not a stored day. The presenter reads `year`, `month`,
`day` and `decade_start_year`. Each answers `None` where the precision knows no
such part, which is the guard against a fabricated exact date.

## The qualifier is said in words

A symbol is storage. A reader gets words.

| Qualifier | Reads |
| --- | --- |
| Approximate | `around 1984` |
| Uncertain | `1984 (uncertain)` |
| Both | `around 1984 (uncertain)` |

The words carry no markup of their own, thus a screen reader says what a sighted
reader sees. `TemporalText` adds the element and the classes; it adds no second
wording.

## A range says each endpoint

A range presents both endpoints, each at its own precision and with its own
words, joined by an en dash. An open start reads `until <end>`. An open end reads
`since <start>`. An unknown endpoint reads `Unknown`.

The primitive qualifies each endpoint separately, thus `1984/1986~` presents as
two differently qualified endpoints. The entry controls in #964 write one pair of
qualifiers, and the presenter still reads a value that does not.

## Boundary

The presenter reads. It writes nothing, stores nothing, and adds no column.

It adds no entry control; #964 and #965 own entry. It adds no filter; the wave
that writes the temporal filter owns the query string encoding, as
[the qualifier specification](2026-08-30-issue-656-temporal-qualifiers-design.md)
states.
