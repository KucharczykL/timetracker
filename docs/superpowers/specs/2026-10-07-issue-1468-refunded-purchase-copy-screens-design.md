# The copy screens reach every purchase (#1468)

Part of the [Access and Purchases wave](2026-09-28-access-and-purchases-wave-design.md).

## Game detail

A copy card shows one copy that the library has now. It shows the live
purchases of that copy that have no refund. The copy's menu carries the
acts of the same purchases.

The Library section ends with one sentence. The sentence counts what the
cards do not show. Each count is a link to the list that shows exactly
those rows.

| Count | Link |
|---|---|
| `N more copies`: live copies with a standing end of access | Library tab, `previous_copies_filter` |
| `(with N purchases)`: live purchases of those copies | Purchases list, `previous_copy_purchases_filter` |
| `N more purchases`: refunded live purchases of copies had now | Purchases list, `refunded_held_purchases_filter` |

A refund of a `game` purchase ends its copy. Thus that purchase counts
in the parenthesis, not in the last count.

A count of zero does not show. The parenthesis shows only after the copies
count. The first count shown sets "There is" or "There are". When no count
shows, the section has no sentence. Examples:

- There is 1 more copy (with 1 purchase) previously in your library.
- There is 1 more copy (with 1 purchase) and 1 more purchase previously in
  your library.
- There is 1 more purchase previously in your library.

The sentence is one `Span` with `Link` children. The note's `P` is a flex
row, so the sentence must be one inline item.

The section badge counts the copies that the library has now.

## One filter, one count

`games/reads/previous_copies.py` holds the three filters. The count of an
ended copy's purchases is `purchase_count`: `purchases_matching(library,
filter).count()`, the base of the Purchases list. `copy_rows` runs it only
when an ended copy exists.

Two counts come from rows that `copy_rows` already reads. The copies count
is the `copy_end` loop. `copy_end` and the `is_ended` facet read the same
marker. The refunded count is the purchases that `unrefunded` removes from
the cards. Thus each count equals what the cards leave out.

A parity test holds each count equal to the rows of its list.

## Library tab

The Purchases column prints every live purchase of the copy. A refunded
purchase prints with no mark: the Access ended column states the refund of
a game purchase. A refund of another kind shows only on the Purchases
list. The copy's menu carries the acts of the unrefunded
purchases only.

## Reads

`copy_purchases` reads the live purchases of each copy, refunded included,
valued and in `PURCHASE_ORDER`. Both screens read it once. `unrefunded`
removes the purchases with a stated refund. Cards and menus read
`card_purchases`, which applies `unrefunded` to one copy.

## Statistics

No figure changes. Each figure states its own refund rule.
