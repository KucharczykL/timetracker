# Plan: the catalog editor's bin can be taken back (#999)

Spec: `docs/superpowers/specs/2026-10-07-issue-999-catalog-bin-undo-design.md`.

## Task 1 — `FixedBox` (common/components/primitives.py)

- `FixedBox(icon: str, *, tag: Literal["div", "dd"] = "div", attributes=None)[children]`:
  `Element(tag, attrs + class=field_box_class("full", look="fixed"))`
  holding `Icon(icon, [("class","mr-1 text-body")], "size-4", decorative=True)`
  then children. Export from `common/components/__init__.py`.
- `_stated_row` renders its `Dd` through `FixedBox("lock", tag="dd")[statement]`.
- Tests: existing `tests/test_opener_facts.py` stays green; one new test
  that `FixedBox` with a trailing child renders icon first, child last.

## Task 2 — server stub and chosen input (games/views/catalog_section.py, games/catalog_form.py)

- `CHOSEN_MARK_FIELD = "catalog-chosen-mark"` in `catalog_form.py`;
  `CatalogGraphForm.chosen_mark` property: bound → `data.get(CHOSEN_MARK_FIELD, self.mark)`,
  unbound → `self.mark`. Must read before `_validate_set` rewrites
  `self.mark`: capture posted mark at init (`self._posted_mark`).
- `_Name`s: `_RELEASE_GOING_NAME = _Name("{} release will be removed", "platform")`,
  `_RELEASE_UNDO_NAME = _Name("Undo removing the {} release", "platform")`,
  `_EDITION_GOING_NAME = _Name("{} edition will be removed", "name", "Unnamed edition will be removed")`,
  `_EDITION_UNDO_NAME = _Name("Undo removing the {} edition", "name", "Undo removing the unnamed edition")`.
- `_binned_stub(going: bool, sentence: _Name, undo: _Name, value: str) -> Node`:
  `Div(data_catalog_binned="", *(_OUT_OF_SIGHT if not going))[FixedBox("delete")[Span(hooks)[text], ControlButton(variant="ghost", type="button", class_="ms-auto", aria_label=…, hooks, data_catalog_restore="")["Undo"]]]`.
  `going = removal_stated(form)` (regardless of errors).
- `_edition_block` rows interleave card, stub. `editions_area` interleaves
  block, stub; adds `Input(type="hidden", name=CHOSEN_MARK_FIELD, value=graph.chosen_mark)`.
- `_templates`: each template body is `Fragment(row, stub)`.
- Tests (tests/test_game_form_page.py): live row stub hidden; binned
  re-render stub visible; binned in-sight row (sentence) stub visible;
  `templates()` both hold `data-catalog-binned`; chosen input echoes posted
  value and falls back to `in_library`; unbound edit renders stored mark.

## Task 3 — element (ts/elements/catalog-editor.ts)

- `isGoing(mark)`: any `ROW_SELECTORS` ancestor whose `OWN_REMOVED_INPUT`
  value is `"on"`.
- `stubOf(row)`: `row.nextElementSibling` if it matches `[data-catalog-binned]`.
- `rowEnd(row) = stubOf(row) ?? row`; `addEdition`/`addRelease` insert after it.
- `outOfSight(element, hidden: boolean)` sets/clears `hidden` and inline display.
- `stateRemoved`: write `on`, hide row, show stub, focus stub's restore button, `restateMark`.
- `stateRestored(button)`: stub = `button.closest('[data-catalog-binned]')`,
  row = `stub.previousElementSibling`; write `""`, show row, hide stub,
  focus row's own bin (`:scope` remove button for an edition is in the
  name row — use first `[data-catalog-remove]` in row), `restateMark`.
- `restateRow`: nodes = row's hooks + `stubOf(row)`'s hooks.
- Chosen: `chosenInput()` = `input[name="catalog-chosen-mark"]`; `change`
  listener on `MARK_INPUT` writes it unless `this.restating`.
- `restateMark`: rule 1/2/3 from spec; dispatch under `restating`.
- Docstrings updated to the chosen rule.
- vitest (catalog-editor.test.ts): add stubs + chosen input to `PAGE`
  and templates; cases listed in spec Tests.

## Task 4 — e2e (e2e/test_game_form_catalog_e2e.py)

- Two Releases (seed like `test_binning_the_marked_row_moves_the_mark_where_a_person_sees_it`);
  bin the marked one, see the stub, press Undo, submit; the Release
  survives and `is_default` stays on it.

## Task 5 — docs

- `docs/catalog.md` mark paragraph; `games/catalog_form.py` `_validate_set` comment.

## Gotchas

- `restateRow` writes `textContent` on hooks without `aria-label`:
  sentence hook on its own `Span`.
- `_validate_set` overwrites `self.mark`; capture posted value first.
- Edition stub lives outside the fieldset, so `fieldset > [data-catalog-remove]`
  test selector stays valid.
- Run `make ts` before e2e.
