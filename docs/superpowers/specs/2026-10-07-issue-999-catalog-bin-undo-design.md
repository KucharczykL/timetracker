# The catalog editor's bin can be taken back (#999)

## Problem

`ts/elements/catalog-editor.ts` answers the bin by setting the row's
`removed` input and hiding the row. Nothing brings it back. A bin on the
marked Release also moves the mark (and through `mirrored_identity()`,
`Game.platform` and `year_released`) to a sibling. Reload is the only
remedy and it discards every other edit.

## Decisions

### A binned row leaves a stub in its place (UI, approved)

Each row has a stub sibling directly after it: one line in the dashed
`look="fixed"` field box, a leading bin glyph, the sentence
"PC release will be removed" / "Standard edition will be removed"
("Unnamed edition will be removed" for a blank name), and a trailing
ghost `Undo` button (`ms-auto`, default control size; the box grows to
50 px, which still sits below a card's height). The button's accessible
name starts with its visible word: "Undo removing the PC release" /
"Undo removing the Standard edition" / "Undo removing the unnamed
edition" (WCAG 2.5.3).

The stub is shown exactly while its row states removal. A row the server
keeps in sight because it carries a sentence (`_row_hooks`) shows its
stub too, so the one binned row that looks live still says it is going.

The stub stays until submit. It needs no timeout and survives a refused
re-render, which a toast does neither of.

### One fixed box for a stated value and a binned row

The opener-fact row (`_stated_row` in `common/components/primitives.py`)
draws a dashed fixed field box with a leading icon and a sentence. The
stub is the same shape with a trailing action. Extract `FixedBox`
(primitives): `field_box_class("full", look="fixed")`, a decorative
leading `Icon` named by the caller, then the `[]` children. It takes the
element tag (`dd` for the fact row's `Dl`, `div` for the stub) and extra
attributes. `_stated_row` renders through it; its markup does not change
(the statement stays the `dd`'s last child).

### The stub is server-rendered, a sibling, never inside the row

The row is hidden whole (`hidden` plus inline `display:none`), so a stub
inside it would hide too. The server renders the stub right after the
release card (inside the Edition's `ChoiceCardGroup`) and right after the
Edition block (in the editions column). Each template renders its row
and stub as one `Fragment`, so a clone has both.

The stub carries `data-catalog-binned` and never `data-catalog-release`
or `data-catalog-edition`, which row counts, `isGoing`, e2e locators and
page regexes read. Undo (`data-catalog-restore`) finds its row as the
stub's `previousElementSibling`: a release stub sits inside the Edition
fieldset, so `closest()` would find the Edition. Appending a row inserts
after the last row's stub.

The stub's sentence is its own `Span` and its button name an
`aria-label`; both are `_Name` hooks. The names a row restates are its
own hooks plus its stub's, for platform and for edition name alike.

### A row is going when its own input says so

The `removed` input is the whole state. A row is going when its own
`removed` input, or its Edition's, reads `on`; `isGoing` reads that, not
`hidden`. Visibility follows the input: the bin writes `on`, hides the
row and shows the stub; Undo writes `""` (which `BooleanField` reads as
not removed, as the unbound form posts), shows the row and hides the
stub. A row the server keeps in sight while it states removal is going
too, so the mark never sits on it. Its bin hides it; its Undo makes it
stay.

Row and stub are hidden by the `_OUT_OF_SIGHT` pair (`hidden` plus
inline `display:none`), and shown by clearing both. Focus moves to the
stub's Undo on bin and to the row's bin on Undo.

Undo of a server-drawn binned Edition shows rows whose sentences
`reads_as_stated(going=True)` stripped. The next submit states them
again; nothing is lost.

### The mark is the person's choice, not a history

The element keeps one chosen mark: the value of a hidden input
`catalog-chosen-mark`. The server renders it with the posted value when
there is one, else with `graph.mark` (the posted `in_library` on a bound
form, the stored mark on an unbound one); the person's every pick of a
mark writes it. An automatic fall never writes it.

After every bin, Undo and append, `restateMark` decides:

1. the chosen mark's input is staying → check it;
2. else a staying mark is checked → leave it;
3. else check the first staying mark.

It dispatches `change` only when it moved the mark, under a flag, so the
listener that writes the chosen mark (a `change` on `MARK_INPUT`) skips
the element's own events. `isTrusted` is not used: jsdom's `click()` is
untrusted.

This gives back the never-binned mark for any order of bins and Undos,
and across a refused re-render, since the chosen value is posted. The
form ignores the input: it names no row the graph writes, and a value
naming no row reads as none.

Append inserts after the last row's stub when its next sibling is one,
else after the row.

Back navigation without bfcache restores the radios but not hidden
inputs; every bin is lost then and the chosen input holds the server's
value. The next bin, Undo or append moves the mark to it. This is the
state the server drew, and is accepted.

### Docs that state the one-way rule

`docs/catalog.md` (the mark falls "a removal, not a mistake"), the
comment in `games/catalog_form.py` `_validate_set`, and the element's
module and `restateMark` docstrings change to the chosen rule.

## Not changed

What a still-binned row posts, the count inputs, renumbering (none), and
`games/catalog_form.py`'s rule for a mark on a going row.

## Tests

- vitest: Undo restores `removed`, visibility and stub; the marked row
  gets its mark back; bin A, bin B, Undo A, Undo B ends on A; a person's
  pick since the bin keeps theirs; an Edition undone around a separately
  binned Release; a row added after a binned last row lands after its
  stub; the stub's names follow platform and edition name; a chosen mark
  rendered on a binned row comes back on Undo.
- pytest: a live row's stub is hidden, a re-rendered binned row's stub is
  visible (also when the row stays in sight); both templates carry a stub
  (read through `templates()`); the chosen-mark input echoes the posted
  value; the fact row still renders.
- e2e (two Releases): bin the marked Release, Undo, submit; the Release
  survives and keeps the mark.

## Follow-up issues to file

None.
