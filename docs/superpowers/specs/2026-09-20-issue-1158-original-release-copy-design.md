# Copy the Original release date into a Release row

Issue: [#1158](https://github.com/KucharczykL/timetracker/issues/1158).

## Rule

The Game form states a date twice. "Original release" says when the game
first came out anywhere. Each Release row says when that edition came out on
that platform. The two agree for most games a person adds, and the person
types the same day twice.

Every Release row carries a **Use original release** button. It copies the
Original release value into that row's date. It copies in one direction, it
always overwrites, and it acts on the one row that holds it.

## Why a button and not a mirror

`ts/add_game.ts` mirrors the game name into the sort name as a person types.
It mirrored the two year columns once as well, in the other direction, and
dropped that when both dates became `<temporal-field>`.

Two facts keep a mirror out:

- A sort name is a derivation of a name. An original release is not a
  derivation of the release in hand. A person who owns a 2019 port of a 1997
  game states two different days on purpose.
- The mirror stops writing when the person takes the target over. A temporal
  control holds thirteen posted inputs, so "the person took it over" has
  thirteen candidate answers. A name has one.

A button states the act once, on the row the person names, and shows the
result immediately.

The button overwrites whatever the row holds. A button that refuses a filled
row makes a person empty the control by hand before a second press, which
costs more than the mistake it prevents.

## The field owns the copy

`<date-time-field>` already answers "copy one date field onto another". The
button lives inside the field element, the peer is addressed by its posted
name, and the write goes through one public method. The session form's two
instants point at each other this way.

`<temporal-field>` answers it the same way, with the direction reversed. The
datetime control says "copy me into that one" because either instant may be
the one a person filled. A Release row says "fill me from that one", because
one field is always the source.

So the button is rendered by `TemporalField()` and wired by
`<temporal-field>`. No second element, and no second answer to a question the
codebase has answered.

`TemporalCopySource` states the source's posted name and the button's label,
beside `DateTimeCopyTarget`. `ReleaseRowForm` names one:
`original_release_date`, which carries no form prefix and so is unique on the
page. `TemporalFieldProps` gains `field_name`, which is the posted name the
widget already holds, and the button carries the source's name. The element
resolves `temporal-field[field-name="…"]`.

Nothing reaches the views. `editions_area()` keeps its signature, and the
Editions area learns nothing about Original release.

A cloned row needs no work. The element connects on arrival, as the row's
`<temporal-field>` already does for its own radios.

## A copy is a draft read and a draft adopted

The thirteen posted inputs are the value. `TemporalDraftData` names them, the
server renders them, `value_from_datadict` reads them back, and every
`commitEndpoint()` rewrites nine of them. They are the one representation
both sides already agree on.

So the copy is not a choreography:

```text
readDraft(host) -> TemporalDraft        the thirteen named inputs
adoptDraft(host, draft)                 the state that draft implies
copyTemporalDraft(source, target) = adoptDraft(target, readDraft(source))
```

`initField()` adopts too. It reads the draft the server rendered and derives
the end shape, the open start, the decade boxes and the disclosure from it.
Today that derivation is written inline and runs on page load alone.
`adoptDraft()` is that code, named and called twice.

This is the whole argument for the shape. An ordered sequence written only
for the copy is exercised only by a copy, and a copy is the rarer path. The
same code on both paths is run by every page load, and the tests that already
pin a stored *since* and a stored *until* fail when it is reordered.

Three facts the derivation owns, which a copy that moved DOM state directly
would have to restate and would drift from:

- `whole_decade` is no posted key. It is a nameless box, and the draft states
  it as `{endpoint}_decade`.
- The end shape is derived from `kind` and from whether the end holds
  anything. It is not read off the radio.
- The disclosure opens when the collapsed field cannot state the value.
  `canCollapse()` is that predicate, and the server's
  `_needs_precision_controls()` is the same predicate written a second time.
  A copy that opened the disclosure on its own rule would be a third.

`initField()` is refactored to make this possible: reveal the segments, bind
the engine, bind the controls, adopt the rendered draft. The adopt step now
commits, which it did not before, so a test pins that adopting a field's own
draft changes nothing.

## The element announces its commits

Typing into a segment fires no native event. The engine takes the keystroke,
writes the buffer and commits, so nothing bubbles.

`<temporal-field>` therefore dispatches `temporal-field:change` on every
commit, as `<date-time-field>` dispatches its own for the same reason. The
button listens for it on the source and paints its enabled state. Without
this the button would never notice a source filled after the page loaded.

## The three inert states

The server renders the button `hidden` and `disabled`, and the element shows
and enables it when it connects.

While the source states nothing the button stays disabled, and its title says
to fill Original release first. `currentKind()` answers whether it states
anything.

`TemporalField()` renders no `<temporal-field>` wrapper at all when a part
holds more characters than a segment, which is how a refused value echoes
back. The button finds no source then, and stays disabled with a title naming
Original release as the thing to correct.

## The stale sentence this work corrects

`games/views/catalog_section.py` opens by saying the whole row is the radio's
label. `ChoiceCard` renders a `Div`, and the `Label` wraps the radio and its
own text alone. A reader who believes the docstring expects a press inside
the card to move the library mark. The docstring is corrected with this
change.

## Tests

`ts/elements/temporal-field.test.ts` covers the refactor first: adopting a
field's own draft is a fixed point for every stored shape, and the tests that
pin a stored *since* and a stored *until* keep passing. Then the copy, over a
day, a range, a *since*, an *until*, a whole decade, both qualifiers, a
target that holds a value already, and a source that holds nothing. A *since*
copied into a collapsed target opens the disclosure. A date copied over an
*until* leaves the end-shape radios usable.

`tests/test_game_form_page.py` covers the button once per Release row, its
two inert attributes, the source name it carries, and the button inside the
`<template>`. That last assertion reads the whole body: the file's `live()`
helper cuts the markup at the first template.

`e2e/test_game_form_catalog_e2e.py` states an Original release, presses the
button on a row the browser cloned, submits, and reads the
`Release.release_date` the form wrote. A second test types into Original
release and watches the button enable without a reload, which is the only
place the commit event is proved.

## Afterwards

`TemporalFieldProps.expanded` states what `canCollapse()` derives. It stays
for now, because it paints the field before the element upgrades and with no
script at all. Removing the duplication is its own change.
