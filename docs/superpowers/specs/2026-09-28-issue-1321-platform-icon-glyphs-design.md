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

`common/components/platform_icons.py` owns it:

- `PLATFORM_ICONS`, unchanged: every icon a platform may name.
- `RETIRED_ICONS`: each alias and the glyph that replaces it.
- `canonical_icon(slug)`: a slug in `PLATFORM_ICONS` stays, an alias
  gives its glyph, and any other value gives `unspecified`.

## The model

- `Platform.icon` defaults to `"unspecified"` and is not blank. One
  spelling states no icon.
- `save()` derives nothing from the name. A new platform, from the
  form, the API or a picker's create row, starts at Unspecified.
- `clean()` refuses a slug outside `PLATFORM_ICONS`. `save()` calls
  `clean()`, so every save path is held, and the rule reads the live
  set, so a new icon needs no migration. A bulk `UPDATE` does not call
  it; the bulk Edit's statement refuses such a slug already.

## The migration

One migration alters the field and rewrites every row whose icon is
not in its set: an alias to its glyph, any other value to
`unspecified`. It holds its own literal copy of the aliases and of the
19 slugs, and imports no application code, so its meaning does not
move when the vocabulary does. On the 2026-09-19 dump it changes 8
rows. `make verify-dump` rehearses it.

## The callers

- `PlatformForm.icon` is a required choice over `PLATFORM_ICONS`. The
  branch that kept an older slug pickable goes: no older slug remains.
- `load_sample_data` passes each fixture icon through
  `canonical_icon`, because `sample.yaml.gz` still names aliases and
  is generated, not edited.
- `games/fixtures/platforms.yaml` states each icon: Steam `steam`,
  Xbox Gamepass `xbox-gamepass`, Epic Games Store `egs`, Playstation 5
  `ps5`, Playstation 4 `ps4`, Nintendo Switch `nintendo-switch`,
  Nintendo 3DS `nintendo`. `loaddata` calls no `save()`, so the file
  states what the model would refuse to leave out.

## Tests

- No two snippets in `games/templates/icons/` draw one glyph, title
  ignored. This replaces the #1136 test over `PLATFORM_ICONS`.
- The migration maps an alias, a blank value and an unknown value, and
  leaves a known slug.
- `clean()` refuses an unknown slug; a platform saved with no icon
  holds `unspecified`.
- `canonical_icon` answers each of its three cases.
- `loadplatforms` and `load_sample_data` leave only slugs in
  `PLATFORM_ICONS`.

## Not in this issue

- Glyphs for consoles the picker lacks (#1325).
- An icon a person uploads (#1326).
