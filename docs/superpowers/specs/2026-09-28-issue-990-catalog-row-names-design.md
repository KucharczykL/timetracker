# A catalog row names its current value

The Editions area of the Game form names each row for assistive
technology. A Release row names its Platform. An Edition block names
its Edition. This spec states where each name comes from. The name
always states the value that the row holds now.

## The names

| Node | Name |
|---|---|
| Release mark (radio and its text) | Show the {platform} release in the library |
| Release bin | Remove the {platform} release |
| Edition group (`legend`) | {name}, or Unnamed edition |
| Edition bin | Remove the {name} edition, or Remove the unnamed edition |

{platform} is the text of the option that the row's Platform select
shows. A row with no Platform shows the empty option, thus its name
says `Unspecified`. A position ("the second release") is not used.
Removal does not renumber the rows, and the same position occurs in
each Edition.

{name} is the Edition name, trimmed. An empty name uses the fallback.

## The server

The server writes each sentence one time. The renderer reads the value
from the bound field, not from the stored record. Thus a refused page
names the value that the person posted.

For a Platform, the renderer finds the Platform by the field's
primary key, in the field's own queryset. A value that the queryset
does not hold gives `Unspecified`, because the select then shows the
empty option. The clone templates are unbound, thus they name
`Unspecified` and `Unnamed edition`.

Each named node carries the sentence as a pattern:
`data-catalog-name="Remove the {} release"`. A node whose name has a
fallback also carries `data-catalog-name-empty` with the full fallback
sentence. `ChoiceCard` accepts attributes for its mark, and puts them
on the radio and on its text. `ChoiceCardGroup` accepts attributes for
its `legend`.

## The element

`<catalog-editor>` owns the update. The server cannot know the value
of a cloned row, or a value that the browser restores after back or
forward navigation.

- One delegated `input` listener. A Platform select or an Edition
  name input in a row causes the row's names to be written again.
- On connect, the element writes the names of every row. This also
  corrects a restored value.
- The element puts the value into the pattern. A node with
  `aria-label` gets a new `aria-label`, and a new `title` if it has
  one. Any other node gets new text. The element never parses HTML.

The element does not contain the words of any sentence.

## Tests

- pytest: a refused page names the posted Platform and the posted
  Edition name. The templates name `Unspecified` and `Unnamed
  edition`.
- vitest: an `input` event writes each kind of node. Connect corrects
  a row whose name does not agree with its value.
- Playwright: a cloned row and a changed row are found by role and
  name, at narrow and wide widths. A cloned Edition is found by its
  typed name.
- The full `make check` passes.

## Limits

- The names do not change the posted values.
- The names of the other controls in a row do not change. Their
  labels do not include a value.
