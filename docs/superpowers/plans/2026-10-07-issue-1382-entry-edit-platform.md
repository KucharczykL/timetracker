# Plan: bulk Edit states a platform on many copies (#1382)

Spec: `docs/superpowers/specs/2026-10-07-issue-1382-entry-edit-platform-design.md`.
Implementation inline, TDD per task.

## Task 1 — the read

- `games/reads/releases.py`: `release_on_platform(library, entry, platform_id)
  -> PlatformRelease`, where `PlatformRelease = OnPlatform | NoRelease |
  SeveralReleases` (frozen dataclasses; `OnPlatform.release`).
  - step 1: `entry.release.platform_id == platform_id` → `OnPlatform(entry.release)`.
  - candidates: `game_releases(library, entry.player_game.game)` filtered on
    `platform_id` (or `platform__isnull=True`), `platform__removed_at__isnull`
    (NULL platform passes), `edition__kind=entry.release.edition.kind`.
  - own Edition subset, else all; 1 → OnPlatform, >1 → Several, 0 → None.
- `games/bulk_entries.py`: `select_related(..., "release__edition")`.
- Tests (new `tests/test_release_on_platform.py`): same platform; own
  Edition wins; two in own Edition; one elsewhere; none; removed Release
  excluded; prerelease vs full kind; Unspecified resolves NULL platform;
  shared catalog game's Release found.

## Task 2 — the write and the facts

- `games/writes/libraryentry.py::describe_entry` gains `release_id`.
- `games/reads/entry_facts.py`: `_RELEASE` fact, `_release_key` parses
  `Reference["id"]` to `uuid.UUID`, None when unreadable; `EntryFactChanges.release`;
  `changed_any`.

## Task 3 — the act

`games/bulk_entry_edit.py`:
- `StatedPlatform`, `EntryEditJson.platform`, `EntryEditStatement.platform`
  (last), encode/decode (`"platform" in stated`, null → `StatedPlatform(None)`,
  bad key → `statement_unreadable`), `of`, `__post_init__`, `NOTHING_STATED`.
- Form: `library` kw, `platform` field declared first, queryset and resolver
  set in `__init__`, placeholder keyed on `platform_id`; `clean` counts it;
  `statement()` maps `Platform | None | KEEP`.
- `offer_edit`/`settle_edit` pass `library`.
- `EntryFacts` (access, format, note, release_id); `_state` takes it.
- `edit_one`: platform stated → re-read platform mark (`PLATFORM_REMOVED`),
  `release_on_platform`, refusals `NO_RELEASE_ON_PLATFORM` /
  `SEVERAL_RELEASES_ON_PLATFORM`; inside `answered(SUBJECT)`.
- `edit_back`: release restated through `restated`, overwrite logged, `EntryFacts`.
- Tests in `tests/test_bulk_entry_acts.py`: form field order/placeholder/⊘;
  statement round trip incl. legacy JSON without `platform`; batch moves,
  keeps, refuses (tally + reasons); re-run chunk counts done; platform +
  access in one dispatch; Undo restores; Undo of removed Release refuses;
  overwrite logged.

## Task 4 — e2e

`e2e/test_library_tab_e2e.py`: second platform with a Release per game;
Edit dialog picks it; rows show the new platform.

## Gotchas

- `EntryEditStatement` positional calls in tests: append field last.
- Rerun idempotency: step 1 must state the copy's own Release.
- `Http404`/non-409 in run fails the batch: refusals must be `CommandRejected`.
- Tests that POST through bulk views need `transaction=True`.
