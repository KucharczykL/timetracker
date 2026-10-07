# Bulk Edit states a platform on many copies (#1382)

Part of the [Access and Purchases wave](2026-09-28-access-and-purchases-wave-design.md).

## Problem

A copy's platform is its Release. `DescribeEntry` takes `release_id`, so one
copy moves to another Release on its own edit form. The Library tab's bulk
Edit (`entry.edit`, `games/bulk_entry_edit.py`) states access, format and
note only. Moving many copies onto one platform is one edit per copy.

## Decisions

1. **One more field on `entry.edit`.** `BulkEntryEditForm` gains `platform`,
   first in the form: Platform, Access, Format, Note, the order the preview
   columns (Game, Platform, Access, Format) read. #1355 shipped `entry.end`
   as its own act, so the two acts share no form.
2. **The field is a platform picker with ⊘.** A `ModelChoiceField` on
   `Platform.objects.visible_to(library)`, widget `UnsetWidget(
   SearchSelectWidget(search_url=PLATFORM_SEARCH_URL), none_label=
   UNSPECIFIED_PLATFORM)`, resolver `partial(platform_options,
   library=library)`, `invalid_choice` sentence `PLATFORM_GONE` (`games/catalog_form.py`). The form
   therefore takes `library`, and `offer_edit` and `settle_edit` pass it, as
   `BulkEditForm` in `games/bulk_session_edit.py` does. Empty keeps. ⊘ states
   Unspecified: the Release whose `platform` is NULL. No create row and no +:
   a new platform has no Release on any game, so every row would refuse. The
   placeholder keys on `row.release.platform_id` and shows the name through
   `platform_words`, so two platforms of one name read mixed.
3. **The statement states a platform, not a Release.** `EntryEditStatement`
   gains `platform: StatedPlatform | None`, appended last so positional
   calls keep their meaning. `StatedPlatform(platform_id: PlatformId | None)`, a plain frozen dataclass in `games/bulk_entry_edit.py` (no command takes it, so it is no `FingerprintedValue`),
   tells Unspecified (`None` inside) from keep (`None` outside). Wire:
   `"platform": "<uuid>"` or `"platform": null`; `EntryEditJson` gains the
   key, and decode reads `"platform" in stated`, so a batch carried before
   this change still decodes. `__post_init__`, `.of()` and
   `NOTHING_STATED` ("Choose a platform, an access, a format or a note.")
   count the new fact.
4. **Each row resolves its own Release, in `run`.** The choice is settled
   once for the batch, but each game has its own Releases. `edit_one`
   resolves, per row, through `release_on_platform` (below), then states
   access, format, note and `release_id` in one `DescribeEntry` dispatch, so
   a row never commits half.
5. **Resolution order.** For a copy and a stated platform, the candidates
   are the game's live Releases (`game_releases`) on that platform whose
   platform is not removed, in Editions of the copy's own `EditionKind`:
   1. The copy's Release is on that platform: the answer is the copy's own
      Release. The dispatch states it anyway: a row re-run under its key
      after its first run committed must fingerprint the same, or the
      dispatcher answers `IdempotencyKeyMismatch`. `DescribeEntry` appends
      nothing for an unchanged Release.
   2. The copy's own Edition holds candidates: exactly one is the answer;
      several refuse.
   3. Else every candidate: exactly one is the answer; several refuse; none
      refuses.
   The kind filter keeps a copy on a prerelease Edition off a full Edition,
   and the reverse. A copy's `access` (`demo` included) plays no part. Step 2 keeps a deluxe copy on its deluxe Edition where one
   exists. The issue's "two Editions" ambiguity remains where the copy's own
   Edition holds no candidate.
6. **Refusals are per row, with constant sentences.** A `CommandRejected`
   inside `answered(SUBJECT)` in `edit_one`; the runner logs the row's key
   and sentence and runs the rest. The tally keeps each distinct sentence
   once and the toast prints them all, so the sentences name no game:
   - removed: `PLATFORM_REMOVED`, "That platform is removed." The batch
     runs on the cluster after the press, so the stated platform's mark is
     read again per row.
   - none: `NO_RELEASE_ON_PLATFORM`, "A copy's game has no release on that
     platform." It names no remedy: a shared game takes no Release yet.
   - several: `SEVERAL_RELEASES_ON_PLATFORM`, "A copy's game has several
     releases on that platform. Choose one on the copy's own edit form."
   The message names the copy, game and platform keys. The act never
   creates a Release: catalog rows are stated through the graph form, and a
   shared Game takes none until #1375.
7. **No caution.** A `Caution` reads rows before the choice, so it cannot
   count the rows a platform will refuse.
8. **Undo restates the release.** `entry_facts.py` gains a release fact over
   `LIBRARYENTRY_CREATED` and `LIBRARYENTRY_RELEASE_CHANGED`, both of which
   carry the Release as a `Reference` under `"release"`; the fact parses its
   `id` to a `uuid.UUID`, and an unparseable one reads None, which
   `fact_change` raises as `RowUnreadable`. `changed_any` counts it.
   `edit_back` restates `release_id` beside the other three through
   `restated`, logs an overwrite as they do, and dispatches one
   `DescribeEntry`. A Release removed since refuses through
   `refuse_a_removed_release`, as the copy's own edit form does.
9. **The dispatch shape.** The forward statement holds a platform and the
   inverse a Release, so `_state` takes a new `EntryFacts(access, format,
   note, release_id)`, the facts one dispatch states. `describe_entry`
   (`games/writes/libraryentry.py`) gains `release_id`.
10. **Sessions and records keep their Release.** A session or record names
    a Release; moving the copy leaves it naming the old one, which no live
    copy may hold any more. The per-copy edit form does the same today;
    `stated_release` checks only a new statement.

## Read

`release_on_platform` lives in `games/reads/releases.py` beside
`game_releases`. It answers a tagged result (`OnPlatform(release)`,
`NoRelease`, `SeveralReleases`) so the act owns the sentences. One query
reads the candidates; the copy's Edition splits them in Python.
`entry_resolution` adds `release__edition` to its `select_related`, so
the copy's Edition costs no query.

## Tests

- Form: the field leads; empty keeps; ⊘ states `StatedPlatform(None)`; a
  platform alone passes `NOTHING_STATED`; placeholder "Keep: <name>" and
  "Keep: mixed".
- Statement round trip: encode/decode with a platform, with `null`, refusal
  of a malformed key.
- Resolution: same platform keeps; own Edition wins over another Edition;
  two in own Edition refuse; a copy on a prerelease Edition ignores a full Edition's Release; a removed stated platform refuses; none in own, one elsewhere moves; none
  anywhere refuses; a removed Release is not a candidate; Unspecified
  resolves the NULL-platform Release.
- Act: a batch over three copies moves one, keeps one, refuses one; the
  tally counts each and the toast states the sentence once. A re-run chunk
  whose first run committed counts the row done, not refused. Platform and access in one batch land in one
  dispatch per row.
- Undo: restores the earlier Release; a Release removed since refuses the
  row; a later change is overwritten and logged.
- e2e: the Library tab's Edit dialog picks a platform and the rows move.

## Follow-up issues to file

None.
