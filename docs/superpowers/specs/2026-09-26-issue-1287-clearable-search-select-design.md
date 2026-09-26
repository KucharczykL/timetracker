# A SearchSelect that clears

Issue #1287, first item of the shared component work in epic #481.

A `SearchSelect` can only be emptied by selecting the box text and deleting it.
Nobody finds that, and a phone user must open the field and summon the keyboard
to do it. Every select #481 still converts is optional, so converting one today
makes its value permanent. A clearable `SearchSelect` shows a trailing × that
empties the field in one press, from any state, without the box being focused.

## Where this departs from #481 and the issue

Four rules of the filed text are reversed. Each follows the prior art below.

1. **One press clears everything.** The epic asked for two stages: × first
   clears a typed query and keeps the committed selection, a second × clears
   the selection. No surveyed system does this. In single mode it protects
   nothing either: the first keystroke already abandons the committed value
   (`search-select.ts`, the `input` listener). So × resets query and value
   together, in both flavours. In multi mode that drops every pill with the
   query, as MUI's multiple mode does.
2. **The button is named "Clear", not "Clear Device".** No surveyed system puts
   the field in the name. The field reaches assistive technology as the
   button's description instead (below).
3. **Every picker offers it.** The epic tied it to optional fields; a required
   picker holding a value needs one press to empty just as much.
4. **Every press is announced.** The issue had a query-only press emit nothing.
   A dedicated clear event is common prior art, and a consumer can use it to
   tell a reset gesture from a pick.

| System | Name | What × clears | Signal |
|---|---|---|---|
| PatternFly Select typeahead | "Clear input value" | query and selection | consumer handler |
| MUI Autocomplete | "Clear" | query and value | `onInputChange`/`onChange` with reason `clear` |
| Carbon ComboBox, MultiSelect | "Clear selected item(s)" | selection | `onClearSelection` |
| Web Awesome, Shoelace | generic | value | `wa-clear`, `sl-clear` |
| React Aria SearchField | "Clear search" | query | `onClear` |

## The button

`SearchSelect(clearable=True)` renders a `<button type="button">` inside the
field box, after the search input and before the #450 committed marker. Every
combobox personality draws its field with that one box
(`[data-search-select-box]`, `_BOX_CLASS`), so the button needs no placement
of its own; the panel personality once drew the border on the input instead,
and a sibling of the input landed under it. It carries
`aria-label="Clear"`, `title="Clear"`, `data-search-select-clear`, `shrink-0`,
`ml-auto` and `size-8`, around a 16px `x-mark` icon. In multi mode the pills
flow before the box in the same wrapping row, so without `ml-auto` the button
could wrap onto a line alone. The 32px box is above the 24px touch target WCAG
2.5.8 asks for, and matches the field's weight where a bare glyph looked lost. Its presence is the
element's opt-in, as the #450 status span is. No prop carries it.

The button shows when the widget holds a committed value (a single label or at
least one pill) or the box holds a typed query. Otherwise it carries `hidden`,
and the server renders it hidden when no option is selected.
`syncClearButton()` decides visibility. It runs inside `syncUncommitted()`,
before that function's early return, and inside `emitChange()`. Between them,
the two already run on every path: a pick, an input, `setSelected`,
`_searchSelectClear`, `setOptions`, `_searchSelectRefetch`, the `sync_url`
restore at init, and the pill ×.

A disabled box hides the button in CSS: the box is a `peer` and the button
carries `peer-disabled:hidden`. `add_purchase.ts` disables the optional
`related_game` picker's box while its type is "game", and the box can still hold
a pick at that point.

The field's name reaches the button as a description. `SearchSelectWidget`
renders `aria-describedby="{field_label_id(id)}"` on it. That is the id
`FormFields` gives every label, the same way `DatePicker` names its group. Orca
reads "Clear, push button, Device". A bare `SearchSelect` outside a form states
no description.

The button is a Tab stop. Tab from the box lands on it and closes the panel, as
Tab out of the widget does today. The container's `focusout` does not fire
while focus stays inside, so the button's `focus` hides the panel itself.

## A press

A press builds on `_searchSelectClear()`, which already empties the pills or
hidden inputs, the label and the box text. It then:

- clears the debounce timer and aborts the pending request, as `focusout`
  does. Otherwise a response for the old query lands after the clear and shows
  its matches as the whole list;
- runs `filterRows("")`, hides the create row and the no-results line;
- sets a flag, `_searchSelectSoleDeclined`, that only `commitTheSoleOption`
  reads. Without it, a field whose search states one option would put back the
  value the person just removed. `runFocus` resets `_searchSelectDirty` when the
  box and the label are both empty, so the dirty mark cannot do this job. A
  pick and a dependency change lift the flag.

Focus follows where it was:

- **Pointer or touch.** The button's `mousedown` is prevented, as the pill ×
  already is, so it never takes focus. Focus stays where it was. A phone tap
  clears the field without opening the keyboard or the panel.
- **Keyboard or assistive technology.** The button holds focus when it is
  activated (`document.activeElement === button`). The press moves focus to the
  box, because the button hides under it and focus would otherwise fall to
  `<body>`. Focusing the box opens the panel, as any focus of it does. A
  click's `detail` is not used: a screen reader's virtual cursor can report 1.

## The events

A press dispatches, in order:

1. `search-select:change` with `values: []` and `last: null`, only when the
   press removed a committed value. A press that emptied a query alone does not
   change the value, so it does not claim one. The input listener already emits
   this shape, and no consumer misreads it.
2. `search-select:clear`, always, bubbling, with detail `{ name }`. Its type,
   `SearchSelectClearDetail`, sits beside `SearchSelectChangeDetail` in
   `ts/elements/search-select.ts`, which consumers import and never redefine.

No consumer listens to the clear event yet. The bulk Edit of #1211 is the
likely first one: its × means "leave as it is" and its ⊘ toggle means "none",
and the two stay different facts.

## Who gets the button

Every `SearchSelect` gets it: the component and `SearchSelectWidget` both take
`clearable: bool = True`, and a call site passes `False` to opt out. Whether a
field is required does not decide it. A required picker that holds a value is
the one a person most needs to change, and without × the only way to empty it
is the keyboard. A required field left empty is the form's refusal to state,
not the picker's.

A press always leaves the field empty, never back at the value the page
rendered. On an add page that is the state the person arrived at; on an edit
page it is still one press to empty, which a reset would lose.

The time zone row reads `search-select:clear` as its pinned "" option: it
states NULL and falls back to the display zone. Every other consumer already
receives `values: []` and `last: null` when a person types over a committed
label, so the × brings them nothing new.

`FilterSelect` and `PresetSelect` do not take the parameter. The quick filter
bar has its own Clear, and the builder's rows belong to #481's third
workstream.

## Tests

- **pytest, component.** A clearable widget renders the button hidden with no
  selection and shown with one, in both flavours. The attributes are as stated.
  `clearable=False` renders no button. `SearchSelectWidget` renders it on
  required and optional fields alike, drops it on `False`, and renders the
  label id as the description.
- **vitest.** Visibility follows every path above. A press with a committed
  value emits change, then clear. A query-only press emits clear and no change.
  A press while a debounced fetch is pending renders nothing from it. On a
  `commit_sole_option` field with `prefetch`, a keyboard press leaves the field
  empty after the focus fetch answers one option. Focus on the button closes the
  panel. The time zone row states NULL on a clear.
- **e2e, one per flavour.** Single, on a real form: a keyboard press empties
  the field, moves focus to the box, and the form posts no value; a pointer
  press empties it and leaves focus where it was. Multi, on the synthetic
  harness: a keyboard press removes every pill and a pointer press does the
  same without moving focus. A disabled box hides the button. On a touch
  device the button is at least 24px square and a tap clears without focusing
  the box.
