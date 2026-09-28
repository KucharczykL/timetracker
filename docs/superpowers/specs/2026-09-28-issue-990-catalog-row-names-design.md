# A catalog row names its current value

The Editions area of the Game form names each row for assistive
technology. A Release row names its Platform. An Edition block names
its Edition. A name always states the value that the row holds now.

## The names

| Node | Follows | Pattern | Empty |
|---|---|---|---|
| Release mark text | `platform` | Show the {} release in the library | |
| Release bin | `platform` | Remove the {} release | |
| Edition `legend` | `name` | {} | Unnamed edition |
| Edition bin | `name` | Remove the {} edition | Remove the unnamed edition |

For a Release, {} is the trimmed text of the selected Platform option.
With no
Platform, the text is `Unspecified`. A name never states a position,
because removal does not renumber the rows.

For an Edition, {} is the trimmed name. An empty name uses the Empty
sentence.

The mark's radio has no `aria-label`. Its label text names it. Thus the
name and the label text are always the same.

## The server

The renderer reads the bound value, not the stored record. Thus a
refused page names the posted value.

The page reads the Platform names one time, as a map from key to option
text. Each row finds its name in the map. A key that is not in the map
gives the text of the empty option, `empty_label`. The clone templates are unbound. Thus
they name `Unspecified` and `Unnamed edition`.

Each named node has these attributes:

- `data-catalog-name`: the pattern.
- `data-catalog-name-of`: the value that the node follows.
- `data-catalog-name-empty`: the Empty sentence, if there is one.

Each pattern has one `{}` slot. A pattern without a slot is an error.
The slot and the values that a name follows go to
`ts/generated/catalog-names.ts`. Thus a change on one side stops the
type check of the other side.

## The element

`<catalog-editor>` updates the names. The server cannot know the value
of a cloned row.

- An `input` event on a Platform select updates the `platform` nodes of
  its Release row. An `input` event on an Edition name updates the
  `name` nodes of its Edition block.
- On connect and on `pageshow`, the element updates each row. Chromium
  restores form values after the element connects, and it sends no
  `input` event. `pageshow` comes after the restore.
- The element splits the pattern on `{}` and joins the parts with the
  value. Thus a `$` in a value stays literal.
- A node with `aria-label` gets a new `aria-label`, and a new `title` if
  it has one. Another node gets new text. The element never writes HTML.
- A named node without a pattern, or a named row without its control,
  is an error in the console. The element does not change that name.

## Limits

- The names do not change the posted values.
- The other controls keep their names. Their names include no value.
