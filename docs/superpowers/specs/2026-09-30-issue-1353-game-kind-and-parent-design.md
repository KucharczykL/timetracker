# Game kind and parent, Edition kind

Issue: [#1353](https://github.com/KucharczykL/timetracker/issues/1353), member
M7 of the [Access and Purchases wave](2026-09-28-access-and-purchases-wave-design.md).
Charter: [Catalog identity](2026-08-09-timetracker-overhaul-design.md#catalog-identity).

## Purpose

A Game states what work it is. An add-on names the main game that it
belongs to. An Edition states if it is the full game or a prerelease: a
demo, a beta or a playtest.

## Words

- `GameKind`: `main`, `dlc`, `expansion`, `standalone_expansion`. These
  are IGDB's `game_type` words. The default is `main`.
- `ADDON_KINDS` are the three kinds that are not `main`.
- `EditionKind`: `full`, `prerelease`. The default is `full`. Early
  Access is `full`.

## Storage

`Game.kind`, `Game.parent` and `Edition.kind`. `parent` is a self key with
`RESTRICT` and no reverse accessor. Four CHECKs hold the words and the rule
that only an add-on names a parent. The database admits more than the
rules do. `audit_library_ownership` reports a parent of another library.

## The rules

`state_addon` in `games/catalog_addons.py` sets `kind` and `parent`. The
caller saves. It runs inside the caller's transaction and locks the Game
and its parent in key order. It refuses with `AddonRefused` on one field:

1. A main game with a parent.
2. An add-on with no parent.
3. The Game as its own parent.
4. A private parent of another library.
5. A removed parent that is not the stored parent.
6. A parent that is not `main`.
7. A main game that an add-on names, a removed add-on included.

A later removal of the parent does not cascade. The add-on reads the
parent as removed.

## Screens

- The Game form has Kind and Add-on of. `<game-addon>` hides Add-on of
  for a main game. A shared Game has no form.
- Each Edition row has a Kind select. `edition_words` names an unnamed
  prerelease "Prerelease".
- Game detail shows "Add-on of" with a kind chip. The parent is a link
  only where the library tracks it. A main game has an Add-ons section
  that lists the tracked add-ons.
- A prerelease Edition shows the Editions table, with a chip.

## The Games list

`games_list_base` gives main games. When a filter names `kind` or
`parent` at any level, it gives every kind. The list, its bulk scope and
`/api/filter/count` read it. The list has a Kind facet and a Kind column.

A link whose figure counts every kind states `GameFilter.every_kind()`.
Under an `OR`, each member states it, because a node ORs its members with
its own leaves. `narrowing()` ignores `kind` and `parent`.

## Limits

- A shared Game's kind and parent have no write path until #782.
- P4 (#723) states the DLC Games through `state_addon`.
- The list does not nest add-ons under their parent.
