# Platform icons name their glyphs

Issue: [#1321](https://github.com/KucharczykL/timetracker/issues/1321).
Precedent: [Select platforms, then edit or remove them in bulk](2026-09-28-issue-1136-platforms-list-selectable-design.md).

## Result

A platform's `icon` names a snippet that draws a distinct glyph. A
person states it through the picker; nothing derives it from the name.

## Why

Three snippets are copies of another under a platform's name:
`nintendo-3ds` of `nintendo`, `physical-media` of `physical`, `ps1` of
`playstation`. `Platform.save()` fills a blank icon with
`slugify(name)`, which gives a slug no snippet has for most names
("Playstation 5" gives `playstation-5`). `get_icon_node` then draws
Unspecified.

The deployed library (dump of 2026-09-19) holds 25 platforms. Every
icon names a snippet; 8 name an alias.

## The snippets

The three aliases go, and `make gen-icons` runs. Every other snippet is
named for its glyph already. `get_icon_node` keeps its fallback, which
interface icons share.

## The vocabulary

`common/platform_icons.py` owns it:

- `PLATFORM_ICONS`, unchanged: every icon a platform may name.
- `RETIRED_ICONS`: each alias and the glyph that replaces it.
- `canonical_icon(slug)`: a slug in `PLATFORM_ICONS` stays, an alias
  gives its glyph, and any other value gives `unspecified`.

## The model

- `Platform.icon` defaults to `"unspecified"` and is not blank. One
  spelling states no icon.
- `save()` derives nothing from the name. A new platform, from the
  form, the API or a picker's create row, starts at Unspecified.
- `clean()` refuses a slug outside `PLATFORM_ICONS`, on the `icon`
  field, so a form shows it beside the picker. `save()` calls
  `clean()`, so every save path is held, and the rule reads the live
  set, so a new icon needs no migration. An `UPDATE` does not call it:
  the bulk Edit's statement refuses such a slug, and its Undo writes
  back only what the ledger recorded, which the migration makes
  canonical.

## The migration

One migration alters the field and rewrites every row whose icon is
not in its set: an alias to its glyph, any other value to
`unspecified`. It does the same to the `earlier` and `stated` of each
`BatchChange` row that records a platform's `icon`, so an Undo never
writes a retired slug back. It holds its own literal copy of the
aliases and of the 19 slugs, and imports no application code, so its
meaning does not move when the vocabulary does. On the 2026-09-19 dump it changes 8
rows. `make verify-dump` rehearses it.

## The callers

- `PlatformForm.icon` is a choice over `PLATFORM_ICONS`; an empty or
  omitted value states `unspecified`, so the API's name-only create
  (`created_by_form`) keeps working. The branch that kept an older
  slug pickable goes: no older slug remains.
- `load_sample_data` passes each fixture icon through
  `canonical_icon`, because `sample.yaml.gz` still names aliases and
  is generated, not edited.
- `games/fixtures/platforms.yaml` states each icon: Steam `steam`,
  Xbox Gamepass `xbox-gamepass`, Epic Games Store `egs`, Playstation 5
  `ps5`, Playstation 4 `ps4`, Nintendo Switch `nintendo-switch`,
  Nintendo 3DS `nintendo`. Without them `loadplatforms` would give
  each row `unspecified`. Its help text stops promising a slug from
  the name.
- A saved filter naming a retired slug in `PlatformFilter.icon` is
  left alone: it matches no row, as it would for any other text.

## Tests

About 100 test platforms in 53 files name a slug no snippet has
(`"pc"`, `"test"`, `"dark"`). Each takes a real slug, or none where the
test reads no icon. `tests/test_loadplatforms.py` stops expecting a
slug from the name.

- No two snippets in `games/templates/icons/` draw one glyph, title
  ignored. This replaces `test_no_two_picker_icons_draw_one_glyph`;
  `test_an_older_slug_stays_pickable` goes.
- The migration maps an alias, a blank value and an unknown value,
  leaves a known slug, and maps a ledger row's two values.
- `clean()` refuses an unknown slug on the `icon` field; a platform
  saved with no icon holds `unspecified`; the form and the API's
  name-only create give `unspecified`.
- `canonical_icon` answers each of its three cases.
- `loadplatforms` and `load_sample_data` leave only slugs in
  `PLATFORM_ICONS`.

## Not in this issue

- Glyphs for consoles the picker lacks (#1325).
- An icon a person uploads (#1326).
