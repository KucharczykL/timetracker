# Present a stored date at its own precision

A stored temporal value knows a precision and a qualifier. A reader must see
both. The value has a canonical string, `1984-06~`, which is the storage form
and not a sentence. The value itself renders as its dataclass repr, thus a page
must never place it directly.

`common/temporal_presentation.py` answers words instead. It reads. It writes
nothing, stores nothing, and adds no column.

## Two entry points

`present_temporal_value(value, presentation)` takes a `StoredTemporal` and a
`DateTimePresentation`. It answers text. `StoredTemporal` admits a canonical
string, because the field installs no descriptor and an unsaved assignment
leaves a string on the instance. A string the parser refuses reads `Unknown`; a
read path must not answer a page with a 500. Only a string is forgiven. Another
type raises, because the field types as `Any` and a caller mistake must not read
as a stored fact.

`TemporalText(value, presentation, class_=…)` answers a `Node` that holds the
same words. A page calls the node. A title attribute, a log line, or an API
answer calls the text.

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

The presenter reads `year`, `month`, `day` and `decade_start_year`. Each answers
`None` where the precision knows no such part. That is the guard against a
fabricated exact date: `1984-06` has a lower bound of 1984-06-01, and 1 is not a
stored day. Never build a `date` from a value that knows no day.

## The qualifier is said in words

A symbol is storage. A reader gets words.

| Qualifier | Reads |
| --- | --- |
| Approximate | `around 1984` |
| Uncertain | `1984 (uncertain)` |
| Both | `around 1984 (uncertain)` |

The words carry no markup of their own, thus a screen reader says what a sighted
reader sees. `TemporalText` adds the element and the classes. It adds no second
wording.

## A range says each endpoint

A range presents both endpoints, each at its own precision and with its own
words, joined by an en dash. An open start reads `until <end>`. An open end
reads `since <start>`. An unknown endpoint reads `Unknown`.

A qualifier in a range takes the suffix form, thus `1984~/1986?` reads
`1984 (approximate) – 1986 (uncertain)`. The prefix form is for an atomic value
only: `around 1984 – 1986` reads as one approximate range, which is a different
statement from an approximate start.

The primitive qualifies each endpoint separately. The entry controls of #964
write one pair of qualifiers. The presenter still reads a value that they cannot
write.

## Callers

The Game detail page reads `Game.original_release_date` through the presenter,
in the meta row labelled `Original release`. The value accepts a month, a decade
and a range, thus a label that says "year" is a wrong label.

## Boundary

The presenter adds no entry control; #964 and #965 own entry. It adds no filter;
the wave that writes the temporal filter owns the query string encoding, as
[the qualifier specification](2026-08-30-issue-656-temporal-qualifiers-design.md)
states.
