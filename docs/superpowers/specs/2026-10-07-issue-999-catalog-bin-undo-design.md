# The catalog editor's bin can be taken back (#999)

## The line a binned row leaves

Each Release card and each Edition block has a line directly after it. The
line is a `FixedBox` (the dashed field box of an opener fact): a bin glyph,
the sentence "PC release will be removed", and a ghost `Undo` button. The
button's name starts with its visible word: "Undo removing the PC release".
An unnamed Edition reads "Unnamed edition will be removed".

The line is a sibling of its row, because the row hides whole. It carries
`data-catalog-binned` and no row attribute, so row counts and `isGoing` do
not see it. Undo finds its row as the line's previous sibling: a release line
sits inside its Edition, where `closest()` finds the Edition. Both templates
carry the line, and an appended row goes in after the last row's line.

The line shows while its row states removal, also when the server keeps a
binned row in sight for its sentence. Its texts are `_Name` hooks, so they
follow the platform and the Edition name.

## The removed input is the state

A row is going when its own `removed` input, or its Edition's, reads `on`.
`RemovalInput` renders every true value as `on`, so the server and the
browser agree. `isGoing` reads the input, not `hidden`. The bin writes `on`, hides the row,
shows the line and focuses Undo. Undo writes `""`, shows the row, hides the
line and focuses the row's bin. `BooleanField` reads `""` as not removed, so
an undone row posts as an unbinned row posts.

## The mark follows the person's pick

The hidden input `catalog-chosen-mark` holds the person's pick. The server
renders the posted value, else the posted `in_library` before any fall, else
the stored mark. A person's `change` on a mark writes it. The element's own
`change` does not: it dispatches under a flag.

After each bin, Undo and append, `restateMark` checks, in this order:

1. the chosen mark, when its row stays;
2. the checked mark, when its row stays;
3. the first mark whose row stays.

Thus any order of bins and Undos ends on the mark the person picked, when
that row stays. The chosen value is posted, so this holds across a refused
page. Writes read the posted mark only.

An Undo of a binned Edition shows rows whose sentences the server dropped
(`reads_as_stated(going=True)`). The next submit states them again.

Back navigation without bfcache restores radios but not hidden inputs. Every
bin is lost, and the mark moves to the server's chosen row. This is accepted.

## Tests

- vitest `catalog-editor.test.ts`: the line, Undo's post and focus, logged
  drift, mark order, a later pick, a binned Release in a restored Edition,
  append, a refused page; `names` covers the line's hooks.
- pytest `test_game_form_page.py`: the line's visibility, both templates,
  the chosen input.
- pytest `test_catalog_graph_form.py`: writes read the mark; `RemovalInput`.
- e2e: Undo of a Release and of an Edition.
