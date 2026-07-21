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

- the 14rem desktop rail width;
- the existing section labels and no-wrap behavior;
- inset focus rings on section links;
- the same-DOM mobile/desktop navigation transformation; and
- the inner menu's `max-height` and `overflow-y-auto` behavior.

Scrollspy, active-section highlighting, label wrapping/truncation, and further rail-width
tuning are outside this repair.

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

## Target ownership

| Element | Responsibility after the repair |
| --- | --- |
| `<settings-section-nav>` | Desktop grid item, sticky positioning, 16px top offset, non-stretched alignment |
| Inner `<nav>` | Accessible navigation landmark, mobile bottom margin, desktop viewport-height cap and vertical overflow |
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

### 3. Replace the false-positive browser assertion

Update
`e2e/test_settings_ui_kit_e2e.py::test_desktop_scaffold_promotes_same_nav_to_sticky_rail`.

Use the outer `<settings-section-nav>` as the sticky subject and the inner `<nav>` as the
overflow subject. The test should:

1. Set the existing 1280×800 desktop viewport and open the isolated settings-kit page.
2. Assert the outer host computes to `position: sticky` and `top: 16px`.
3. Assert the inner `<nav>` computes to `overflow-y: auto` and is not sticky.
4. Record the host's initial bounding box and confirm it starts aligned with the first
   settings section.
5. Confirm the scaffold is tall enough to provide genuine sticky travel.
6. Scroll the window beyond the host's original vertical position. Use the measured initial
   position to choose the scroll target instead of relying on an unexplained fixed value.
7. Assert the browser reached that target so a no-op or page without enough content cannot
   pass.
8. Read the host's post-scroll bounding box and require its `y` coordinate to remain within a
   small tolerance around 16px, for example `14 <= y <= 18`.
9. Keep the existing desktop assertions that all five original navigation nodes are restored
   to the primary list and the `More` control is hidden.

The post-scroll assertion must have both a lower and upper bound. In particular, negative
coordinates must fail.

Illustrative test shape:

```python
expect(nav_host).to_have_css("position", "sticky")
expect(nav_host).to_have_css("top", "16px")
expect(nav).to_have_css("overflow-y", "auto")

initial = nav_host.bounding_box()
assert initial
target = initial["y"] + 100
page.evaluate("target => window.scrollTo(0, target)", target)
page.wait_for_function("target => window.scrollY >= target - 1", target)

stuck = nav_host.bounding_box()
assert stuck and 14 <= stuck["y"] <= 18
```

Adapt the exact waiting expression to the installed Playwright API. Avoid a fixed timeout when
the page's scroll position can be awaited directly.

### 4. Codify the layout rule

Update the rail guidance in `docs/visual-conventions.md`:

- sticky positioning belongs on the rail's grid item or host, whose containing block spans
  the full content column height;
- `self-start` prevents grid stretching from defeating sticky behavior;
- the nested navigation owns `max-height` and `overflow-y-auto`; and
- a computed `position: sticky` assertion is insufficient without a before/after scroll
  measurement.

This is a general containment rule, not a settings-page exception.

### 5. Run focused verification

Rebuild the stylesheet because responsive utility ownership changes:

```console
direnv exec . make css
```

Run the focused server-rendered component tests:

```console
direnv exec . env DEBUG=true uv run --frozen pytest tests/test_settings_ui_kit.py
```

Run the single desktop sticky behavior test:

```console
direnv exec . env DEBUG=true uv run --frozen pytest \
  e2e/test_settings_ui_kit_e2e.py::test_desktop_scaffold_promotes_same_nav_to_sticky_rail
```

Finish with:

```console
git diff --check
```

Do not run the full project check for this iteration. The epic's final verification gate owns
the full `make check` run.

### 6. Perform a manual preview check

At a desktop width where the scaffold has promoted to two columns:

1. Start near the top of the settings preview and note the rail's alignment with the first
   section.
2. Scroll past the rail's original document position.
3. Confirm the rail remains 16px from the viewport top while the settings sections continue
   moving.
4. Focus or click a section link and confirm its entire inset ring remains visible.
5. Resize below the desktop container threshold and confirm the rail returns to the existing
   chip row with priority-plus overflow.
6. Return to desktop width and confirm all original section nodes return to the vertical list.

If practical, also reduce viewport height enough to make the menu exceed its available height
and verify that the inner menu—not the page-wide rail host—scrolls vertically.

### 7. Commit and integrate

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
- [ ] The inner navigation retains its viewport-height cap and vertical scrolling.
- [ ] Section-link focus rings remain complete and visible.
- [ ] The desktop rail remains 14rem wide.
- [ ] Mobile priority-plus behavior and same-node restoration are unchanged.
- [ ] The focused component and desktop browser tests pass.
- [ ] `git diff --check` passes.
- [ ] The unrelated `Makefile` modification remains unstaged and unchanged.

## Risks and checks

- **Sticky ancestor constraints:** do not add `overflow` to the outer host or scaffold; an
  ancestor scroll container would change which viewport the sticky host follows.
- **Grid stretching:** retain `self-start` on the sticky host even though the current grid also
  uses `items-start`.
- **Container-query threshold:** keep all new layout classes behind `@4xl`; viewport width
  alone does not determine whether this scaffold is in desktop mode.
- **End-of-scaffold behavior:** the rail should stop sticking at the bottom of its two-column
  scaffold. It must not float over content following the settings scaffold.
- **Test validity:** always prove that a meaningful window scroll occurred before asserting the
  sticky coordinate.
