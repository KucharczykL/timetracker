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
It also mirrored the two year fields once, and dropped that when both dates
became `<temporal-field>`.

Two facts keep the mirror out:

- A sort name is a derivation of a name. An original release is not a
  derivation of the release in hand. A person who owns a 2019 port of a 1997
  game states two different days on purpose.
- The mirror stops writing when the person takes the target over. A temporal
  control holds thirteen inputs, so "the person took it over" has thirteen
  candidate answers. A name has one.

A button states the act once, on the row the person names. The result is on
screen immediately, which an automatic fill is not.

The button overwrites whatever the row holds. A button that refuses a filled
row makes a person empty thirteen inputs by hand before a second press, which
costs more than the mistake it prevents.

## What the copy moves

The element keeps its value in the segment buffers and the toggle boxes.
`commitEndpoint()` writes the thirteen named inputs out of those. A copy of
the named inputs therefore moves the derived half alone, and the target then
paints from buffers nobody wrote.

`ts/elements/temporal-field.ts` owns those internals and exports the copy:

```text
copyTemporalDraft(source, target)
  per endpoint: the segment buffers, approximate, uncertain, whole_decade
  then: open_start and the end-shape radio
  then: the paint, then commitEndpoint() for both endpoints
```

`commitEndpoint()` already writes both endpoints and the kind on one call.

`initField()` binds the listeners and paints the first state in one pass. The
paint half becomes `paintField()`, which the copy runs again and the bind half
runs once. A second bind would answer one click twice.

## Where the button lives

`_labelled()` in `games/views/catalog_section.py` renders a label, a control
and its refusals. It gains an `extra` slot, and `_release_card()` puts the
button in the Released cell.

`_release_card()` also renders the `<template>` the browser clones, so a row a
person adds carries the button with no extra work.

`<catalog-editor>` already holds one delegated `click` listener for the add
and bin buttons. The copy is a third branch in it. Nothing binds per row.

## Where the source is

The button names its source: `data-catalog-copy="<id>"`, and the handler reads
`document.getElementById(id)?.closest("temporal-field")`.

The id comes from the view, not from a guess about Django's naming.
`editions_area()` takes an `original_release_id` argument, and both the Add
Game and the Edit Game view pass `form["original_release_date"].id_for_label`.

`CatalogEditorProps` stays empty. The element still reads the page rather than
an attribute, and a cloned row inherits the hook because the id holds no row
number.

## The two inert states

The server renders the button `hidden` and `disabled`, and
`<catalog-editor>` shows and enables it when it connects. The end-shape radios
already arrive this way. With no script the value still round-trips; the
convenience alone is gone.

While Original release states nothing the button stays disabled and its title
says to fill that field first. A disabled button moves no layout and names its
own condition, which a hidden one does not.

## Tests

`ts/elements/temporal-field.test.ts` covers `copyTemporalDraft` over a day, a
range, a since, an until, a whole decade, both qualifiers, a target that holds
a value already, and a source that holds nothing.

`ts/elements/catalog-editor.test.ts` covers the delegated click on a rendered
row and on a cloned row.

`tests/test_game_form_page.py` covers one button per Release row, the two
inert attributes, the id the view passes, and the button inside the template.

`e2e/test_game_form_catalog_e2e.py` states an Original release, presses the
button on a row, submits, and reads the `Release.release_date` the form wrote.
