# The release row's platform picker

Part of #481. After #1080 and #1292.

## The field

`ReleaseRowForm.platform` is a `ModelChoiceField`. It is optional. Its
widget is a `SearchSelectWidget` over `/api/platforms/search`.

- The none row reads `UNSPECIFIED_PLATFORM` (`games/reads/releases.py`).
- `revert_on_leave` is on. A first keystroke drops the value. Focus that
  leaves without a pick restores it.
- The form takes the stored Release at construction. `instance` is
  read-only after that, because the queryset and the resolver read it.
- The queryset is `platforms_or_stored`: live platforms, plus the stored
  one, inside the library's own and shared rows. A removed stored
  platform resubmits. A platform of another library never resolves.
- `platform_options` resolves posted keys over the same set. It parses
  each key as a UUIDv7, because the key field refuses any other UUID.
- A key the set does not hold is refused with `PLATFORM_GONE`.
- `platform_option` is the one row shape: the search, the resolver, the
  create route and the dialog. A removed platform reads
  `"<name> (removed)"`.

## Two ways to make a platform

- The create row posts the typed name to `/api/platforms/`.
- The + (`NEW_PLATFORM`) opens Add Platform in a form dialog. After a
  write, `add_platform` answers `CreatedRedirect` with `platform_option`.
  Edit Platform shares the view and answers a plain redirect.

Both select the new row and emit `search-select:change`. The person
submits the Game once.

## The row's layout

The card and the header share `EDITION_COLUMNS`. The date column is a
fixed `11rem`, because both grids must agree and the date has a fixed
width. The picker takes the remaining width. A single-select search box
shrinks to `min-w-0`, so the + stays on its line.

## Names that follow the platform

The mark's label and the bin's name state the platform.

- Server: `CatalogGraphForm.platform_names()` resolves every row's value
  in one query, labelled as the picker labels them. `platform_key`
  spells a bound value as the map keys it. `NO_PLATFORM_KEY` reads
  `UNSPECIFIED_PLATFORM`.
- Browser: `<catalog-editor>` listens for `search-select:change`. Before
  a picker is `wired`, the server's names stand. After, it reads
  `heldLabel()`: the held label, the none label for none, or `null` mid
  edit, which leaves the names.
- A silent hold emits no change. `pageshow` restates every name.

## Back and forward

Chromium restores no picker state on back. The picker shows the stored
platform and holds its key, and the names agree. A typed field, such as
the edition name, restores.

## Rules

- No form page that `tests/test_html_validity.py` lists renders a native
  `<select>`. A MODEL setting may; `settingControlOf` refuses it.
- `games/filters.py` keeps its URL literals, beside the device ones.
