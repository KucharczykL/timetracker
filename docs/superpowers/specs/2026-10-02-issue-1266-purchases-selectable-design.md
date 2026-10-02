# The Purchases list is selectable; the conversion is reviewed

Issue: [#1266](https://github.com/KucharczykL/timetracker/issues/1266),
member P5b2 of the
[Access and Purchases wave](2026-09-28-access-and-purchases-wave-design.md).

## The acts

The Purchases list is selectable. Its tray offers two acts. Both undo
through `EventRows(Purchase)`.

- `purchase.remove` lives in `games/bulk_removal.py`. It runs
  `remove_purchase`. Its inverse runs `restore_purchase`, which requests a
  revaluation.
- `purchase.edit` lives in `games/bulk_purchase_edit.py`. It states kind,
  price, purchase day and note. An empty field keeps the row's value.
  Price offers Keep, Paid, Free and Unknown. The note's ⊘ states no note.
  The day keeps the row's own `purchase_note`. One `DescribePurchase`
  dispatch writes each row.

`games/bulk_purchases.py` holds what the two acts share. It imports no
act. The list's read, `purchase_list_rows`, is in
`games/reads/purchases.py`, so the view and the acts share it without an
import cycle.

The Undo of an edit reads each fact through `purchase_fact_changes`
(`games/reads/purchase_facts.py`). `Fact.read` takes the whole event,
because the purchase day is the envelope's `effective_time`.
`payload_fact` reads one payload key.

## The kind rule

`DescribePurchase` refuses a kind change on a refunded purchase. The same
statement can take the refund back; then the change passes. The rule
exists because a `game` refund ends an owned, unended copy, and a refund
of another kind does not. A kind change would leave that end misread.

## The conversion review

`conversion_review` is a choice field on `PurchaseFilter` and
`LibraryEntryFilter`. Its words are `Category`
(`games/conversion_review.py`), less the words only the reconciliation
lists. It reads `LibraryEvent` through `Exists`: the row's key, origin
`conversion`, and the word in
`review`. An entry also matches through its purchases' events, removed
purchases included. The field refuses an unknown word.

The Library page's Purchases section lists one row per category: label,
reason, count and a link to its rows. A category with no rows is left
out. "Repurchased games" counts games with two copies or more. The count
is the target list's own read. An edit does not take a row out of its
category; a removal does.

"Hide this review" is `UserLibraryPreferences.conversion_review_hidden`,
set through `PATCH /api/library/conversion-review-hidden`. The page
reloads after the save. A hidden review reads no row.

The review serves one conversion. #1443 removes it, and keeps the field.

## The Library tab

The Purchases column lists one line per live, unrefunded purchase of the
copy, from `held_purchases`. A line is the price. A purchase of another
kind than `game`, or a named one, puts its label first.
