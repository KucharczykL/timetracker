# Desktop settings rail sticky repair plan (#384)

**Status:** planned; not implemented  
**Prepared:** 2026-07-21  
**Scope:** repair the desktop settings section rail's intended sticky behavior and its
false-positive browser test.

## Outcome

At desktop settings-scaffold widths, the section menu remains approximately 16px from the
top of the viewport while the settings content scrolls. If the menu itself is taller than
the available viewport space, its inner navigation can scroll vertically. Mobile keeps the
existing priority-plus chip row and `More` dropdown unchanged.

This repair must preserve:

- the 14rem desktop rail width as the current starting point;
- complete, readable section labels with no horizontal menu scrollbar;
- inset focus rings on section links;
- the same-DOM mobile/desktop navigation transformation; and
- the inner menu's `max-height` and `overflow-y-auto` behavior.

The existing no-wrap presentation may remain only if each concrete settings page's desktop
labels pass the horizontal-overflow gate below. If they do not, stop and make a deliberate
follow-up choice between wrapping, accessible truncation, or further width treatment. Do not
hide overflowing labels with `overflow-x-hidden` or `overflow-x-clip`.

This gate belongs exclusively in browser tests run during development and CI. Do not add
label measurement, length validation, warnings, or exceptions to production Python or
TypeScript. Character-count limits are not a substitute: proportional fonts and translated
text make character counts a poor predictor of rendered width.

Scrollspy and active-section highlighting are outside this repair. Label-layout or further
rail-width work remains outside it unless the overflow gate proves that work is required.

## Confirmed problem

`SettingsSectionNav` currently assigns desktop `sticky` and `top-4` to its inner `<nav>`.
The `<nav>` is contained by the outer `<settings-section-nav>` grid item, whose height is
only the menu's content height. That containing block gives the sticky child no useful
vertical travel alongside the taller settings-content column.

The current browser test verifies that the inner `<nav>` computes to `position: sticky`, but
does not prove sticky behavior. After scrolling it accepts `y <= 18`; a rail that has scrolled
off-screen to a negative coordinate also satisfies that condition.

The inner `<nav>` is still intentionally a scroll container because it owns
`overflow-y-auto`. This is independent of whether sticky positioning works and is why the
section links retain their inset focus rings.

There is a related horizontal-axis risk: when one overflow axis is `auto`, an otherwise
visible overflowing axis becomes scrollable. The combination of the inner navigation's
`overflow-y-auto` and the links' `whitespace-nowrap` can therefore recreate a horizontal
scrollbar whenever a label is wider than the 14rem rail. Widening the rail reduces that risk
but does not eliminate it; the browser checks below must prove the current labels fit.

## Target ownership

| Element | Responsibility after the repair |
| --- | --- |
| `<settings-section-nav>` | Desktop grid item, sticky positioning, 16px top offset, non-stretched alignment |
| Inner `<nav>` | Accessible navigation landmark, mobile bottom margin, desktop viewport-height cap and vertical overflow; must pass the no-horizontal-overflow gate |
| Primary `<ul>` | Horizontal clipped chip row on mobile; restored vertical list on desktop |
| Section `<a>` | Navigation label, hover state, and contained inset focus ring |

Sticky positioning belongs to the outer grid item because its containing block is the full
two-column settings scaffold. Overflow belongs to the inner navigation so a long menu can
scroll without making the sticky grid item taller than the viewport.

## Implementation steps

### 1. Move sticky positioning to the grid item

Edit `SettingsSectionNav` in `common/components/settings_kit.py`.

Change the outer custom-element host from:

```text
block min-w-0
```

to:

```text
block min-w-0 @4xl:sticky @4xl:top-4 @4xl:self-start
```

`self-start` makes the ownership robust even if the scaffold's grid alignment changes later;
a stretched grid item is an unreliable sticky rail.

Remove `@4xl:sticky` and `@4xl:top-4` from the inner `<nav>`. Keep its other responsive
classes, producing this responsibility:

```text
mb-4 @4xl:mb-0 @4xl:max-h-[calc(100vh-2rem)] @4xl:overflow-y-auto
```

Do not move `overflow-y-auto` onto the host. Do not remove `focus:ring-inset` from the links.
No TypeScript behavior should change.

### 2. Make the component contract assert ownership

Update `SettingsScaffoldTest.test_same_dom_carries_mobile_chips_and_desktop_rail_classes`
in `tests/test_settings_ui_kit.py`.

The test must establish all of the following:

1. The opening `<settings-section-nav>` carries `@4xl:sticky`, `@4xl:top-4`, and
   `@4xl:self-start`.
2. The inner `<nav>` does not carry `sticky` or `top-4`.
3. The inner `<nav>` still carries the max-height and vertical-overflow classes.
4. Section links still carry `focus:ring-4 focus:ring-inset`.
5. The desktop grid remains `14rem minmax(0, 1fr)`.

Prefer assertions scoped to each opening element rather than checking whether a class occurs
anywhere in the complete HTML. A global `"@4xl:sticky" in html` assertion allowed the wrong
owner to pass previously.

### 3. Strengthen the isolated browser fixture

In `settings_kit_view` in `e2e/test_settings_ui_kit_e2e.py`, add a clearly marked test-only
block after `SettingsScaffold(sections)` inside the existing page-content wrapper:

```python
Div(data_settings_after_scaffold="", class_="min-h-screen")[
    "Content after the settings scaffold."
]
```

The trailing block gives the browser enough document height to verify that the sticky rail is
constrained by the settings scaffold and does not overlay later page content. It is fixture
material, not part of `SettingsScaffold` and not a supported settings component.

Keep five sections so the existing priority-plus counts remain stable, but replace one
synthetic label with the reported near-limit preview label, `Setting source and lock states`.
This makes the test exercise the exact label seen in the rail-width and focus-ring review,
without adding a production check or changing the supported component catalog.

### 4. Replace the false-positive sticky assertion

Update
`e2e/test_settings_ui_kit_e2e.py::test_desktop_scaffold_promotes_same_nav_to_sticky_rail`.

Use the outer `<settings-section-nav>` as the sticky subject and the inner `<nav>` as the
overflow subject. The test should:

1. Set the existing 1280×800 desktop viewport and open the isolated settings-kit page.
2. Assert the outer host computes to `position: sticky` and `top: 16px`.
3. Assert the inner `<nav>` computes to `overflow-y: auto` and is not sticky.
4. Measure every primary section link in the rendered browser and collect links whose
   `scrollWidth` exceeds their `clientWidth`. Assert that collection is empty and include each
   offending label's text in the assertion failure. Also assert the inner navigation itself
   satisfies `nav.scrollWidth <= nav.clientWidth`. If either check fails, stop; do not mask it
   with horizontal clipping. Resolve the label-layout decision before continuing.
5. Focus the first section link and assert its compiled `box-shadow` contains `inset`, proving
   the browser received the contained focus treatment rather than checking only a source
   class string.
6. Record the host's initial bounding box and confirm it starts aligned with the first
   settings section and materially below the 16px sticky threshold.
7. Set the target scroll position beyond the host's original document position, then calculate
   `document.documentElement.scrollHeight - window.innerHeight` and assert the target is
   reachable. A clamped scroll must fail the test rather than produce a misleading result.
8. Scroll to the target and wait until `window.scrollY` reaches it.
9. Read the host's post-scroll bounding box and require its `y` coordinate to remain within a
   small tolerance around 16px, for example `14 <= y <= 18`.
10. Scroll to the test-only block after the scaffold. Assert the sticky host's bottom edge is
    at or above that block's top edge, proving the rail stops at the scaffold boundary rather
    than overlaying following content.
11. Keep the existing desktop assertions that all five original navigation nodes are restored
    to the primary list and the `More` control is hidden.

The post-scroll assertion must have both a lower and upper bound. In particular, negative
coordinates must fail.

Illustrative test shape:

```python
expect(nav_host).to_have_css("position", "sticky")
expect(nav_host).to_have_css("top", "16px")
expect(nav).to_have_css("overflow-y", "auto")

primary_links = nav.locator("[data-section-nav-primary] a[href^='#']")
overflowing_labels = primary_links.evaluate_all(
    """elements => elements
        .filter(element => element.scrollWidth > element.clientWidth)
        .map(element => element.textContent?.trim() || "<unnamed>")"""
)
assert overflowing_labels == [], (
    f"Section labels exceed the 14rem rail: {overflowing_labels}"
)
assert nav.evaluate("element => element.scrollWidth <= element.clientWidth")

first_link = primary_links.first
first_link.focus()
assert "inset" in first_link.evaluate(
    "element => getComputedStyle(element).boxShadow"
)

initial = nav_host.bounding_box()
assert initial
assert initial["y"] > 66
target = initial["y"] + 100
max_scroll = page.evaluate(
    "document.documentElement.scrollHeight - window.innerHeight"
)
assert target <= max_scroll
page.evaluate("target => window.scrollTo(0, target)", target)
page.wait_for_function("target => window.scrollY >= target - 1", target)

stuck = nav_host.bounding_box()
assert stuck and 14 <= stuck["y"] <= 18

after_scaffold = page.locator("[data-settings-after-scaffold]")
after_document_y = after_scaffold.evaluate(
    "element => element.getBoundingClientRect().top + window.scrollY"
)
max_scroll = page.evaluate(
    "document.documentElement.scrollHeight - window.innerHeight"
)
assert after_document_y <= max_scroll
page.evaluate("target => window.scrollTo(0, target)", after_document_y)
page.wait_for_function(
    "target => window.scrollY >= target - 1",
    after_document_y,
)
stopped = nav_host.bounding_box()
after_box = after_scaffold.bounding_box()
assert stopped and after_box
assert stopped["y"] + stopped["height"] <= after_box["y"] + 1
```

Adapt the exact waiting expression to the installed Playwright API. Avoid a fixed timeout when
the page's scroll position can be awaited directly. The viewport-height trailing block is
deliberately large enough to make its document position reachable. If that reachability
assertion fails, fix the fixture; do not weaken or omit the boundary assertion.

### 5. Prove that a tall rail scrolls internally

Add a second focused browser test, for example
`test_desktop_section_nav_scrolls_in_short_viewport`.

1. Open the same fixture at a desktop width and a deliberately short viewport, such as
   1280×240. The 14rem rail and `@4xl` container mode remain active, while five section links
   exceed `calc(100vh - 2rem)`.
2. Assert the outer host still computes to `position: sticky`.
3. Assert the inner `<nav>` computes to `overflow-y: auto`.
4. Require `nav.scrollHeight > nav.clientHeight`; this proves the fixture genuinely exercises
   overflow.
5. Set the inner navigation's `scrollTop` to its `scrollHeight` and assert the resulting
   `scrollTop` is greater than zero.
6. Record `window.scrollY` before changing `scrollTop` and assert it is unchanged afterward.

This is an automated requirement, not an optional manual check. It proves the inner
navigation—not the sticky host and not the page—is the tall-menu scroll owner.

### 6. Codify the layout rule

Update the rail guidance in `docs/visual-conventions.md`:

- sticky positioning belongs on the rail's grid item or host, whose containing block spans
  the full content column height;
- `self-start` prevents grid stretching from defeating sticky behavior;
- the nested navigation owns `max-height` and `overflow-y-auto`;
- vertical `overflow-y-auto` can expose horizontal overflow, so a rail also needs an explicit
  long-label policy and a rendered-width browser check that reports offending labels;
- label-width enforcement belongs in development/CI tests, not runtime JavaScript, Python
  validation, or a character-count heuristic;
- every concrete page that consumes `SettingsScaffold` must run the same per-label assertion
  against its actual desktop rail; once a second consumer needs it, extract the small assertion
  into a shared `e2e/` test helper rather than duplicating it;
- a computed `position: sticky` assertion is insufficient without a before/after scroll
  measurement;
- a sticky rail must also be checked at the bottom of its containing scaffold when later page
  content is possible.

This is a general containment rule, not a settings-page exception.

### 7. Run focused verification

Rebuild the stylesheet because responsive utility ownership changes:

```console
direnv exec . make css
```

Run the focused server-rendered component tests:

```console
direnv exec . env DEBUG=true uv run --frozen pytest tests/test_settings_ui_kit.py
```

Run the two desktop rail behavior tests:

```console
direnv exec . env DEBUG=true uv run --frozen pytest \
  e2e/test_settings_ui_kit_e2e.py::test_desktop_scaffold_promotes_same_nav_to_sticky_rail \
  e2e/test_settings_ui_kit_e2e.py::test_desktop_section_nav_scrolls_in_short_viewport
```

Finish with:

```console
git diff --check
```

Do not run the full project check for this iteration. The epic's final verification gate owns
the full `make check` run.

### 8. Perform a manual preview check

At a desktop width where the scaffold has promoted to two columns:

1. Start near the top of the settings preview and note the rail's alignment with the first
   section.
2. Scroll past the rail's original document position.
3. Confirm the rail remains 16px from the viewport top while the settings sections continue
   moving.
4. Hover the rail and confirm no horizontal scrollbar appears. Verify every section label is
   complete and readable.
5. Focus or click a section link and confirm its entire inset ring remains visible.
6. Continue to the end of the settings scaffold and confirm the rail does not overlap any
   following content.
7. Reduce the desktop viewport height until the menu exceeds its available height; confirm the
   inner menu scrolls independently while the page remains still.
8. Resize below the desktop container threshold and confirm the rail returns to the existing
   chip row with priority-plus overflow.
9. Return to desktop width and confirm all original section nodes return to the vertical list.

### 9. Commit and integrate

Review `git status` before staging. Stage only the sticky-rail implementation, its tests, and
the associated documentation; leave the existing unrelated `Makefile` modification unstaged.

Use a focused commit such as:

```console
git commit -m "fix(settings): make desktop section rail sticky"
```

Fast-forward local `main` using the repository's temporary-worktree flow, then verify that
local `main` and the feature branch resolve to the same commit.

## Acceptance checklist

- [ ] At desktop scaffold width, the outer navigation host computes to `position: sticky` with
      a 16px top offset.
- [ ] After the page scrolls beyond the rail's original position, the host remains between
      14px and 18px from the viewport top.
- [ ] The browser test fails if the rail scrolls to a negative `y` coordinate.
- [ ] The browser test proves its target scroll position is reachable and was reached.
- [ ] A short-viewport browser test proves the inner navigation is genuinely overflowing and
      can scroll without changing `window.scrollY`.
- [ ] The rail does not overlap the test-only content following the settings scaffold.
- [ ] Every representative fixture label passes the per-link rendered-width check; any failure
      reports the offending label text.
- [ ] The fixture includes the reported near-limit preview label, `Setting source and lock
      states`.
- [ ] The inner navigation as a whole has no horizontal overflow.
- [ ] Production contains no runtime label measurement or character-count validation.
- [ ] Visual conventions require each future concrete `SettingsScaffold` page to apply the
      same browser assertion to its actual labels.
- [ ] Section-link focus rings remain complete and visible, and the browser-computed focus
      shadow is inset.
- [ ] The desktop rail remains 14rem wide.
- [ ] Mobile priority-plus behavior and same-node restoration are unchanged.
- [ ] The focused component and desktop browser tests pass.
- [ ] `git diff --check` passes.
- [ ] The unrelated `Makefile` modification remains unstaged and unchanged.

## Risks and checks

- **Sticky ancestor constraints:** do not add `overflow` to the outer host or scaffold; an
  ancestor scroll container would change which viewport the sticky host follows.
- **Horizontal overflow:** `overflow-y-auto` can make horizontal overflow scrollable. Never
  satisfy the no-horizontal-overflow gate by clipping text; choose a real long-label treatment
  if the current 14rem/no-wrap combination fails.
- **Width enforcement:** use each rendered link's `scrollWidth` and `clientWidth` in browser
  tests. Do not use a character limit, because glyph and translation widths vary, and do not
  ship measurement logic to production.
- **Grid stretching:** retain `self-start` on the sticky host even though the current grid also
  uses `items-start`.
- **Container-query threshold:** keep all new layout classes behind `@4xl`; viewport width
  alone does not determine whether this scaffold is in desktop mode.
- **End-of-scaffold behavior:** the rail should stop sticking at the bottom of its two-column
  scaffold. The test-only trailing block must prove it does not float over following content.
- **Test validity:** prove that a meaningful window scroll is both reachable and reached before
  asserting the sticky coordinate. Require a lower and upper coordinate bound.
- **Focus rendering:** keep the source-level inset-ring assertion, but also focus a real link in
  the browser so a missing compiled utility cannot pass unnoticed.
