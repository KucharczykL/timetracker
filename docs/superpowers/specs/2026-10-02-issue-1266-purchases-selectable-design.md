# The Purchases list is selectable; the conversion is reviewed

Issue: [#1266](https://github.com/KucharczykL/timetracker/issues/1266),
member P5b2 of the
[Access and Purchases wave](2026-09-28-access-and-purchases-wave-design.md)
stack (#1409), on top of
[Every purchase write](2026-10-01-issue-724-purchase-writes-design.md).

## Scope

1. The Purchases list is selectable. Its tray offers Edit… and Remove.
2. Two bulk acts: `purchase.edit` and `purchase.remove`, both undone
   through `EventRows(Purchase)`.
3. The `conversion_review` filter field on `PurchaseFilter` and
   `LibraryEntryFilter`.
4. Conversion review rows in the Library page's Purchases section, with a
   "Hide this review" preference.
5. A Purchases column on the Library tab.

The row menu stays as P5b built it: Edit purchase…, Refund, Remove
purchase…. The Actions column retired with P5a.

## Decisions

**The user's rulings (2026-10-02).**

- Bulk Edit states Kind, Price, Purchased and Note. An empty field keeps
  its value.
- The Library tab's Purchases column has one line per purchase.
- The review rows sit inside the Purchases section, not in a section of
  their own.

**The organizer's ruling (2026-10-02).** One `conversion_review` field
reaches each category's rows. It is a link target and no quick facet. Its
words are `Category`'s, and they stay stable once shipped.

### `Category` moves out of the backfill

`Category` moves from `games/backfill/purchase_plan.py` to
`games/conversion_review.py`. Its importers follow: the backfill
(`purchase.py`, `purchase_plan.py`, `purchase_reconciliation.py`) and
`games/purchase_parity.py`. A filter field
outlives the conversion pass, and P5c may delete the backfill. The module
also holds:

- `REVIEW_WORDS`: per category, a label, a one-line reason and a target
  list.
- `REVIEWED`: every category except `skipped_removed_game`, which appends
  no event.

These are the field's choices. Each category targets one list:

- A price category targets the Purchases list: `unknown_price`,
  `epic_free` and `quantized`. The first two are owned rows, so each has
  a purchase. A non-owned row priced under half a cent is `quantized`
  and has none; it has no price left to review, so the list omits it.
- Every other category targets the Library tab. A non-owned free row has
  no purchase, so only its copy can carry the tag.

An attached purchase (a pass or an upgrade on the base's held copy)
appends `purchase.created` alone. Its tag never reaches the entry's own
events. So the entry filter's `Exists` matches an event of the entry,
or an event of any purchase that names the entry. With that, every
tagged row has its copy on the Library tab.

**The review counts history, not open work.** The tag sits on the
conversion's events forever. A purchase whose price is stated later
still counts as `unknown_price`. The rows say what the conversion shaped;
"Hide this review" closes them once they are read.

### The filter field

`conversion_review` is a `ChoiceCriterion`. Its handler compiles one
`Exists` per word over `LibraryEvent`, filtered on these four:

- `library` equal to the row's library;
- `aggregate_id` equal to `OuterRef("pk")`;
- `source_metadata__origin` equal to `"conversion"`;
- `source_metadata__review__contains` the word.

The index `(library, aggregate_id)` serves it. A row holds a set of
categories, so the handler composes the modifiers as a set does:

- `INCLUDES` or `EQUALS` is any of the words.
- `INCLUDES_ALL` is all of them.
- `EXCLUDES` or `NOT_EQUALS` is none of them.
- `excludes` adds a "none of these" conjunct.
- `IS_NULL` is no category at all, and `NOT_NULL` is any category.
- `INCLUDES_ONLY` raises `FilterError`, as `kind` does. The builder
  still offers it, since `Modifier.for_multi()` lists it for every set
  field.

The field's `choices` are built from `REVIEW_WORDS`, since
`_word_choices` takes `TextChoices` and `Category` is a `StrEnum`.

The two filters share one builder: `conversion_review_field(aggregate)`,
where `aggregate` names the event keys the row reaches. A purchase reaches
its own key. An entry reaches its own key and its purchases' keys.

### Review rows

`conversion_review_rows(library) -> tuple[ReviewRow, ...]` builds the
rows. A `ReviewRow` holds label, reason, count and `url`. The count is the
target list's own read, the same filter, `.count()`. A count of zero
drops the row. One `exists()` first decides whether the library holds
any conversion event; without one, the review renders nothing.

A further row, "Repurchased games", counts games with two copies or more
(`GameFilter.entry_count`) and links to the Games list, as the wave says.

The rows render as a `SummaryList` of `SummaryRow`s:

- label: the category label;
- subtitle: the reason;
- value: `SummaryValue(count, url)`, the link to the rows.

`SummaryRow.actions` render behind a ⋯ menu, so a lone Review action
would hide the link the count already is. The list follows the
Purchases section's `SummaryRow` in one `Fragment`. When the review is
hidden, no row is read and no row renders. The checkbox stays.

### The preference

`UserLibraryPreferences.conversion_review_hidden` is a `BooleanField`
that defaults to false. It needs a migration.

The live-settings client fills `/api/library/__key__` with the field key.
A second literal route, `PATCH /api/library/conversion-review-hidden`,
fills that template exactly as `default-device` does. Its body is
`{value: bool}` and its answer `{key, value, source, locked, namespace}`.
The default-device route keeps its schemas and its tests. Its docstring
changes: each preference is one literal route named by its key.

- A second `LibraryPreferencesForm`-style form holds the checkbox, with a
  `SettingFieldState` keyed `conversion-review-hidden`.
- The checkbox widget carries `data-reload-after-save`. The client
  reloads on that attribute alone (`ts/elements/live-setting-fields.ts`).
  The route sets `X-Reload`, so the toast waits for the reloaded page.

### The acts' shared half

`games/bulk_purchases.py` imports no act, as `bulk_entries.py` does. It
holds `purchase_scope`, `purchase_resolution`, `removed_purchase` and the
preview. `purchase_list_rows`, `_PURCHASE_PATHS` and `ListedPurchase`
move from `games/views/purchase.py` to `games/reads/purchases.py`, because
the view imports the acts for its tray. The act table's foot imports the
acts, so an act importing the view would cycle
(`tests/test_bulk_act_imports.py`). `purchase.edit` lives in
`games/bulk_purchase_edit.py`, and `purchase.remove` beside its siblings
in `games/bulk_removal.py`.

### `purchase.remove`

- `scope` is `purchase_scope`: `narrowed(purchase_list_rows(library),
  …, parse_purchase_filter)`. It is the list's own read.
- `resolve` reads live purchases with the paths the cells read, in game
  display order, then `id`.
- `resolve` reads through `with_valuation`, because `PurchaseAmount`
  refuses a row without the alias.
- `run` is `remove_purchase`. `inverse` is `restore_purchase`.
- Both writes gain `source_metadata`, keyword only.
- The preview columns are Name, Kind, Amount and Purchased.

### `purchase.edit`

`PurchaseEditStatement` holds:

- `kind`: `PurchaseKind`, or `None` to keep;
- `price`: `StatedPrice`, or `None` to keep;
- `purchased`: `TemporalValue`, or `None` to keep;
- `note`: `str`, or `None` to keep.

It encodes and decodes like `EntryEditStatement`. Price travels as
`{"amount": "12.50" | null, "currency": "EUR" | ""}`.

**The form.** `BulkPurchaseEditForm` composes three parts. `offer_edit`
renders it through `FormFields(form, groups=[price_group(), …],
presentations=price_presentations())`, because the amount and currency
rows show only inside the `group/price` ancestor. KEEP arrives through
`initial=`, since `PriceFields.__init__` defaults the price to Paid.

- `PriceFields`, with `price_choices` led by `PriceChoice.KEEP` ("Keep").
  KEEP is the initial choice. The form adds a "Keep: mixed" or
  "Keep: 12.50 EUR" hint as help text. `_clean_price` already ignores
  amount and currency for any choice but Paid and Free.
- Kind and Note, as on the Library tab's bulk Edit.
- Purchased, a `TemporalFormField` that is not required, with no ⊘.

An undated purchase is a gap the conversion left, never a statement to
make in bulk.

`PriceFields.price_statement()` keeps its type; its `None` means No
purchase. Its KEEP case raises `ValueError`, as Add purchase's NONE case
does. The bulk form reads KEEP itself, in `price_change() -> StatedPrice
| None`, where `None` keeps.

**Run.** One `DescribePurchase` dispatch per row, through
`restate_purchase`, which gains `idempotency_key` and `source_metadata`.
The day keeps the row's own `purchase_note`, so an unchanged day answers
`Unchanged`. `RestatedPurchase` carries its `CommandResult`, so the
tally reads `RowOutcome.of`: a replayed chunk counts as moved, as every
act counts it.

**A kind change beside a standing refund is refused.** A `game` refund
ends its Owned copy, and a pass refund does not. So `DescribePurchase`
refuses a kind change on a refunded purchase unless the same statement
voids the refund. The sentence is "Take the refund back before changing
what this purchase bought." The single Edit page shares this rule, and
each refused bulk row shows it.

**Undo.** `purchase_fact_changes(library, purchase_id, batch)` lives in
`games/reads/purchase_facts.py` and reads four facts.

`Fact.read` changes from a payload value to the whole event. The
purchase day lives in `effective_time`, not in the payload, so a payload
reader cannot reach it. `payload_fact(key, parse)` keeps the seven
existing facts (four in `playergame_facts.py`, three in
`entry_facts.py`) one line each. `Fact.key` goes; `_value`'s refusal
names the event type and sequence and quotes the payload. The new facts are these:

- `kind` and `note`, payload facts;
- `price`, read as a `StatedPrice`, where null is `UNKNOWN_PRICE`;
- `purchased`, read as `ActStatement(effective_time, note)`, the
  creation's `purchase_note` or the correction's `note`.

`edit_back` restates each changed fact back, as `entry.edit` does.

### The Purchases list

- Rows carry `key=str(purchase.pk)` beside the existing `id=`, which
  five tests read.
- `selection` holds the filter, the CSRF token, and
  `tray_actions(PURCHASE_EDIT.name, REMOVE_PURCHASE.name, origin=origin)`.

### The Library tab column

`Column("Purchases", key="purchases", priority=1)`, with no sort key, sits after
Format. Each cell is a stack of one line per live, unrefunded purchase,
read from `held_purchases`, the same read the menu uses:

- `price_words(purchase)`;
- prefixed with `purchase_label(purchase) · ` when the kind is not
  `game` or the purchase has a name.

A copy with no purchase gets an empty cell.

## Gotchas

- `restate_purchase` with only `purchased` must keep the purchase note.
- `held_purchases` hides refunded purchases. The column follows it, so a
  refunded game purchase shows nothing there: its copy ended.
- The settings JS reads `patch_url_template="/api/library/__key__"`.
  Both literal routes fit it.
- The review departs from the wave's first draft: demo editions, created
  releases and mixed games target the Library tab through the field,
  not the Games list or inline rows. The organizer amended the wave doc
  to the field.
- `make render-pages`: the Purchases list gains checkboxes and the tray,
  the Library tab gains a column, and the Library page gains the review.

## Follow-up issues to file

None yet.
