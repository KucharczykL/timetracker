# The Library screens

Issue: [#1352](https://github.com/KucharczykL/timetracker/issues/1352),
member M3 of the
[Access and Purchases wave](2026-09-28-access-and-purchases-wave-design.md).
It needs [the LibraryEntry aggregate](2026-09-29-issue-719-libraryentry-aggregate-design.md)
and [a copy's end and resume](2026-09-29-issue-721-entry-access-end-design.md).

## Words

A person has a copy, or no longer has it. The screens say only this.
"Library" names the tab, the section and the Add page. "Copy" names one
row, and every answered sentence says "copy". "Entry" is the word in
code, events and the API.

## Game detail

The Library section shows the copies the person has now. Copies of one
version (`release_words`) share one name above their rows
(`SummaryGroup`). A row states access, format and "since <day>". A note
shows as a `Chip`, clipped to about four words.

A copy that the person no longer has leaves the section. One centred line
counts these copies and points at View all. View all opens the Library
tab, filtered to the game.

**Add to library** is a split button. The button adds a copy in one
click: default version, Owned, Digital, today. The menu opens the Add
page.

## The row menu

Game detail and the Library tab use one menu, `entry_row_menu`:

| Copy | Submenu | One click | Page |
|---|---|---|---|
| had | I no longer have it | Just mark it gone | With details… |
| ended | I have it again | Just add it back | With details… |

An ended copy also offers "Edit how it left…". Every copy offers "Edit…"
and "Remove…". A trailing "…" opens a page.

A one-click act posts a submission key, so a double press records once.
It states today, and its toast offers Undo. A one-click end states the
way **Not said** (`EndWay.UNSTATED`). No screen prints that way: the day
stands alone.

## The pages

Add, Edit, I no longer have it, Edit how it left and I have it again are
pages over `AddForm`, each with Cancel. A refusal renders the page again
with its sentence. #1385 moves them into a dialog.

## The Library tab

The Games page has two tabs, Games and Library. The Library tab lists
every copy through `LibraryEntryFilter`, mode `entries`, with presets,
the builder, and the tray acts `entry.edit` and `entry.remove`, each
with Undo.

## The Games tab

The Access column is off by default. `AccessBadge` shows a cloud for a
digital copy, a disc for a physical copy, and a dashed ring for an
unknown format. A filled glyph means the person has the copy now. The
badge opens a popover with one sentence, for example "You have 2
versions, and had 3". `GameFilter` gains `access`, `format`,
`entry_count` and `entry_filter`.

## Not in this issue

- Purchases in the section and the tab (P5).
- Bulk end of access (#1355).
- A library's own Release under a shared Edition (#1375).
