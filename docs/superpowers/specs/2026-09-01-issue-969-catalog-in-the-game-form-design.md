# The Game form owns the catalog graph

A player states a Game's Editions and Releases in the form that states the
Game. This supersedes the screens of
[#969's first design](2026-08-30-issue-969-private-catalog-management-design.md),
which put six routes and two forms beside Game detail.

## Why it moves

Game detail has one grammar for a child collection, and `_purchases_section`
states it: read the rows here, edit a row in place, create somewhere else. The
Purchases section carries no `Add purchase`; the Sessions section carries no
`Add session`. The page's whole write vocabulary is three verbs about the Game
itself — `Log this game`, `Edit`, `Remove`.

The Releases section broke that with four creation verbs. Worse, it made a
second way to reach rows the Add Game form already writes:
`save_private_game()` states a Game, its default Edition and its default
Release in one call, and `add_game` already hands it a Platform and a date.
Two write paths to one graph is what let the flat columns go null — the
standalone path commits an Edition, then mirrors against a graph holding no
Release.

One form, one path.

## What Edit Game becomes

Edit Game grows the graph below the Game's own fields.

```text
Name                [Xenoblade Chronicles     ]
Sort name           [                         ]
Original release    <temporal field>
Status              [Played              v]
Wikidata            [                         ]

Editions
  Edition name      [Definitive Edition       ]           [bin]

    In library  Platform            Released
    (o)         [Nintendo Switch v] <temporal field>      [bin]
    ( )         [Steam           v] <temporal field>      [bin]
    Add release

  Add edition
```

An Edition block repeats. A Release row repeats inside it. A Game holding one
unnamed Edition and one Release renders one block and one row.

That is still furniture. The one-Edition Game gains a bordered block, a header
row and a mark it cannot move, where today it states a Platform and a year in
two plain rows. The trade is deliberate: one grammar that holds every Game
beats a short form that a second Platform breaks. What keeps it small is that
nothing in the block is a menu — the block is a `<fieldset>`, the mark is a
radio, and both add buttons are ghost.

`In library` is the Release the games list draws. The name states what the mark
does today: `mirror_legacy_columns()` writes `Game.platform` and
`Game.year_released` from the default Release, and the list draws its one badge
from that column. `Default` names a database fact; this names the one a person
can see.

**The mark is one group over the whole Game.** Every Release row in every
Edition posts to one radio name, so exactly one row across the form carries it.
`Edition.is_default` and `Release.is_default` stay per-parent in the database,
and the form states the marks the person never sees: the chosen row's Edition
becomes the default Edition, the chosen row becomes that Edition's default
Release, and every other Edition keeps whichever default Release it already
held. Exposing both levels would ask a person to state a fact with no visible
effect, since only one Release reaches the list at all.

## What Add Game keeps

**Amended after the branch shipped.** Add Game hosts the same Editions area as
Edit Game, and `InitialReleaseForm` is gone. The area is additive — a page that
drew one Release row now draws one Release row and offers more — so nothing a
person could see stops being visible, which is the test the deferred picker
below fails.

The original reading was that a new Game has one Edition and one Release to
state, so a second row states something the games list cannot show. That is
still true of the list, and it is not a reason to make a person save and then
reopen the form to say the rest. What the list draws is settled by the mark, the
same on both pages.

`game=None` is what tells `CatalogGraphForm` there is no Game yet: it draws one
blank Edition holding one blank marked row, `save_private_game()` seeds the
Game's default Edition and Release from that row, and `adopt()` claims both
before the graph write, so `add_release` adds no empty Release beside the stated
one. The Game and the whole graph share one transaction, thus a refused row
leaves no Game behind.

The Platform control on Add Game is a plain `<select>` now, not the searchable
combobox `InitialReleaseForm` carried. `ReleaseRowForm` uses one on purpose: a
composite widget keeps its id on a wrapper `<div>`, and a cloned row would have
to rewrite that id and re-run the element's wiring. Both pages read the same.

## What Game detail keeps

One read-only table, in place of the per-Edition blocks and their control rows.

```text
Editions  3

Name                 Platforms                          Actions
Definitive Edition   Nintendo Switch (2025), Steam (2024)  [Edit]
```

The Platforms cell is a comma list in one cell, not a spanning cell:
`StyledTable` guards one cell per column (`common/components/primitives.py:2540`)
because the responsive column-hiding is position-based, and a spanning cell
corrupts it.

`Actions` follows the house column — `Column("Actions", align="right",
priority=3)`, as every other table in the app writes it — and holds one link to
Edit Game. No add, no remove: the form owns both.

`_reads_plainly()` still gates the section. A Game with one unnamed Edition and
one Release states its Platform and date in the header's two rows, and a
one-row table below them would say it twice.

The under-construction notice gains one sentence: a Platform beyond the first
does not reach the games list yet.

## What the form must honour

**One transaction over the finished graph.** The submit compares the posted
rows against the stored ones and calls `add_edition`, `update_edition`,
`remove_edition`, `add_release`, `update_release` and `remove_release` inside a
single `write_and_mirror(game, ...)`. The mirror runs once, at the end. Per-row
mirroring is what opens the window where the graph holds an Edition and no
Release.

**A Release row states a full temporal value.** Not a year box.
`docs/temporal.md` states that a form never widens a stored value, so a control
that can only say `2024` would drop the day from a stored `2024-06-14`. Each
row hosts `TemporalField`, and each carries a distinct field name, which the
row prefix supplies.

**The last live Release of an Edition stays.** `remove_release` allows it, and
the mirror then writes null to `Game.platform` and `Game.year_released`. The
form refuses it while those columns exist. #889 lifts the rule.

**A refusal lands on the row that caused it.** Every verb raises a
`ValidationError` carrying one sentence. The form puts it on the offending
Edition or Release row, not on the form as a whole.

## The Release row is a choice card

A row is not a table row with a radio at the end. The whole row is the radio's
option: clicking anywhere inert inside it takes the mark. Two new builders in
`common/components/primitives.py` state that, named after the existing
`StatisticCard`:

- `ChoiceCardGroup(name=..., ...)` — the `<fieldset>` holding one group
- `ChoiceCard(name=..., value=..., checked=..., label=..., ...)` — one option:
  a `<label>` wrapping the radio, then the row's own controls

**One markup, three widths, no viewport breakpoint.** The Edition block
declares `@container/edition`; the row reflows at `@2xl/edition`. A form that
sits in a narrow column reads as cards whatever the screen is, which
`md:`-prefixed classes cannot say. Below the breakpoint the mark and the bin
share row one and each control sits under its own visible label; above it the
labels go `sr-only`, a header row appears, and the row becomes four columns.

**The first column is fixed, not `auto`.** The header row and the option rows
are separate grids, so `auto` sizes them independently and the headers drift
off their controls. Both declare the same track list, first column `5.5rem`.

**The mark is first.** It is the first child in the DOM and the first cell at
both widths.

**Selection is chrome, not a wash.** A chosen card takes `border-brand`,
`ring-1 ring-brand` and `bg-neutral-secondary-soft`. It does not take
`bg-brand-soft`: in dark that token is blue-900, which drops the row's own
disclosure link to 1.98:1. A card hosts arbitrary content, so the fill has to
stay a surface the content was measured against.

**A row is added by cloning, and adding one needs scripting.** The Editions
area renders a blank Release row and a blank Edition block into `<template>`s;
one custom element detaches them on connect and clones, renumbers and appends
on demand. `ts/elements/filter-group.ts` already states this pattern, and
template content stays inert until cloned, so a `TemporalField` inside one
upgrades on insertion rather than early. A row's names carry its index through
Django's own form prefix, which `TemporalWidget` already honours because Django
hands it the prefixed name, so nothing in `timetracker/temporal.py` changes; the
clone rewrites the index the prefix states.

There is no scripting-off path to a new row. A popup that writes one is
refused: it commits an Edition of its own, which is the second write path this
whole design closes, and on Add Game there is no saved Game to hang one on. A submit
button that re-renders the draft one row longer is refused as well — it works,
but nobody is asked to carry it. What survives scripting off is every row the
page already holds: they edit, they validate and they save.
`docs/temporal.md` keeps its contract, which is about the widget and not about
the form that hosts it.

**The `:checked` rule is scoped to the group's own mark.**

```css
has-[[data-choice-card]:checked]:border-brand
```

not `has-[:checked]:`. `TemporalField` renders its own checked end-shape radio
inside every row, and the unscoped rule lights every card at once. `ChoiceCard`
stamps `data-choice-card` on its input and the group's rule reads only that.

## What accessibility requires

Measured in Chromium against the compiled stylesheet, both themes, at 390px and
1200px: WCAG 2.1 contrast, target size, and the accessibility tree scanned for
roles with no name.

**A hidden label is `sr-only`, never `hidden`.** Above the breakpoint the
per-control labels stop being drawn, and `hidden` removes their text from the
tree — the platform select and the mark are then nameless. They keep their text
and their `for`/`id` pairing and only stop painting.

**Every control states a name.** The mark carries the Platform in its
`aria-label`, since its visible text is the same four words on every row. Each
bin carries what it removes. Each Edition block is a `<fieldset>` with an
`sr-only` `<legend>` naming the Edition.

**The mark's hit area is the column, not the input.** `sr-only` collapses the
label around a 16px radio. A minimum width on the label holds the target at the
column's width.

**One token fix ships first.** `_DISCLOSURE_CLASS` in
`common/components/temporal_field.py` uses `text-brand`, the surface token;
every other link uses `text-fg-brand`. In dark they diverge — Flowbite sets
`--color-brand: blue-600` and `--color-fg-brand: blue-500` — and the disclosure
reads 3.84:1 against the page. It is the only text use of `text-brand` in the
app, it is already shipped on Add/Edit Game, and the one-word swap takes the
whole form to zero contrast failures in both themes. `scripts/contrast_audit.py`
audits `text-fg-brand` and never covered the pair that renders; the swap makes
the table true rather than needing a new row.

Two shortfalls stay, both `TemporalField`'s and both older than this work: its
month and day boxes are 19px wide and its disclosure is 20px tall, under the
24px floor of WCAG 2.2 SC 2.5.8. They are recorded here, not fixed here.

## What is removed

- The six routes, from `games/urls.py` and `games/views/returns.py`
- `games/views/catalog.py`
- `EditionForm` and `ReleaseForm` as page forms; their rules move into the
  Game form's nested rows
- The four control buttons and the per-row icons in `_releases_section`

`games/catalog_writes.py` stays whole. The six verbs are the service, they are
tested, and #782's importer writes through them.

## The backfill

852 of 858 Games hold no Edition. A data migration calls `save_private_game()`
for each private Game holding none, passing the Game's current `platform` and a
`TemporalValue` for its `year_released`, so the graph states what the flat
columns already state and the mirror writes back the same values.

Without it, those Games show no Platform in the Edit form's Editions area until
someone saves them one at a time.

## What waits

**The Add Game picker** — selecting an existing Game so the form writes an
Edition and a Release under it rather than a second Game. Its one power is
turning two Games into one, and that is the one act that makes visible data
invisible: two rows and two Platform badges become one of each. Six sites read
`Game.platform` as a scalar — `_platform_badge`, the `platform` and
`platform_group` criteria, `platform_filter`, free-text search, and the Year
column's sort. #889 retires the columns and teaches all six a set. The verdict
is recorded on #969 and #889.

Adding a Release to an Edition is not deferred. It takes nothing away: the
library gains a fact the list does not draw yet. `add_release` takes
`is_default=False`, so a second Release leaves the default alone and the badge
does not move.

## Tests

- The form writes one transaction: a refusal on the third Release row leaves
  the Game, the Editions and the first two Releases as they were
- A stored `2024-06-14` survives a save that touches only the Edition name
- Removing an Edition's last live Release is refused, with its sentence on the
  row
- Promoting a sibling Release moves `Game.platform`; adding one does not
- A plain Game's Edit form renders one Edition block and one Release row
- Two-library isolation: another library's Edition never reaches the form
- The backfill leaves every Game's `platform` and `year_released` unchanged
- Marking a Release under a second Edition moves both defaults: that Edition
  becomes the Game's, that Release becomes the Edition's, and the Edition left
  behind keeps its own default Release
- The posted form carries exactly one mark; a submit carrying none is refused
- `ChoiceCard` renders its input with `data-choice-card`, and a group holding a
  `TemporalField` marks one card, not all of them
- Browser tests in `e2e/`: add a Release, mark it, remove it, remove an Edition
- Browser tests in `e2e/`: at 390px each control shows its own label; at 1200px
  the header row shows and every control still states an accessible name
