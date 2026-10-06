# The release row's platform picker

Part of #481. After #1080 and #1292.

## The field

`ReleaseRowForm.platform` is a `ModelChoiceField`. It is optional. Its
widget is a `SearchSelectWidget` over `/api/platforms/search`.

- The none row reads `UNSPECIFIED_PLATFORM` (`games/reads/releases.py`).
- `revert_on_leave` is on. A first keystroke drops the value. Focus that
  leaves without a pick restores it.
- The form takes the stored Release at construction (`instance`).
- The queryset is `platforms_or_stored`: the visible platforms, and the
  stored one. A removed stored platform resubmits. A platform of another
  library never resolves, stored or posted.
- `platform_options` resolves posted keys over the same set. It parses
  each key as a UUIDv7, because the key field refuses any other UUID.
- `platform_option` is the one row shape. A removed platform reads
  `"<name> (removed)"`.

## Two ways to make a platform

- The create row posts the typed name to `/api/platforms/`.
- The + (`NEW_PLATFORM`) opens Add Platform in a form dialog. After a
  write, `add_platform` answers `CreatedRedirect` with `platform_option`.
  Edit Platform shares the view and answers a plain redirect.

Both select the new row and emit `search-select:change`. The person
submits the Game once.

## A cloned row

The release template renders the picker with the row placeholders.
`renumbered()` replaces them in the name, the search input id and the +
link. The clone wires itself on insertion.

## Names that follow the platform

The mark's label and the bin's name state the platform.

- Server: `CatalogGraphForm.platform_names()` resolves every row's value
  in one query, labelled as the picker labels them, trimmed. Key `""` is
  `UNSPECIFIED_PLATFORM`.
- Browser: `<catalog-editor>` listens for `search-select:change`. It
  reads `SearchSelectElement.heldLabel()`: the committed label, the none
  label for none, or `null`. `null` means nothing is held or the picker
  is not wired. Then the names stay as they are.
- A silent hold emits no change. `pageshow` restates every name.

## Back and forward

Chromium restores no picker state on back. The picker shows the stored
platform, holds its key, and the names agree. A typed field, such as the
edition name, restores.

## Rules

- No form page renders a native `<select>`. `tests/test_html_validity.py`
  holds this.
- `games/filters.py` keeps its URL literals, beside the device ones.
