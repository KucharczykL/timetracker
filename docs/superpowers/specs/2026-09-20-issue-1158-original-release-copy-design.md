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

## Why a custom element

`<temporal-copy>` wraps the button, as `<copy-control>` wraps its own.

A cloned row is the reason. `<catalog-editor>` wires itself once, and
`addRelease()` clones `template.innerHTML` verbatim, so a plain button in a
clone keeps whatever attributes the server wrote and nothing reaches it
again. The radios inside a cloned row escape this only because each row's
`<temporal-field>` is an element of its own and connects on arrival. A
button needs the same hook.

The element also owns the one piece of state a delegated listener has no
place for: whether Original release states anything yet.

`<catalog-editor>` and `CatalogEditorProps` stay as they are.

## The two ids

`TemporalCopyProps` states `source_id` and `target_id`, the ids of the two
kind selects. The element resolves each with `getElementById()` and then
`closest("temporal-field")`.

The view states both. `editions_area()` takes an `original_release_id`
argument, and the Add Game and Edit Game views pass
`form["original_release_date"].id_for_label`. The row states its own as
`row["release_date"].id_for_label`.

A cloned row needs no work: a Release row form is prefixed
`edition-{n}-release-{n}`, so its id holds both placeholders and
`renumbered()` rewrites the prop with the rest of the markup.

## What the copy moves

The element keeps a date in the segment buffers and the toggle boxes.
`commitEndpoint()` writes nine of the thirteen named inputs out of those: the
four date parts per endpoint, and the kind. The four qualifier keys are not
written at all, because for those the named input **is** the checkbox a
person ticks. `whole_decade` is no posted key; it is a nameless box that
reaches the wire as `{endpoint}_decade`.

So a copy of the named inputs alone moves the derived half and leaves the
target painting from buffers nobody wrote.

`ts/elements/temporal-field.ts` owns those internals and exports
`copyTemporalDraft(source, target)`. The order is load-bearing:

1. `open_start`, because setting it clears the endpoint beside it.
2. The segment buffers, through `setSegmentBuffer()`. A write to `value`
   leaves the buffer and the visible text disagreeing.
3. The qualifier boxes, which are the named inputs.
4. `whole_decade` per endpoint, then `paintDecade()`.
5. The end-shape radio, **copied from the source's radio**, then
   `paintEndShape()`.
6. `commitEndpoint()`, which writes both endpoints and the kind at once.
7. `setExpanded(target, true)` when a qualifier or a decade box came across.

Step 5 is why this is a sequence and not a repaint. `initField()` derives the
end shape from the `kind` named input, which a copy has not written yet at
that point. Running that derivation after a copy reads the target's own stale
kind and states `end_none`, so a *since* arrives as a *date*. `initField()`
is left alone; the copy paints what it changed and nothing else.

Step 7 is the second such trap. The disclosure opens from a server-rendered
`expanded` attribute, so without it a copied qualifier or decade ticks a box
inside a collapsed row. The value posts, and nobody sees it.

## Where the button lives

`_labelled()` in `games/views/catalog_section.py` renders a label, a control
and its refusals. It gains an `extra` slot, and `_release_card()` puts the
element in the Released cell.

The cell is one grid item and the element goes inside it, so the card's four
tracks are unchanged.

`_release_card()` renders the `<template>` as well, so the row a person adds
carries the element already.

The button states `type="button"`. A submit in the card would answer the
Enter key and would make the e2e suite's `#add-form button[type=submit]`
name two controls.

## The three inert states

The server renders the button `hidden` and `disabled`, and the element shows
and enables it when it connects. A clone connects on arrival, which is the
whole reason for the element.

While Original release states nothing the button stays disabled, and its
title says to fill that field first. The element listens for `change` on the
source, so a field filled later enables the button. A disabled button moves
no layout and names its own condition, which a hidden one does not.

`TemporalField()` renders no `<temporal-field>` wrapper at all when a part
holds more characters than a segment, which is how a refused value echoes
back. The element finds no source then, and stays disabled with a title
naming the Original release as the thing to correct.

## The stale sentence this work corrects

`games/views/catalog_section.py` opens by saying the whole row is the radio's
label. `ChoiceCard` renders a `Div`, and the `Label` wraps the radio and its
own text alone. A reader who believes the docstring expects a press inside
the card to move the library mark. The docstring is corrected with this
change.

## Tests

`ts/elements/temporal-field.test.ts` covers `copyTemporalDraft` over a day, a
range, a *since*, an *until*, a whole decade, both qualifiers, a target that
holds a value already, and a source that holds nothing. The *since* case
pins step 5, and the qualifier cases pin step 7 against a collapsed target.

`ts/elements/temporal-copy.test.ts` covers the connect of a clone, the
disabled state while the source states nothing, the enable when the source
changes, and a source that renders no wrapper.

`tests/test_game_form_page.py` covers one element per Release row, the two
inert attributes, both ids, and the element inside the `<template>`. The
template assertion reads the whole body: the file's `live()` helper cuts the
markup at the first template.

`e2e/test_game_form_catalog_e2e.py` states an Original release, presses the
button on a row the browser cloned, submits, and reads the
`Release.release_date` the form wrote.
