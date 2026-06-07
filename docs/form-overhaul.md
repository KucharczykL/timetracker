# Form Overhaul Plan

> Last updated: 2026-05-12
> Status: Decided — awaiting implementation
>
> **Decisions made:**
> - All forms (simple and complex) get section headers for consistency
> - Two-column layout uses **flexbox** (auto-reflow on different screen sizes)
> - `cotton/layouts/add.html` enhanced with **Option A**: `c-section` component slots
> - `add_purchase.html` dual-submit **simplified** — remove `<tr><td>`, use same `c-button` pattern as `add_game.html`
> - GameStatusChange delete confirmation **converted to modal** (via HTMX trigger)

## Goal

Modernize all forms and form-like elements to align with Flowbite design, improve visual consistency, and adopt responsive multi-column layouts for complex forms.

---

## Current State Analysis

### Form Pages (add/edit)

All use `cotton/layouts/add.html` — single column, `max-w-xl`, `form.as_div`:

| Page | Form | Fields | Complexity |
|---|---|---|---|
| Game | `GameForm` | 7 fields: name, sort_name, platform, year, year_orig, status, mastered, wikidata | Medium |
| Purchase | `PurchaseForm` | 11 fields: games, platform, dates, price, currency, type, ownership, related, infinite, name | High |
| Session | `SessionForm` | 8 fields: game, timestamps, duration, emulated, device, note, checkbox (custom rendering) | High |
| Platform | `PlatformForm` | 3 fields: name, icon, group | Low |
| Device | `DeviceForm` | 2 fields: name, type | Low |
| PlayEvent | `PlayEventForm` | 5 fields: game, dates, note, checkbox | Low |
| GameStatusChange | `GameStatusChangeForm` | 4 fields | Low |

### Other Form-Like Elements

| Element | Template | Notes |
|---|---|---|
| Login | `registration/login.html` | Flowbite card, already good |
| Search | `cotton/search_field.html` | Reusable, already good |
| Delete Game | `partials/delete_game_confirmation.html` | Inline modal, inconsistent button layout |
| Delete PlayEvent | `gamestatuschange_confirm_delete.html` | Full-page form, no modal |
| Refund Purchase | `partials/refund_purchase_confirmation.html` | Inline modal, inconsistent button layout |
| Stats Year Select | `stats.html` | Manual `<select>`, no Flowbite styling |
| Status Selector | `partials/gamestatus_selector.html` | Alpine.js dropdown, old Tailwind classes |
| Device Selector | `partials/sessiondevice_selector.html` | Alpine.js dropdown, old Tailwind classes |

---

## Issues to Fix

### P0: Broken/Inconsistent

1. ~~**`modal.html` has a missing `<form>` tag** (line 13: `</form>` with no opening `<form>`)** — *Resolved: rewritten as proper component with form wrapping support, body + footer slots, reusable `close_button` component. Ready for standardizing all inline modals later.*
2. **Delete confirmations are inconsistent** — three different patterns (inline modal, full-page form, inline modal)
3. **`.errorlist` CSS** has fixed `width: 300px` — too narrow, breaks on mobile. *No scoping needed: Django auto-applies `.errorlist` to form error output only, never used explicitly in templates.*
4. **`add_purchase.html` has `<tr><td>`** in a `c-slot` that renders inside a `<div>` — semantic mismatch. **Decision: simplify dual-submit** to match `add_game.html` pattern (use `<c-button>` only).
5. **`#button-container` and `.basic-button` in `input.css`** — legacy patterns, unused or dead code

### P1: Layout & UX

6. **All add/edit forms are single-column** — PurchaseForm (11 fields) and GameForm (7 fields) would benefit from multi-column
7. **No field grouping** — related fields listed flat without visual hierarchy
8. **Stats year `<select>`** has no Flowbite styling
9. **Search field** is not wrapped in `<form method="get">` — no native clear-on-Enter behavior

### P2: Styling Consistency

10. **Status/device selectors** use old Tailwind v3 patterns (`rounded-sm`, `shadow-2xs`, `border-gray-200` without explicit color)
11. **`navbar.html` buttons** use `rounded-sm` instead of `rounded-base`
12. **`simple_table.html` pagination buttons** use `rounded-s-lg`/`rounded-e-lg` — could be simplified

---

## Proposed Improvements

### 1. Two-Column Layout for Complex Forms (Flexbox)

**Scope**: `GameForm`, `PurchaseForm`, `PlayEventForm`, `SessionForm`

Use **flexbox** with wrap behavior so fields auto-reflow on different screen sizes. No fixed column count — fields sit side-by-side on `md:`+ and wrap naturally on smaller screens.

#### GameForm Layout
```
┌──────────────────────────────────┐
│ Game Details                     │
│ ┌──────────────────┬───────────┐ │
│ │ Name             │ Platform  │ │
│ │ Sort Name        │ Year      │ │
│ │ Original Year    │ Wikidata  │ │
│ └──────────────────┴───────────┘ │
│ Status                           │
│ ┌──────────────────┬───────────┐ │
│ │ Status           │ Mastered  │ │
│ └──────────────────┴───────────┘ │
│         [Submit]                 │
└──────────────────────────────────┘
```

#### PurchaseForm Layout (simplified)
```
┌──────────────────────────────────────────┐
│ Purchase Details                         │
│ ┌──────────────────────┬───────────────┐ │
│ │ Games (multi-select) │ Platform      │ │
│ │ Type                 │ Ownership     │ │
│ │ Name                 │ Related Purch │ │
│ └──────────────────────┴───────────────┘ │
│ Dates                    │ Price          │
│ ┌───────────────┬──────┴───────────────┐ │
│ │ Date Purch    │ Price         Curr   │ │
│ │ Date Refund   │ Infinite [ ]         │ │
│ └───────────────┴──────────────────────┘ │
│         [Submit] [Submit + Session]      │
└──────────────────────────────────────────┘
```

**Implementation**: `c-section` component accepts `columns="2"` (or `"3"`) which applies `flex flex-wrap gap-4 [&>div]:w-[calc(50%-0.5rem)]` on md+ screens. Each field wraps in a `<div>` inside the section slot.

**Decision**: Dual-submit in `add_purchase.html` simplified — remove `<tr><td>`, use same `<c-button>` pattern as `add_game.html`.

### 2. Field Grouping with Card Sections

**Decision**: ALL forms get section headers for consistency (not just complex forms).

Group related fields with section headings and subtle borders/backgrounds:

```html
<c-section title="Game Details" columns="2">
  {{ form.name }}
  {{ form.platform }}
  {{ form.sort_name }}
  {{ form.year_released }}
</c-section>
```

Each section renders as:
```html
<fieldset class="form-section p-5 border-t border-default-medium bg-neutral-primary-soft/30 first-of-type:border-t-0 first-of-type:pt-0">
  <h3 class="text-sm font-medium text-heading uppercase mb-4">Section Title</h3>
  <div class="flex flex-wrap gap-4">
    <!-- fields in <div> wrappers, each taking calc(50% - 0.5rem) on md+ -->
  </div>
</fieldset>
```

Each section gets:
- Subtle background (`bg-neutral-primary-soft/30`)
- Top border with spacing (`border-t border-default-medium`)
- Section heading (`text-sm font-medium text-heading uppercase mb-4`)
- Flexbox gap for responsive field reflow

### 1b. `c-section` Component Specification

New cotton component for the `cotton/` directory:

```python
# games/templates/cotton/section.py (or inline in components.py)
from common.components import Div

def Section(title: str = "", columns: str = "1", children: str = "") -> SafeText:
    """Renders a form field section with optional multi-column flexbox layout.
    
    Args:
        title: Section heading (renders as uppercase label)
        columns: "1" (default), "2", or "3" — target column count on md+ screens
        children: Field markup (each field wrapped in <div> for flex wrapping)
    """
    col_class = {
        "1": "flex flex-col",
        "2": "flex flex-wrap gap-4 [&>div]:w-[calc(50%-0.5rem)]",
        "3": "flex flex-wrap gap-4 [&>div]:w-[calc(33.333%-0.67rem)]",
    }.get(columns, "flex flex-col")
    
    return Div(
        cls=f"form-section p-5 border-t border-default-medium bg-neutral-primary-soft/30 first-of-type:border-t-0 first-of-type:pt-0",
        children=f"""
            <h3 class="text-sm font-medium text-heading uppercase mb-4">{title}</h3>
            <div class="{col_class}">{children}</div>
        """
    )
```

**Template usage:**
```django
{# add_game.html #}
<c-layouts.add title="New Game">
  <c-section title="Game Details" columns="2">
    <div>{{ form.name }}</div>
    <div>{{ form.platform }}</div>
    <div>{{ form.sort_name }}</div>
    <div>{{ form.year_released }}</div>
    <div>{{ form.original_year_released }}</div>
    <div>{{ form.wikidata }}</div>
  </c-section>
  <c-section title="Status" columns="2">
    <div>{{ form.status }}</div>
    <div>{{ form.mastered }}</div>
  </c-section>
</c-layouts.add>
```

**`cotton/layouts/add.html` changes:**
- Remove hardcoded `{{ form.as_div }}` rendering
- Accept optional `sections` variable (list of rendered `c-section` output)
- If `sections` provided, render them; otherwise fall back to `{{ form.as_div }}` for simple forms
- Keep `additional_row` slot for dual-submit buttons

### 3. CSS/Style Fixes

#### `input.css` changes:
```css
/* Update errorlist */
.errorlist {
  @apply mt-4 mb-1 pl-3 py-2 bg-red-600 text-slate-200 w-full max-w-xl;  /* was w-[300px] */
}

/* Remove: #button-container, .basic-button — unused legacy */

/* Remove: .flowbite-input — custom class is code smell with Tailwind */
/* Remove: flowbite-input @apply block (line 229-234) */

/* Add Flowbite styling for select in stats */
#yearSelect {
  @apply bg-neutral-secondary-medium border border-default-medium text-heading text-sm rounded-base focus:ring-brand focus:border-brand;
}
```

**Important**: The styling previously provided by `.flowbite-input` must be preserved. The element-level `@apply` rules for `input`, `select`, and `textarea` in `input.css` (lines 209-219) already provide equivalent styling. These rules automatically apply to all form inputs without needing custom classes:
- `input:not([type="checkbox"])` — background, border, text, radius, focus ring, padding
- `select` — same base styling as inputs
- `textarea` — same base styling with adjusted padding

**Files to clean up:**
- `common/input.css`: Remove `.flowbite-input` class entirely (lines 229-234)
- `games/forms.py`: Remove `flowbite_input_widget` and `flowbite_password_widget` (lines 22-23)
- `games/forms.py`: Remove `widget=` from `LoginForm` fields (lines 28, 32) — login template uses explicit Tailwind classes already

#### Rewrite `modal.html`:
- Remove stray `</form>` tag and restructure as a proper cotton component
- New `c-modal` component with: `modal_id`, `title`, `size="xl"`, `backdrop_close` variables
- `{{ slot }}` (cotton default slot) for body content — passed as children of `<c-modal>`, no block tags needed
- `{{ footer }}` (optional named slot via `<c-slot name="footer">`) for non-form buttons
- Reusable `cotton/close_button.html` via `<c-close-button />`
- Size mapping via inline `{% if %}`: `{% if size == 'sm' %}max-w-sm{% elif size == 'lg' %}max-w-lg{% else %}max-w-xl{% endif %}`
- Horizontal centering: `mx-auto` on inner container (matching old modal pattern)
- Click-to-dismiss backdrop with `event.stopPropagation()` on inner container
- Flowbite-style styling: `rounded-lg shadow`, `bg-white dark:bg-gray-800`, `sm:p-5`

### 4. Unify Delete Confirmations (All Modal)

**Decision**: GameStatusChange delete confirmation converted from full-page to modal. All three use the same modal pattern.

**Target**: All confirmation modals use the same pattern:

```html
<div class="fixed inset-0 bg-black/70 dark:bg-gray-600/50 ...">
  <div class="relative mx-auto p-6 bg-white dark:bg-gray-900 rounded-lg shadow-lg max-w-md w-full">
    <h2 class="text-xl font-medium text-center">Confirm Action</h2>
    <p class="text-center mt-4 text-sm text-body">Are you sure...?</p>
    {% if details %}
    <ul class="text-center mt-2 text-sm text-body list-disc list-inside">
      <li>{{ detail }}</li>
    </ul>
    {% endif %}
    <p class="text-center mt-3 text-sm font-medium text-red-600">This action cannot be undone.</p>
    <div class="flex gap-3 mt-6">
      <c-button color="red" class="w-full" type="submit">Delete</c-button>
      <c-button color="gray" class="w-full">Cancel</c-button>
    </div>
  </div>
</div>
```

- **Delete Game** (`partials/delete_game_confirmation.html`): Update template to match standard pattern
- **Delete StatusChange** (`gamestatuschange_confirm_delete.html` → `partials/statuschange_delete_confirmation.html`): Adopt the same 2-view pattern as delete-game.
  - Add `delete_statuschange_confirmation` view (GET → renders modal partial) + URL before the delete URL
  - Update `partials/history.html` — add `hx-get="{% url 'games:delete_statuschange_confirmation' change.id %}" hx-target="#global-modal-container"` to the Delete link
  - Create new `partials/statuschange_delete_confirmation.html` using `<c-modal>`, same structure as `delete_game_confirmation.html` (detail list, red warning text, same button layout, `<c-gamestatus>` badge for old status)
  - Modify `GameStatusChangeDeleteView` to only handle POST (remove its GET-rendered template)
  - Delete old `gamestatuschange_confirm_delete.html` after migration
- **Refund Purchase** (`partials/refund_purchase_confirmation.html`): Update template to match standard pattern

### 5. Search Form Enhancement

Wrap `search_field.html` in proper `<form method="get">`:

```html
<form class="max-w-md mx-auto" method="get" x-data x-on:keydown.escape="this.querySelector('input').value=''; this.submit()">
  <!-- input + button -->
</form>
```

This enables:
- Native form submission on Enter
- Potential for "clear all" functionality
- Proper browser form autofill behavior

### 6. Status/Device Selector Styling

Update Alpine.js dropdowns to use consistent button classes:
- Replace `rounded-lg` with `rounded-base`
- Replace `shadow-2xs` with `shadow-xs`
- Standardize border colors with `border-default`
- Use `text-heading` / `text-body` for dark mode compatibility

---

## Templates That Need Changes

| Template | Change | Effort |
|---|---|---|
| `cotton/layouts/add.html` | Add `c-section` component support (title, columns, fields slots) | Medium |
| `add_game.html` | Multi-column flexbox layout, section headers | Medium |
| `add_purchase.html` | Multi-column flexbox layout, simplify dual-submit, section headers | High |
| `add_session.html` | Flexbox layout for timestamps+duration, section headers | Low |
| `add_playevent.html` | Flexbox layout, section headers | Low |
| `add_platform.html` | Section headers (was flat single-column) | Low |
| `add_device.html` | Section headers (was flat single-column) | Low |
| `partials/delete_game_confirmation.html` | Standardize to shared modal pattern | Low |
| `partials/refund_purchase_confirmation.html` | Standardize to shared modal pattern | Low |
| `partials/statuschange_delete_confirmation.html` | New — adopt same 2-view pattern as delete-game (modal, `<c-modal>`, HTMX triggers) | Medium |
| `gamestatuschange_confirm_delete.html` | Delete (replaced by new partial) | Trivial |
| `cotton/modal.html` | Fix missing `<form>` tag | Low |
| `stats.html` | Add Flowbite select styling | Low |
| `partials/gamestatus_selector.html` | Update button classes | Low |
| `partials/sessiondevice_selector.html` | Update button classes | Low |
| `cotton/search_field.html` | Wrap in `<form method="get">` | Low |
| `common/input.css` | Remove legacy, fix errorlist, add select styles | Low |

---

## Implementation Order

### Phase 1: Quick Wins (low risk, no breaking changes)

1. **CSS fixes** (`input.css`) — fix errorlist width, remove legacy `.basic-button` / `#button-container`, add select styles
2. ~~**`modal.html` rewrite**~~ — add missing `<form>` tag, conditional form wrapper ✓ Implemented (uses `{{ slot }}` cotton default slot, no `{% partial %}` tags; `size` defaults to `"xl"` with inline `{% if %}` mapping)
3. **Delete confirmation standardization** — 3 templates → all modal, same pattern (including GameStatusChange: full-page → modal)
4. **Search field enhancement** — wrap in `<form method="get">`
5. **Stats select styling** — add Flowbite select classes
6. **Selector styling updates** — gamestatus + sessiondevice selectors, consistent classes

### Phase 2: `c-section` Component

7. **Create `c-section` component** — title, columns, fields slots
8. **Update `cotton/layouts/add.html`** — support `sections` variable, fallback to `form.as_div`

### Phase 3: Form Layout Overhaul (largest change)

9. **`GameForm`** — section headers + 2-col flexbox (`add_game.html`)
10. **`PlayEventForm`** — section headers + 2-col flexbox
11. **`PurchaseForm`** — section headers + 2/3-col flexbox + simplify dual-submit (`add_purchase.html`)
12. **`SessionForm`** — section headers + flexbox for timestamps+duration (custom rendering already exists)
13. **Simple forms** — `add_platform.html`, `add_device.html` get section headers (single column)

---

## Testing Strategy

- Run `make test` after Phase 1 changes to verify nothing broke
- `tests/test_paths_return_200.py` — URL-level smoke tests (186 tests). All views must have a `test_*_returns_200` test. Adding new views requires a corresponding test to prevent `TemplateDoesNotExist` regressions.
- CSS changes do not require test changes (no test coverage for rendering), but visual verification is recommended

---

## Open Questions

- [x] Simple forms section headers? → **All forms get section headers** for consistency
- [x] CSS Grid or Flexbox? → **Flexbox** — auto-reflow on different screen sizes
- [x] add.html layout variable? → **Option A** — `c-section` cotton component with `title` and `columns` slots
- [x] add_purchase.html dual-submit? → **Simplify** — remove `<tr><td>`, use same `<c-button>` pattern as `add_game.html`
- [x] GameStatusChange modal or full-page? → **Modal** — trigger via HTMX, same pattern as delete-game
- [x] .flowbite-input class? → **Remove entirely** — rely on element-level `@apply` in `input.css`

## Decision Summary

| Question | Decision |
|---|---|
| Section headers on simple forms | Yes, all forms get them |
| Layout approach for multi-column | Flexbox with wrap |
| Layout mechanism in add.html | Option A: `c-section` cotton component |
| Purchase dual-submit | Simplify — single submit button, same as Game |
| GameStatusChange delete | Convert to modal (HTMX-triggered) |
| .flowbite-input class | Remove — preserve styling via element-level `@apply` in `input.css` |
| `modal.html` component | Rewrite with form wrapping, body + footer slots, reusable close button ✓ Implemented

## Build Step

After any CSS changes to `common/input.css`, the compiled output must be rebuilt:

- **`make css`** — one-shot build: `npx @tailwindcss/cli -i ./common/input.css -o ./games/static/base.css`
- **`make dev`** — watch mode: Tailwind rebuilds automatically on every `input.css` save

Running `make dev` is sufficient for development since it concurrently runs Django and the CSS watcher.
Only use `make css` if you only want to rebuild CSS without starting the dev server.

**Important**: Legacy CSS removals (`.basic-button`, `#button-container`, `.flowbite-input`) will only take effect in the browser after a rebuild. The old compiled `base.css` will still contain them until rebuilt.
