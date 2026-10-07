# A refunded purchase is reachable from the copy screens (#1468)

Part of the [Access and Purchases wave](2026-09-28-access-and-purchases-wave-design.md).

## Problem

Forza Horizon 6: the Standard copy was bought on 19/05, refunded on 21/05,
and the Premium copy was bought the same day. Neither copy screen shows the
refunded purchase:

- Game detail's Library section lists the copies held now. Each copy shows
  `held_purchases` (`games/reads/purchases.py`): live, **unrefunded**
  purchases. The ended copy is one sentence, "There is 1 more copy
  previously in your library, click View all to manage it."
  (`_had_copies`, `games/views/game.py`).
- The Library tab lists every copy. Its Purchases column reads the same
  `held_purchases`, so the ended copy's row shows "Refunded · 21/05/2026"
  under Access ended and nothing under Purchases.

## Decisions

The person decided the screen. These decisions replace the issue body's
Outcome (struck-through refund lines, a disclosure of previous copies).

### Game detail: the cards do not change

A copy card shows the copies held now with their live, unrefunded purchases,
as before. A refund does not appear on a card.

### Game detail: the note counts what the cards do not show

The note is one sentence with up to two counts. Each count shows only when
it is not zero. Each count is a link.

| Copies | Purchases | Sentence |
|---|---|---|
| 1 | 0 | There is [1 more copy] previously in your library. |
| 2 | 1 | There are [2 more copies] and [1 more purchase] previously in your library. |
| 0 | 1 | There is [1 more purchase] previously in your library. |
| 0 | 0 | No note. |

The verb agrees with the first count. Brackets mark the link text. The
sentence has no "click": the link text names the destination. The header's
View all stays, and its rule does not change (it shows when the section
count or the note is not zero). The section badge counts the copies held
now.

- **Copies** counts live copies of the game with a standing end of access,
  as today (`copy_end`). Link: the Library tab,
  `LibraryEntryFilter.where(game=[id], is_ended=True)`. Both are quick
  facets, so the bar stays editable.
- **Purchases** counts every live purchase of the game that no card shows:
  a purchase with a refund stated, or a purchase whose copy has a standing
  end. FH6 reads "There is 1 more copy and 1 more purchase previously in
  your library." Link: the Purchases list, filtered to
  `game AND (is_refunded OR entry_filter.is_ended)`.

The purchase link nests the OR one level down:
`PurchaseFilter.where(game=[id])` with
`AND=[PurchaseFilter(OR=[is_refunded, entry_filter(is_ended)])]`.
`OperatorFilter` applies a node's own criteria first, then `AND`, then
`OR`. An `OR` beside `game` on one node would therefore read
`game OR refunded OR ended`. A scratch run against the dev database
compiled the nested form to
`game_id IN (…) AND (refund_recorded_at IS NOT NULL OR entry_id IN
(… access_end_recorded_at IS NOT NULL))`. The Purchases list shows
"Advanced filter active" for this link. `game` is no quick facet in
purchases mode, so a game-only link would show it too. The person accepted
this for a count that equals the rows.

The purchase count is `purchases_matching(library, filter).count()`
(`games/reads/purchase_figures.py`): the link's own filter over the
Purchases list's own base, as every statistics link counts. Count and link
cannot drift. The copies count stays the `copy_end` loop in
`copy_rows`; `copy_end` and `is_ended` both read `access_end_recorded_at`.
A parity test holds each count equal to its list's whole queryset.

### Library tab: every live purchase, plain

The Purchases column prints every live purchase of the copy, refunded
included, with no marking. The row's Access ended column already says
"Refunded · day". A refunded add-on on a held copy prints plain too. The
person accepted this.

### Unchanged

Statistics, the Purchases list, and the copy's menu on both screens: it
carries the acts of the copy's unrefunded purchases alone, as today.

## Design

- `games/reads/purchases.py`
  - `copy_purchases(library, entry_ids) -> CopyPurchases`: each copy's live
    purchases, refunded included, valued and in `PURCHASE_ORDER`. It
    replaces `held_purchases`, so both screens make one read.
  - `unrefunded(purchases) -> Sequence[ValuedRow]`: the purchases with no
    refund stated. The cards and both menus read it.
- `games/reads/previous_copies.py`, new: what the note counts and links.
  - `previous_copies_filter(game) -> LibraryEntryFilter`.
  - `previous_purchases_filter(game) -> PurchaseFilter`.
  - `previous_purchase_count(library, game) -> int`: `purchases_matching`
    over that filter. `games.filters` imports neither reads module at
    module level, so no cycle.
- `games/views/library_cards.py`: `copy_rows` reads `copy_purchases`,
  passes `unrefunded(...)` to card and menu, and `CopyRows` gains
  `previous_purchases: int`. A game with no live copy has no live
  purchase, so `copy_rows` skips the count query when it loads no entry.
- `games/views/game.py`: `_had_copies(had: int)` becomes
  `_previous_note(game, copies) -> Node | None`. `_game_section`'s `note`
  takes a `Node`. The sentence is one `Span` with `Link`
  (`common/components/primitives.py`) children, so the note's flex `P`
  holds two items, the icon and the sentence, and spaces survive.
- `games/views/library_list.py`: the Purchases column reads
  `copy_purchases`; the menu reads `unrefunded(...)`.

## Tests

- `tests/test_library_section.py`: the four sentence rows above, each link's
  `href`, and the badge counting held copies alone. Rewrite the substring
  checks at :79 and :94, which the link markup breaks. Extend
  `test_a_copy_lists_its_live_unrefunded_purchases` (:194) with the
  "1 more purchase" sentence.
- Parity: for a fixture with a held copy, a refunded purchase on it, an
  ended copy with a sold purchase, a removed purchase, and another game,
  each count equals the rows its link's filter returns.
- `tests/test_library_list.py`: the ended copy's row prints its refunded
  price, and its menu holds no submenu for that purchase.
- `e2e/test_library_section_e2e.py:119`: the new sentence text.
- `make render-pages` before and after. Expected difference classes:
  every game with an ended copy (the sentence loses "click View all…" and
  gains a link); games with a refunded purchase on a held copy or a
  purchase on an ended copy (the purchase count); Library tab rows of
  those copies (new Purchases lines). Any other difference is a defect.

## Docs

- CLAUDE.md: the Library tab's Purchases column prints every live
  purchase; the Game detail sentence naming `held_purchases` names
  `copy_purchases` and `unrefunded`, and the note.
- `2026-10-02-issue-1266-purchases-selectable-design.md`: the column no
  longer reads `held_purchases`.
- The wave doc's #1468 entry states these decisions, not the struck-through
  disclosure.

## Follow-up issues to file

None.
