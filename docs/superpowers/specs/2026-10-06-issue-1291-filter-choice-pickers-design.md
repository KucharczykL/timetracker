# Filter controls in a SearchSelect

Issue #1291, part of #481.

## Controls

The filter builder and the quick bar render no native `<select>`. Six
controls are single-select pickers:

| Control | Marker | Choices |
|---|---|---|
| String match mode | `data-string-modifier-select` | the field's string modifiers |
| Number comparison | `data-number-modifier-select` | the field's number modifiers |
| Comparison operator | `data-fc-op` | set by the client from the left column |
| Comparison quantifier | `data-fc-quantifier` | `RELATION_MATCH_CHOICES` |
| Relation match | `data-relation-match` | `RELATION_MATCH_CHOICES` |
| Relation field | `data-relation-field` | the model's relation fields |

`ChoicePicker` (`common/components/filters.py`) builds each one. It holds
a choice always: no ×, no none row. It sets `revert_on_leave`, a
`search_aria_label` and a width. The comparison controls carry the marker
on a wrapper, because the client hides the quantifier and seeds both
through `data-selected`.

The relation pickers are server templates: one match template, and one
field template per reachable model. The field rows come from
`field_metadata`, the source of the `models` prop. A test holds the two
equal.

## The accessor

`ts/elements/choice-control.ts` is the one reader and writer.

- `choiceControl(root, marker)` finds the picker that carries the marker,
  or sits inside an element that carries it.
- `read()` returns the held value, or `null` mid-edit.
- `write(value)` is silent. It refuses a value that no row offers.
- `setChoices(groups)` replaces the rows of a wired picker.
- `isChoicePick(event, marker)` is true for a pick, false for a keystroke
  drop.

A clone of a `<template>` does not upgrade until it connects. `write`
then changes markup: one hidden input and the box text. Initialisation
adopts both, so the builder hydrates detached clones.

## Readers

- A string widget's value input carries `data-string-value`. The picker's
  box is also a text input, so no reader selects `input[type="text"]`.
- A string or number reader answers `null` while its picker holds
  nothing.
- `setupModifierToggles` reacts to a pick. The toggles find their inputs
  under `[data-filter-widget]`.
- An operator pick refreshes the right operand and the quantifier.
- `<filter-group>` refreshes completeness when a picker box inside a
  value cell loses focus. `revert_on_leave` restores silently, because
  `<live-setting-fields>` saves on every change.

## The facet panel

A facet's `combobox` behavior focuses and refetches only
`search-select[always-visible="true"]`. A number or string facet focuses
nothing on open, and its modifier list stays closed.

## SearchSelect

- `setOptionGroups(groups)` replaces rows in groups. `setOptions` is one
  group with a blank label.
- A blank group label renders no header, on the server and the client.
- `dynamic_options` ships a header template beside the row template.
- `search_aria_label` names the search box.

A picker assigns its ids at initialisation, so each clone of one
prototype takes its own ids. A test holds this.
