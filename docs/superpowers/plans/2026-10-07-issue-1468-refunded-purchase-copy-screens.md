# Plan: a refunded purchase is reachable from the copy screens (#1468)

Spec: [design](../specs/2026-10-07-issue-1468-refunded-purchase-copy-screens-design.md).
Implementation is inline, test first per task. Each `make` test run goes
under `flock "$(git rev-parse --git-common-dir)/heavy-tests.lock"`.

## Task 0: baseline render

Before any code edit, with a library that holds a refund (dev DB or a
restored dump):

```bash
make render-pages ARGS="--user NAME --out $SCRATCH/before"
```

Keep the directory for task 6.

## Task 1: one read of a copy's purchases

Files: `games/reads/purchases.py`, `tests/test_library_section.py` or
the purchases reads test that covers `held_purchases` today (grep first).

- Rename `HeldPurchases` to `CopyPurchases`; `held_purchases` becomes
  `copy_purchases`, dropping `refund_recorded_at__isnull=True`.
- Add `unrefunded(purchases: Sequence[ValuedRow]) -> list[ValuedRow]`,
  `stated(purchase, PURCHASE_REFUND) is None`. Put it beside
  `copy_purchases`.
- Tests: `copy_purchases` returns a refunded purchase in
  `PURCHASE_ORDER`; `unrefunded` drops it; a removed purchase stays out.

Gotcha: `stated` lives in `games/reads/endpoints.py`; check
`games/reads/purchases.py` does not import a views module for it.

## Task 2: the note's filters and count

Files: new `games/reads/previous_copies.py`, new
`tests/test_previous_copies.py`.

- `previous_copies_filter(game: Game) -> LibraryEntryFilter`:
  `LibraryEntryFilter.where(game=[game.pk], is_ended=True)`.
- `previous_purchases_filter(game) -> PurchaseFilter`:
  `PurchaseFilter.where(game=[game.pk])` with
  `AND=[PurchaseFilter(OR=[PurchaseFilter.where(is_refunded=True),
  PurchaseFilter(entry_filter=LibraryEntryFilter.where(is_ended=True))])]`.
  Comment why the OR nests (operator order), seven words.
- `previous_purchase_count(library, game) -> int`:
  `purchases_matching(library, previous_purchases_filter(game)).count()`.
- Parity tests (fixture: held copy with a kept and a refunded purchase,
  ended copy with a purchase, a removed purchase, a removed ended copy,
  another game's ended copy, another library's rows):
  - `previous_purchase_count` equals the Purchases list's rows for
    `filter_url(previous_purchases_filter(game))`, read through the
    client, whole queryset (set page size or count rows on one page with
    a small fixture), and equals 2 here.
  - copies count from `copy_rows(...).ended` equals the Library tab's
    rows for `filter_url(previous_copies_filter(game))`.
  - Both filters round-trip through `to_json` and
    `parse_purchase_filter` / `parse_entry_filter`.

Gotcha: game ids must be UUIDv7 (`_coerce_uuid7` refuses v4).

## Task 3: Game detail cards and note

Files: `games/views/library_cards.py`, `games/views/game.py`,
`tests/test_library_section.py`.

- `copy_rows` reads `copy_purchases`; card `purchases=` and
  `entry_row_menu(purchases=)` both take `unrefunded(...)`.
- `CopyRows` gains `previous_purchases: int`; computed by
  `previous_purchase_count` only when `held or ended`.
- `_had_copies` → `_previous_note(game, copies: CopyRows) -> Node | None`:
  one `Span` holding text and `Link(href=filter_url(...))` children.
  Grammar: `There is`/`There are` from the first nonzero count;
  `copy`/`copies`, `purchase`/`purchases`; ` and ` between; trailing
  `previously in your library.`
- `_game_section(note: Node | None)`.
- Tests (rewrite :79, :94; new):
  - copies only: sentence text (strip tags or check link text), Library
    tab `href` with `is_ended`.
  - copies and purchases (FH6 shape): "There is 1 more copy and 1 more
    purchase previously in your library."
  - purchases only (refunded add-on on a held copy): extend
    `test_a_copy_lists_its_live_unrefunded_purchases` (:194).
  - neither: no note, no View all when no copy.
  - badge counts held copies alone.
  - query-count tests (:164, :279, :313) stay green.

Gotcha: assert on text with markup in mind; add a small helper that
strips tags from the note `P` rather than matching raw HTML across `<a>`.

## Task 4: Library tab

Files: `games/views/library_list.py`, `tests/test_library_list.py`.

- One `copy_purchases` read; column `price_lines(all)`; menu
  `purchases=unrefunded(...)`.
- Tests: ended copy's row prints its refunded price; that copy's menu
  carries no submenu for the refunded purchase (no
  `purchase-menu-<pk>` / edit_purchase URL for it); a held copy's
  refunded add-on prints plain.

## Task 5: e2e

File: `e2e/test_library_section_e2e.py:118-120`. Update to the new text
("There is 1 more copy previously in your library."). Add one check that
the "1 more copy" link lands on the Library tab showing the ended copy.

## Task 6: render diff

`make render-pages` into `$SCRATCH/after`, `diff -r before after`.
Attribute every hunk to one of the spec's three classes; anything else is
a defect to fix before the gate.

## Task 7: docs and gate

Per the implement-issue skill's step 8: delete this plan, rewrite the
spec timeless, trim comments, update CLAUDE.md (two sentences named in
the spec), the 1266 spec line, the wave doc's #1468 entry; rewrite the
issue body's Outcome to the decided design. `make format`,
`make lint-fix`, `make format-check`, `make vale`, then full `make check`
under the lock, draft PR, five-agent review.
