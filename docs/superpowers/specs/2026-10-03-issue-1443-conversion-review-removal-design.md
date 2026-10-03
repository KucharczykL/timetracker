# The conversion review is gone (#1443)

## Scope

The 2026-10-02 purchase conversion tagged some copies and purchases
with a review word. The Library page listed each word's count and a
link, plus Repurchased games, until a Hide preference hid them. The
conversion ran once, so that list has no later use.

## Rules

- The Library page's Purchases section holds the purchases summary
  only.
- `UserLibraryPreferences` has no `conversion_review_hidden` column.
  Migration `0037` removes it and depends on the fourth squash. No
  route, form or setting command writes the preference.
- `conversion_review`, the choice field on `PurchaseFilter` and
  `LibraryEntryFilter`, stays. It reads the tags from events, and the
  events stay. It is the one way to the converted population.
- The field's words do not change, because a saved preset can name
  one. `Category` names every word an event can carry, and every word
  is a choice. `REVIEW_LABELS` gives each word its label.
- The filter refuses `skipped_removed_game`. No event carries that
  word.
- `RELOAD_HEADER` and `data-reload-after-save` stay. The settings forms
  use them.
- #1432's audit screen reaches the converted rows through the
  `conversion_review` field.

## Tests

- `tests/test_conversion_review_filter.py` holds that every `Category`
  word is a choice, that each choice carries its label, and that the
  retired word is refused.
- `tests/test_library_page_isolation.py` pins the Library page at 24
  queries.
