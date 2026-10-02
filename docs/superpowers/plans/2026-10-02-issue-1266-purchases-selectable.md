# Purchases selectable, conversion reviewed — implementation plan

**Goal:** P5b2 of #1409: Purchases list tray (Edit…, Remove), the
`conversion_review` field, the review rows with their Hide preference,
the Library tab's Purchases column.

**Spec:** docs/superpowers/specs/2026-10-02-issue-1266-purchases-selectable-design.md

Implementation is inline. Each test run is wrapped in
`flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make test ARGS=…`.
Before each commit: `make format`, `make lint-fix`, `make format-check`,
`make vale`, each in its own call, read by exit code.

## Global constraints

- Comments ≤ 7 words, no issue references.
- Complete-word identifiers; PEP 695 aliases for primitive roles.
- `render_page`, components, `action_url` with origin; no `reverse()` in
  links to mutating views.
- No dispatch inside a transaction; POSTing tests need
  `@pytest.mark.django_db(transaction=True)`.
- A test states days through `tests/calendar_days.py`.

---

### Task 1: `Category` moves; `conversion_review` field

**Files**
- Create `games/conversion_review.py`: `Category` (moved verbatim),
  `ReviewTarget` (`StrEnum`: `purchases`, `entries`), `ReviewWords`
  (`NamedTuple`: label, reason, target), `REVIEW_WORDS:
  Mapping[Category, ReviewWords]`, `REVIEWED: tuple[Category, ...]`
  (all but `SKIPPED_REMOVED_GAME`), `ORIGIN = "conversion"` if not
  importable from the backfill without a cycle (else import it).
- Modify `games/backfill/purchase_plan.py` (import `Category`),
  `games/backfill/purchase.py`, `games/backfill/purchase_reconciliation.py`,
  `games/purchase_parity.py`.
- Modify `games/filters.py`: `conversion_review_handler(reaches)` where
  `reaches: Callable[[], Expression]` gives the event key set; set
  composition per the spec; `FilterField(handler=…, label="Conversion
  review", choices=<from REVIEW_WORDS>, nullable=True)` on both
  `PurchaseFilter` (`conversion_review: ChoiceCriterion | None`) and
  `LibraryEntryFilter`. Entry reach: `aggregate_id = OuterRef("pk")` OR
  `aggregate_id IN Purchase.objects.filter(entry=OuterRef("pk"))
  .values("pk")` (plain manager: a removed purchase's tag still counts
  for its copy).
- Not in `QUICK_FACETS`.

**Tests** (`tests/test_conversion_review_filter.py`)
- Seed a library through the conversion pass helpers already used by
  `tests/test_purchase_conversion*.py` (find the builder there), or
  append events with `source_metadata` by hand through the commands'
  dispatch with a `source_metadata` argument.
- Purchase filter: INCLUDES one word selects exactly the tagged purchase;
  EXCLUDES leaves it out; INCLUDES_ALL needs both words; IS_NULL selects
  untagged; NOT_NULL tagged; `excludes` conjunct; INCLUDES_ONLY raises
  `FilterError`.
- Entry filter: a copy whose only tagged event is an attached purchase's
  is selected; another library's tagged event never matches (library
  scope).
- JSON round trip through `parse_purchase_filter` / `parse_entry_filter`.
- A word outside `REVIEWED` is refused at parse (choices).

**Gotchas**
- `games.E0xx` filter checks and `test_partition_covers_every_criterion_field`
  need the `fields` entry.
- `ChoiceCriterion` stores strings; map to `Category(word)` only where
  needed.

### Task 2: Review rows and the Hide preference

**Files**
- `games/models.py`: `UserLibraryPreferences.conversion_review_hidden =
  models.BooleanField(default=False)`; `make makemigrations
  ARGS="games --name conversion_review_hidden"`.
- `games/conversion_review.py`: `ReviewRow(label, reason, count, url)`;
  `conversion_review_rows(library) -> tuple[ReviewRow, ...]`: one
  `LibraryEvent.objects.filter(library=…, source_metadata__origin=…)
  .exists()`, then per category in `REVIEWED` the target list's read
  (`purchase_list_rows`'s base `library_purchases(library)` or
  `library_entries(library)`) filtered by the field, `.count()`, zero
  dropped; plus "Repurchased games" over `Game.objects.for_library`
  with `GameFilter(entry_count=AggregateCriterion(2, GREATER_THAN or
  equal))`. URLs via `filter_url(...)` with the list route (check
  `filter_url`'s signature for purchases and entries modes).
- `games/writes/` or `games/library_preferences.py` (where
  `change_library_default_device` lives): `change_conversion_review_hidden`.
- `games/api.py`: `PATCH /library/conversion-review-hidden`
  (`ConversionReviewHiddenIn{value: bool}`, out `{key, value: bool,
  source, locked, namespace}`), message "Conversion review saved"? —
  use "Hide this review saved"; set `X-Reload`. Update the default-device
  docstring.
- `games/forms.py`: `ConversionReviewForm` (`hidden =
  BooleanField(label="Hide this review", required=False)`, widget attr
  `data-reload-after-save`). Field name must equal the key the template
  fills — check how `LiveSettingFields` maps field name → key
  (`SettingFieldState.key`).
- `games/views/library.py`: the Purchases section becomes
  `Fragment(purchases_summary, review_list, hide_control)`; review list
  only when rows exist and not hidden; checkbox shown whenever the
  library holds conversion events.
- `games/views/returns.py`: no new page route (API only). Check API
  route lists pinned by tests (`tests/test_api_*`).

**Tests**
- `tests/test_conversion_review_rows.py`: counts equal the target list's
  rows for each target; zero rows dropped; no conversion events → no rows
  and no checkbox; hidden → no rows read (assertNumQueries-style bound or
  `django_assert_max_num_queries`), checkbox rendered checked.
- API: PATCH true/false persists; non-bool 422; other library untouched.
- Library page render: rows link to the lists; the link opens the list
  with exactly those rows (GET the URL, count rows).
- e2e (`e2e/test_library_page_e2e.py` or nearest): ticking Hide reloads
  and the rows go.

### Task 3: Shared half, `purchase.remove`

**Files**
- Move `purchase_list_rows`, `_PURCHASE_PATHS`, `ListedPurchase` to
  `games/reads/purchases.py`; update `games/views/purchase.py` and any
  test importing them (`grep -rn purchase_list_rows`).
- `games/writes/purchase.py`: `remove_purchase` / `restore_purchase`
  gain keyword `source_metadata: SourceMetadata | None = None` passed to
  `_dispatch` (check `_dispatch` accepts it; else add).
- Create `games/bulk_purchases.py`: `PURCHASE_GONE`, `purchase_scope`,
  `purchase_resolution` (`library_purchases(...).filter(pk__in=...)`,
  `with_valuation`, `select_related(*PURCHASE_PATHS)`, game display order
  through `entry__player_game__game`, then `id`; `lost(...)`),
  `removed_purchase(actor, id)` (plain manager, `RowNotHeld`),
  `PURCHASE_PREVIEW` (Name via `purchase_label` + game, Kind, Amount via
  `price_words`, Purchased).
- `games/bulk_removal.py`: `remove_one_purchase`, `restore_one_purchase`,
  `REMOVE_PURCHASE = BulkAction(name="purchase.remove", ..., subject=
  purchase SUBJECT, undo_rows=EventRows(Purchase), fallback=
  "games:list_purchases")`.

**Tests** (`tests/test_bulk_purchase_removal.py`, mirror
`tests/test_bulk_entry*` for the entry act)
- Confirmation lists the rows; POST removes; Undo restores; a removed
  row is "gone since"; another library's key is lost.
- Revaluation runs after restore (patch/spy as the P5b tests do).
- Any test enumerating `BULK_ACTIONS` names updates.

### Task 4: `purchase.edit` and the kind rule

**Files**
- `games/commands/purchase.py`: in `DescribePurchase.build`, refuse
  `kind` differing from the row's while `purchase.refund_recorded_at` is
  set and `self.refund` is not `TAKE_REFUND_BACK`; constant
  `KIND_UNDER_A_REFUND = "Take the refund back before changing what this
  purchase bought."`. Fingerprint unchanged (no new field).
- `games/reads/fact_change.py`: `Fact(created, changed, read:
  Callable[[LibraryEvent], T | None], initial=None)`; `payload_fact(key,
  parse) -> Callable[[LibraryEvent], T | None]`; `_value` message names
  event type, sequence and payload. Update `playergame_facts.py`,
  `entry_facts.py`.
- Create `games/reads/purchase_facts.py`: `PurchaseFactChanges(kind,
  price, purchased, note)` with `changed_any`; `purchase_fact_changes`.
  `purchased` fact: created → `ActStatement(event.effective_time,
  payload["purchase_note"])`; corrected → `ActStatement(effective_time,
  payload["note"])`, `changed=PURCHASE_CORRECTED`.
- `games/price_fields.py`: `PriceChoice.KEEP = "keep"`, label "Keep";
  `price_statement` KEEP case raises `ValueError`.
- `games/writes/purchase.py`: `restate_purchase` gains
  `idempotency_key`, `source_metadata`; `RestatedPurchase` gains
  `result: CommandResult`.
- Create `games/bulk_purchase_edit.py`: `PurchaseEditJson`,
  `PurchaseEditStatement` (kind, price, purchased, note; `of`,
  `encode`, `decode`), `BulkPurchaseEditForm(PrimitiveWidgetsMixin,
  UnsetFieldsForm, PriceFields)` — check MRO and that `UnsetFieldsForm`
  and `PriceFields.clean` both run (`super().clean()` chain);
  `price_change()`; `offer_edit` with `price_group()` and
  `price_presentations()`; `settle_edit`; `edit_one`; `edit_back`;
  `PURCHASE_EDIT = BulkAction(name="purchase.edit", label="Edit…", ...,
  choice=EDIT_CHOICE)`. Register in `bulk_actions.py`'s foot import.

**Tests**
- `tests/test_bulk_purchase_edit.py`: each fact alone and together;
  empty form refused with `NOTHING_STATED`; Keep placeholder text for
  same/mixed; Paid requires amount and currency (refusal on the field
  label); Free; Unknown; purchased keeps purchase_note; unchanged day →
  already so; Undo restores each fact; Undo over a later change logs and
  overwrites; Undo of a batch that changed nothing → refused sentence;
  removed row → refused; kind change on a refunded purchase → refused
  row with the sentence; carried statement round trip; unreadable
  statement.
- `tests/test_purchase_refund*.py` / commands: the new kind rule, and
  that a kind change beside a refund void passes.
- `tests/test_fact_change*.py` (or wherever `Fact` is tested): event
  reader.
- `test_endpoint_fingerprints`: unchanged.

### Task 5: The list is selectable; the Library tab column

**Files**
- `games/views/purchase.py`: rows `key=str(purchase.pk)` beside `id=`;
  `selection` with `tray_actions(PURCHASE_EDIT.name, REMOVE_PURCHASE.name,
  origin=origin)`.
- `games/views/library_list.py`: `Column("Purchases", key="purchases",
  priority=1)` after Format; cell `purchase_lines(purchases)` in
  `games/views/purchase_menu.py` (a `Div` stack of `Span`s:
  `price_words`, prefixed by `purchase_label` + " · " when kind ≠ game
  or named).

**Tests**
- Purchases list renders the check-all, row checkboxes and tray acts.
- Library tab cell: game purchase shows price; pass shows "Season pass ·
  …"; refunded hidden; none → empty.
- e2e (`e2e/test_purchase_e2e.py`): select two rows → Edit… → Free →
  Save → both Free; Undo restores. Remove from tray.

### Task 6: Docs, render-pages, gate

- `make render-pages` at P5b tip and here on one database
  (`ARGS="--user NAME --out …"`), diff, attribute every file.
- CLAUDE.md: Purchase bullet (tray acts, kind rule), Library page
  review, `conversion_review`, the third events read.
- Spec timeless rewrite; delete this plan; wave doc via the organizer.
- Full `make check` once under the lock.
