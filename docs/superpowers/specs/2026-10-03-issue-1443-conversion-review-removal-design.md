# Remove the one-time conversion review (#1443)

## Problem

The Library page's Purchases section carries the Conversion review: one
row per review category of the 2026-10-02 purchase conversion, a count
linking to the rows, and a "Hide this review" checkbox stored on
`UserLibraryPreferences.conversion_review_hidden`. The conversion ran
once. After the owner has worked through it, nothing reads it again.

## Decisions

- The review rows, the Repurchased games row and the Hide checkbox go:
  `games/views/conversion_review.py` and its call in
  `games/views/library.py`. The Purchases section holds the purchases
  summary alone.
- The preference goes: the model field, `set_conversion_review_hidden`,
  `change_library_conversion_review_hidden`
  (`timetracker/settings_commands.py`), the
  `PATCH /api/library/conversion-review-hidden` route with
  `ConversionReviewHiddenIn`/`ConversionReviewHiddenOut`,
  `ConversionReviewForm` (`games/forms.py`) and
  `CONVERSION_REVIEW_HIDDEN`. Migration `0037` removes the column and
  depends on the squash #1448 writes in the same PR.
- `conversion_review`, the choice field on `PurchaseFilter` and
  `LibraryEntryFilter`, stays, with `Category` and `ORIGIN`. The events
  stay forever, and after the rows go the field is the only way to the
  converted population. Its words stay stable: a saved preset may name
  one.
- The field's choice labels stay. `REVIEW_WORDS` shrinks to
  `REVIEW_LABELS: Mapping[Category, str]`; `ReviewWords`, `ReviewTarget`
  and the reasons go, since only the rows read them.
- `Category.SKIPPED_REMOVED_GAME` and `RECONCILIATION_ONLY` go: no
  event carries the word, the filter already refuses it, so no preset
  can name it, and its readers leave with #1448.
- `data-reload-after-save` and `RELOAD_HEADER` stay;
  `games/settings_forms.py` and `_report_saved` in `games/api.py` use
  them.
- #1432's audit screen planned to gather the review lists; it reaches
  the same rows through the `conversion_review` field. A comment on
  #1432 says so.

## Tests

- `tests/test_conversion_review_rows.py` and
  `e2e/test_conversion_review_e2e.py` go.
- `tests/test_conversion_review_filter.py` reads `REVIEW_LABELS`, and
  asserts every `Category` word is a choice.
- `tests/test_library_page_isolation.py` pins the Library page's query
  count and its docstring names the review's query; the number drops
  by what the review read, measured.
- CLAUDE.md's #1266 text drops the review and its preference. The wave
  doc's Review surface and Deployment text waits for the organizer's
  timeless rewrite and the step-two trim.
- `StrictBool` leaves `games/api.py`'s imports with the schema.

## Follow-up issues to file

None.
