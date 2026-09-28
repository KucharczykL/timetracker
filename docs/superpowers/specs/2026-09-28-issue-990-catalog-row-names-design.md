# A catalog row names its current value

The Editions area of the Game form names each row for assistive
technology. A Release row names its Platform. An Edition block names
its Edition. The name always states the value that the row holds now.

## The names

| Node | Follows | Pattern | Empty |
|---|---|---|---|
| Release mark text | `platform` | Show the {} release in the library | |
| Release bin | `platform` | Remove the {} release | |
| Edition `legend` | `name` | {} | Unnamed edition |
| Edition bin | `name` | Remove the {} edition | Remove the unnamed edition |

For a Release, {} is the text of the option that the Platform select
shows. A row with no Platform shows the empty option, `Unspecified`.
No position ("the second release") is used: removal does not
renumber the rows.

For an Edition, {} is the trimmed name. An empty name uses the Empty
sentence.

The mark's radio has no `aria-label`. Its label text names it at each
width, thus the visible text and the name are the same.

## The server

The server writes each sentence one time. The renderer reads the
trimmed value of the bound field, not the stored record, thus a
refused page names the posted value.

The page builds one map from Platform key to name, from the queryset
that the field offers. Each row reads the map with `str(value)`, thus
a row adds no query. A key that the map does not hold gives the
field's `empty_label`, because the select then shows the empty
option. The clone templates are unbound, thus they name `Unspecified`
and `Unnamed edition`.

Each named node carries `data-catalog-name` (the pattern) and
`data-catalog-name-of` (the value it follows). A node with an Empty
sentence also carries `data-catalog-name-empty`. `ChoiceCard` accepts
attributes for its label text. `ChoiceCardGroup` accepts attributes
for its `legend`.

## The element

`<catalog-editor>` owns the update, because the server cannot know
the value of a cloned row.

- One delegated `input` listener. A Platform select rewrites the
  `platform` nodes of its own `[data-catalog-release]`. An Edition
  name input rewrites the `name` nodes of its own
  `[data-catalog-edition]`.
- On connect, the element rewrites each row. The element's script is
  deferred, thus connect runs after the browser restores form values.
  A page from the back-forward cache keeps its names, thus there is
  no `pageshow` handler.
- The element splits the pattern on `{}` and joins the parts with the
  value, thus a `$` stays literal. A node with `aria-label`
  gets a new `aria-label` and `title`. Any other node gets new text.
  The element sets text and attributes, never `innerHTML`.

## Tests

- pytest: a refused page names the posted Platform and Edition name.
  A whitespace name gives the Empty sentence. A posted Platform key
  outside the library gives `Unspecified`. The templates carry the
  pattern attributes. The mark's name comes from its label text. The
  query count does not grow with the rows.
- vitest: each kind of node is rewritten. An Edition name leaves the
  Release names alone. A `$&` value stays literal. Connect corrects a
  stale name.
- Playwright: a changed row and a cloned row are found by role and
  name, at both widths. At narrow width the visible text changes. Row
  0 of a cloned Edition follows its Platform. A cloned Edition is
  found by its typed name. No test uses back or forward; the vitest
  connect case covers that.
- The full `make check` passes.

## Limits

- The names do not change the posted values.
- The other controls keep their names, which include no value.
