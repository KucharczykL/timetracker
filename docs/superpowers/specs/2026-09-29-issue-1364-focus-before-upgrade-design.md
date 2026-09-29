# A picker focused before its script runs

The server renders `<search-select>` as HTML. A module script adds its
behaviour later. A person or a script can focus the search box before the
module defines the element. The browser sends the `focus` event before
`initWidget` binds its listener, so the widget does not see the event.
Without a replay, the widget sends no prefetch and opens no panel.

## The rule

At the end of `initWidget`, the widget examines the search box:

- A box without `autofocus` that holds focus runs `runFocus` once, at
  once. The focus came from a person or from a script. In both cases the
  panel must open.
- A box with `autofocus` waits one frame. It runs `runFocus` only when it
  started empty or held none. A box that holds a label keeps its focus and
  stays closed.

The replay comes before the early return of a hosted picker, so hosted and
standalone pickers get it. `runFocus` is the path of a real `focus` event.
Thus the prefetch, the select-all of a label, and `showPanel` do not change.

`search-select.ts` imports `drop-down.js` before it defines itself. Thus the
host `<drop-down>` is defined when `runFocus` opens it.

## Known limits

- An `autofocus` box that holds a label stays closed after a click before
  wiring. At wiring, a click and native autofocus look the same.
- When the element is defined between mousedown and mouseup, the mouseup
  sets the caret and removes the select-all. The panel opens.
- Text typed before wiring becomes the committed label, with no value.
  #1367 tracks this.
- An `UnsetField` that the server rendered as none can disable the box
  after its panel opens. #1367 tracks this.

## Tests

`test_a_box_clicked_before_its_script_opens_its_panel` in
`e2e/test_search_select_e2e.py` delays the evaluation of
`search-select.js` with a top-level `await`. A delayed fetch is not
correct, because `page.goto` waits for `load`, and `load` waits for the
fetch. `load` does not wait for the evaluation. The test clicks the box.
After the click, it asserts that the element is not defined. A definition
cannot go back to undefined, so this proves that the click came first. The
test then expects the prefetched rows, and asserts that the route delayed
one file.
