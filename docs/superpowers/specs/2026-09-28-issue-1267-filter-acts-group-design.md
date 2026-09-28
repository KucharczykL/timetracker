# The filter acts and the presets panel

The quick filter bar has two kinds of control. A **statement** says what
the filter holds: the search field, the facets, and the `⋯` menu that
holds the facets that do not fit. An **act** does something to the whole
filter: Apply, Clear, Presets, and Advanced filter. This spec puts the
acts in one group, and gives the quick bar, the degraded pill and the
filter builder one panel that loads and saves presets.

## The row

The statements come first, in the sequence that #1254 states. The acts
come last, as one segmented group with `ml-auto`, so the group sits at the
end of the row. When the row wraps, the group wraps as one unit and stays
at the end of its line. `justify-content: space-between` is not used: a
wrapped group then sits at the start of its line.

The row keeps its flat children, because `layoutOverflow` moves the facets
that are direct children of the row. The overflow reserve sums the
`offsetWidth` of every other child, and `offsetWidth` excludes margins, so
the auto margin takes only the slack and changes no fit.

The group has these segments, in this sequence:

| Segment | Look | Name and tooltip |
|---|---|---|
| Apply | word, blue | — |
| Clear | `funnel-off` icon | "Clear filter" |
| Presets | `bookmark` icon and `▾` | "Presets" |
| Advanced filter | `list-tree` icon | "Advanced filter" |

Apply keeps its word, because it is the primary act. Each icon segment
has an `aria-label` and the same text as `title`. The group has
`aria-label="Filter actions"`. `funnel-off` and `bookmark` are new
snippets in `games/templates/icons/`; `make gen-icons` regenerates
`icons_generated.py`. Advanced filter is absent on the modes that have no
builder page, as today.

Before, the Load preset picker was a ghost "Label ▾" trigger between the
`⋯` host and the group. It looked like a facet, so a person who looked
for it after Clear looked among the facets.

## The segment that opens a panel

A `ButtonGroup` member can open a panel. The member states the panel, and
the group renders a `<drop-down>` whose trigger is the segment, shaped by
`shaped` for its place. `SplitButtonDropdown` in `custom_elements.py`
already puts a `<drop-down>` in a joined row the same way; each member
draws its own border, so the wrapper breaks no corner. `ButtonGroup` sits
in `primitives.py`, which `custom_elements.py` imports, so it imports
`Dropdown` inside the function. `ButtonGroup` takes a `class_` that the
group's shell accumulates, which is how the row passes `ml-auto`.

The panel opens with `placement="bottom-end"`, so it aligns with the end
of the group rather than clamping against the viewport.

`LoadPresetDropdown` is removed. Its two callers, `QuickFilterBar` and
`FilterBuilder`, use the Presets member.

## The presets panel

`<preset-panel>` is one custom element inside the Presets dropdown. It
keeps the `data-preset-picker` hook, which the tests and the removal
wiring read. It holds:

1. The saved presets for the mode: the `PresetSelect` of today, with its
   search box and a remove action on each row.
2. A name box and a Save `ControlButton`. When the typed name is the name
   of a saved preset, the button says "Overwrite" and a hint under it says
   that saving replaces that preset. The name box is not a search-select
   and does not carry `data-search-select-search`.

The dropdown's behavior is the combobox behavior with Tab kept inside the
panel. Today the combobox behavior closes on Tab, so a keyboard user could
never reach the name box. The behavior keeps the refetch of the list on
`dropdown:show`, the focus of the preset search box, and the Enter guard.

Enter in the name box saves and calls `preventDefault`. Without that, the
quick bar's `<form>` submits and Enter navigates as Apply.

The panel owns the preset API calls that `ts/elements/presets.ts` has
today: save, the names fetch for the overwrite check, and removal with
its Undo toast. After a save, the panel stays open, the list refetches,
the name box empties, and a toast states the result.

The panel does not know which page it is on. It speaks to its host
through two events that bubble:

- `preset-panel:load` carries the filter, sort and per-page of the picked
  preset. The host decides what a load does.
- `preset-panel:save` asks for the state to save. The panel creates the
  `detail` as a mutable object. The nearest host writes the filter, sort
  and per-page into it during dispatch and stops propagation. A host can
  write a refusal sentence instead; the panel then toasts it and does not
  save. When no host writes either, the panel does not save and reports a
  client error.

## The hosts

**The quick bar.** A load goes to the list with the preset's filter, sort
and per-page, as today. A save stores what the bar states now, through
the serializer that Apply uses, also when the person did not apply it.
The sort comes from the page's URL and the per-page from the bar's prop,
as Apply does.

**The degraded pill.** The pill shows when `is_quick_editable` refuses
the filter. It renders inside `<quick-filter-bar>` with no form, no facets
and no `data-quick-row`, so `setupOverflow` finds no row and does
nothing. It shows the group without Apply; Edit in builder becomes the
Advanced filter segment. A load goes to the list with the preset. A save
stores the page's filter, which `QuickFilterBarProps` carries in a new
`filter` prop set only on this branch, with the sort from the URL and the
per-page from `per_page`.

**The builder.** The toolbar of `FilterBuilder` keeps no picker, no name
box and no Save button of its own. It shows the group with Apply, Clear
and Presets at the end of the toolbar, and no Advanced filter segment. A
load puts the preset into the tree and keeps the page, as today. Clear
still empties the tree and does not go to the list.

A save stores `serializeForQuery()`, the filter Apply queries, with the
builder's sort and per-page. The builder saved `serialize()` before, which
reads the tree as stored rather than the live widgets, so a leaf a person
added or edited saved its default value. While a criterion is incomplete,
the host answers the save with a refusal sentence, the same rule that
disables Apply, so a save never drops a leaf in silence.

## Limits

- The `/api/presets/` contract does not change. A save with a taken name
  still updates that preset, and the answer is still 200.
- The panel does not rename a preset. Save under a new name, then remove
  the old one.
- The overflow engine and the facets do not change.
- #1249 makes the degraded pill rarer. The pill keeps the group, because
  a facet whose widget cannot show its criterion still degrades the bar.
- The segment text changes from "Advanced filter…" to an icon named
  "Advanced filter". Tests that find the link by the old name change with
  it.
