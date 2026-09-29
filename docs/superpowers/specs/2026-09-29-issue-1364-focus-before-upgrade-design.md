# A picker focused before its script runs still opens

`<search-select>` is server-rendered, and its behaviour arrives with a module
script. A person or a test can click the search box after the HTML is parsed
and before `search-select.js` has run. The click focuses a plain `<input>`.
When the module defines the element, `initWidget` binds the `focus` listener
to an input that already holds focus, so `focus` never fires. `runFocus`
does not run, the prefetch is never sent, and no panel opens. The box looks
focused and does nothing until the person leaves it and comes back.

This is the flake in #1364.
`e2e/test_bulk_edit_e2e.py::test_two_sessions_take_one_device_and_the_undo_takes_it_back`
presses Edit…, which loads the confirmation as a new page, waits for the
heading, and clicks the device picker. Sometimes the click wins the race with
the module. The trace shows no request to the device search, which matches.
A 1.5 s delay on `**/search-select*.js` through `page.route` fails the test on
every run. With the change below, it passes.

## The rule

At the end of `initWidget`, a search box that already holds focus is treated
as focused now: `runFocus` runs once. That is the path a real `focus` event
takes, so the prefetch, the select-all of a committed label, the retained
query, and `showPanel` are unchanged.

The existing autofocus replay is one case of this rule, with its own
condition. An `autofocus` box keeps its rule: one frame later, and only when
it started empty or holding none, because native autofocus can land after
wiring and a pre-committed field must not steal the panel. A box without
`autofocus` that holds focus at wiring got it from a person or from a
script, such as a `<drop-down>` combobox or a sheet that focuses its first
field. Either way the panel belongs open, so it runs at once, whatever it
holds. Both branches live in one block, placed before the hosted picker's
early return, so only one path calls `runFocus` for a focus that happened
before wiring, hosted or not.

## What it does not change

- A hosted picker opens through its `<drop-down>`. `search-select.ts`
  imports `drop-down.js` before it defines itself, so the host is defined by
  the time `runFocus` calls `open()`.
- Text typed before wiring is not handled. `initWidget` reads
  `search.value` as the committed label, so typed text counts as a label
  with no value, and `runFocus` selects it and shows the full list. That
  happens with or without this change; #1367 tracks it.
- The mouseup guard that keeps a click's select-all does not arm, because
  the mousedown happened before its listener existed. When the mouseup
  also came before wiring, the select-all from `runFocus` stands. When the
  element is defined between mousedown and mouseup, the mouseup collapses
  the selection to a caret. The panel still opens, so that case is left.
- An `autofocus` box that holds a label and that a person clicks before
  wiring stays closed. At wiring, native autofocus and a click look the
  same, and the autofocus rule keeps a pre-committed field closed. A click
  after wiring does no better: native autofocus already holds focus, so the
  click fires no `focus` event.
- A picker inside an `UnsetField` that the server rendered as none can be
  clicked before either module runs. When `search-select` defines first,
  its panel opens, and then `<unset-field>` disables the input under it.
  #1367 tracks it.
- The bulk Edit test is correct as written. It is not changed.

## Tests

- `e2e/test_search_select_e2e.py`: on the search-url page, delay the
  evaluation of `search-select.js` with a top-level `await`, as
  `e2e/test_dropdown_host_order_e2e.py` delays its host. Click the box
  before the element is defined, and expect the prefetched rows to show.
  The test asserts that the route fired and, right after the click, that
  `customElements.get("search-select")` is still undefined. A definition
  only goes from undefined to defined, so a check after the click proves
  the click came first, and a missed or too-short delay fails rather than
  passing with no race. A delayed fetch does not work here: it delays
  `load`, and `page.goto` waits for `load`. A delayed evaluation does not
  delay `load`. It fails without the change on every run.
- The #1364 test, twenty runs in a row.
- The existing autofocus tests stay green.

## Out of scope

Other server-rendered custom elements can have the same race when their
controls can hold focus or take input before the element is defined. #1367
tracks the date field's segments, text typed into a picker before wiring,
and the `UnsetField` case above.
