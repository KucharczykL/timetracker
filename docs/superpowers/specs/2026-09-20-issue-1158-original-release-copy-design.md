# Copy the Original release date into a Release row

Issue: [#1158](https://github.com/KucharczykL/timetracker/issues/1158).

The Game form states a date two times. "Original release" is the day the
game first came out. Each Release row is the day that edition came out on
that platform. For most games the two agree.

## The rule

Each Release row has a **Use original release** button. The button puts the
Original release value into that row. The copy goes in one direction. The
copy always replaces what the row holds. The button changes only the row
that holds it.

A button is correct here, and a mirror is not. An original release is not a
derivation of the release in hand. A person who owns a 2019 port of a 1997
game states two different days on purpose.

## The field owns the copy

`<temporal-field>` renders the button and connects it. `<date-time-field>`
already answers the same question the same way.

`TemporalCopySource` states the source name and the button text.
`ReleaseRowForm` names one source: `original_release_date`. That name
carries no form prefix. Thus one page holds one source, and
`temporal-field[field-name="original_release_date"]` finds it.

A cloned row needs no more work. Its own element connects when it arrives.

## A copy is a draft read and a draft adopted

The thirteen posted inputs are the value. `readDraft()` reads them.
`adoptDraft()` applies them. `copyTemporalDraft()` does both.

`initField()` also adopts. Thus one function sets the state on a page load
and on a copy. Every page load exercises the code that a copy uses.

From the draft, `adoptDraft()` derives the open start, the segment buffers,
the qualifier boxes, the whole-decade boxes and the end shape. It then
opens the disclosure if `canCollapse()` is false.

Three facts make the draft the correct unit. The whole-decade box is
nameless, and the draft states it as `{endpoint}_decade`. The end shape
comes from the kind, not from the radio. The disclosure opens when the
collapsed field cannot state the value.

## The element announces its commits

Typing in a segment fires no native event. The engine takes the keystroke
and writes the buffer. Thus `commitEndpoint()` dispatches
`temporal-field:change`. The button listens on the source and sets its own
enabled state.

## The three inert states

The server renders the button hidden and disabled. The element shows it on
connect.

While the source states nothing, the button stays disabled. Its title says
to fill Original release first.

`TemporalField()` renders no `<temporal-field>` when a part holds more
characters than a segment. The button then finds no source and stays
disabled.

## Tests

`ts/elements/temporal-field.test.ts` proves that a field adopts its own
draft with no change, for every stored shape. It then copies each shape.

`tests/test_game_form_page.py` proves the button in each live row and in
the template.

`e2e/test_game_form_catalog_e2e.py` presses the button on a cloned row.
It also proves that the button becomes enabled with no reload. Only that
test proves the commit event.
