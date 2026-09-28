# The filter acts and the presets panel

A filter control is a **statement** or an **act**. A statement says what
the filter holds: the search field, the facets, and the `⋯` menu. An act
does something to the whole filter: Apply, Clear, Presets, and Advanced
filter.

## The row

The statements come first. The acts come last, as one segmented
`ButtonGroup` with `ml-auto`. The group wraps as one unit and stays at the
end of its line. The row keeps flat children, because `layoutOverflow`
moves facets that are direct children of the row.

| Segment | Look | Name and tooltip |
|---|---|---|
| Apply | word, blue | — |
| Clear | `funnel-off` icon | "Clear filter" |
| Presets | `bookmark` icon and `▾` | "Presets" |
| Advanced filter | `list-tree` icon | "Advanced filter" |

Apply, the primary act, keeps its word. The group is named "Filter
actions". Presets needs a preset API; Advanced filter needs a builder
page.

When the row wraps, an open `⋯` menu can cover the group. Enter in a
facet applies from inside the menu.

## A segment that opens a panel

A `ButtonGroup` member with `opens` is a button, and takes no `href` or
`method`. The group shapes it for
its place and gives it to `opens`, which returns the popup around it.
`presets_member` returns the Presets member. Its dropdown opens with
`placement="bottom-end"` and the `presets` behavior: the combobox
behavior, with Tab kept inside the panel so that the name box and Save are
reachable.

## The presets panel

`<preset-panel>` holds the saved presets, a name box and Save. When the
typed name is taken, Save says "Overwrite" and a hint says that saving
replaces the preset. Enter in the name box saves and does not submit the
host's form. The panel makes every preset API call.

The panel does not know its page. It speaks to its host through two events
that bubble:

- `preset-panel:load` carries the filter, sort and per-page of the picked
  preset. The host cancels the event to show that it loaded it.
- `preset-panel:save` carries a `PresetSaveRequest`. The host answers it
  once, with the state to save or a refusal sentence, and stops
  propagation.

An event that no host answers gives a client error and a toast.

## The hosts

**The quick bar.** A load goes to the list. A save stores what the bar
states now, applied or not, with the sort from the URL and the per-page
from the prop.

**The degraded pill.** It renders inside `<quick-filter-bar>` with no form
and no `data-quick-row`, beside the group without Apply. Its save stores
the page's filter from the `filter` prop, and refuses when that prop does
not parse.

**The builder.** Its toolbar is the group without Advanced filter. A load
goes into the tree. A save stores `serializeForQuery()`, which reads the
live widgets; `serialize()` reads the stored tree. While a criterion is
incomplete, the save is refused, by the rule that disables Apply.

## Limits

The `/api/presets/` contract does not change. The panel does not rename a
preset.
