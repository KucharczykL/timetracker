# Hold a date's dimensions in a form and build one value

`TemporalValue` is frozen and parses from one canonical string. It has no
transformer, thus a form cannot change one part of it. A person who adds a month
to a year needs a mutable carrier.

`TemporalDraft` goes in `timetracker/temporal.py`, beside the value, because it
must know the grammar. The field and the widget go in `games/forms.py`, and the
markup in `common/components/temporal_field.py`.

## The draft

A mutable dataclass. It holds a kind, and for each endpoint a year, a month, a
day, a decade start year, and a qualifier.

`TemporalDraft.from_value(value)` reads a stored value, and `build()` builds one.
`build()` raises `TemporalValueParseError` on a combination the grammar refuses,
and the field turns that into a field error with a sentence.

The kind is one of `Date`, `Range`, `Since`, `Until` and `Unknown`. `Since` opens
the end and `Until` opens the start, thus an open endpoint needs no control of
its own and every storable shape is reachable.

The precision is derived, not stated: a filled day means day, else a filled month
means month, else a filled year means year, else a filled decade means decade,
else the endpoint is unknown. A person thus never picks a precision from a menu.

The draft holds a qualifier for each endpoint. The controls expose one pair for
the whole value and write both endpoints. An asymmetric range stays storable,
readable and presentable, and no control reaches it. A second control set is then
additive.

## The field and the widget

`TemporalFormField(forms.Field)` cleans to `TemporalValue | None`.
`TemporalWidget(forms.Widget)` follows `DatePickerWidget`: it renders a component
in place of a native control, and reads its own inputs from the data dictionary.

One field name yields several inputs. `{name}-kind`, `{name}-year`,
`{name}-month`, `{name}-day`, `{name}-decade`, `{name}-approximate`,
`{name}-uncertain`, and the same part names behind `{name}-end-` for the second
endpoint of a range. `value_from_datadict()` builds the draft, and `clean()`
turns it into the value.

The widget joins the composite list in `apply_primitive_widget_classes()`, beside
`SearchSelectWidget` and `DatePickerWidget`, because it styles itself and must
not take the native control classes.

## Every combination works with no JavaScript

The widget renders native controls: a select for the kind, number inputs for the
parts, and checkboxes for the two qualifiers. A day, a month, a year, a decade, a
range, and an unknown value each round-trip with scripting off.

This is the contract #965 enhances. The element hides controls and binds
segments; it introduces no input the server cannot read.

## Boundary

No custom element; #965 owns the browser. No presenter; #963 owns the words a
reader sees. No model change: `TemporalValueField` already stores the value, and
the generated columns already project it.
