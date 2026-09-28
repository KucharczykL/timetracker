# Platform icons name their glyphs

Issue: [#1321](https://github.com/KucharczykL/timetracker/issues/1321).
Precedent: [Select platforms, then edit or remove them in bulk](2026-09-28-issue-1136-platforms-list-selectable-design.md).

## Result

A platform's `icon` names a snippet that draws a distinct glyph. A
person states it through the picker. Nothing derives it from the name.

## The snippets

A snippet is named for the glyph it draws. No two snippets draw one
glyph, with the title ignored; a test holds this over every file in
`games/templates/icons/`.

## The vocabulary

`common/platform_icons.py` owns it. It is outside `common.components`,
because that package imports `games.models`, and the model reads the
vocabulary.

- `PLATFORM_ICONS`: every icon a platform may name.
- `RETIRED_ICONS`: each slug that copied a glyph, and that glyph.
- `canonical_icon(slug)`: a listed slug, its glyph for a retired slug,
  else `unspecified`.

## The model

- `Platform.icon` defaults to `unspecified` and is not blank. One
  spelling states no icon.
- `clean()` refuses a slug outside `PLATFORM_ICONS`, on the `icon`
  field. `save()` calls `clean()`. The rule reads the live set, so a
  new icon needs no migration.
- An `UPDATE` does not call `clean()`, so the write behind the bulk
  Edit and its Undo refuses an unlisted slug itself. All three raise
  sites call `require_platform_icon`. `games.E013` refuses a listed icon
  no snippet draws.

## The migration

Migration 0018 rewrites each platform whose icon is not listed: a
retired slug to its glyph, any other value to `unspecified`. It does
the same to the `earlier` and `stated` of each `BatchChange` row that
records a platform's `icon`. It holds its own copy of the slugs and
imports no application code, so its meaning does not change with the
vocabulary. On the dump of 2026-09-19 it changed 8 rows and left no
unlisted icon.

## The callers

- `PlatformForm` offers `PLATFORM_ICONS`. An empty or omitted icon
  states `unspecified`, so the API's name-only create works.
- `load_sample_data` passes each icon through `canonical_icon`,
  because the generated `sample.yaml.gz` holds retired slugs.
- `games/fixtures/platforms.yaml` states each platform's icon.
- A saved filter that names a retired slug matches no row. It stays.

## The group picker

Group is a `SearchSelect` on the Platform form and the bulk Edit, so
its panel is a `<drop-down>` like every other picker. A group is text
on a platform, not a row, so no endpoint creates one.
`SearchSelect(create=...)` takes one `CreateRow`, which names how the
create row commits, and none offers no row:

- `PostCreate(url)`: it posts there and holds the answered row.
- `EmitCreate()`: it emits `search-select:create`; the consumer commits.
- `SelectTyped()`: it holds the typed text as value and label.

One value, so no two ways contradict. The element
codegen emits a `Literal` of strings as a TypeScript union whose reader
throws on any other value. A form submit commits text typed and not
picked, so the typed group is never dropped.
`TextSearchSelectWidget` hosts a text field: its options are the
library's groups, its create row reads `Use “…”`. On the bulk Edit it
sits inside `UnsetWidget`, so ⊘ states no group.

## Not in this issue

- Glyphs for consoles the picker lacks (#1325).
- An icon a person uploads (#1326).
