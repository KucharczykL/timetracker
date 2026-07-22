# Settings UI kit inventory

Issue [#384](https://github.com/KucharczykL/timetracker/issues/384) builds the
settings UI vocabulary before a settings page consumes it. This inventory is the
implementation boundary: later stages compose these pieces instead of inventing
page-local variants.

| Need | Decision | Existing base | Why |
|---|---|---|---|
| Page width and shell | Reuse | `render_page()` + `ContentContainer` | Settings are a normal page body and must keep the shared max width and gutters. |
| Responsive section layout | New | `ContentContainer`; container-query vocabulary | There is no existing rail/two-pane component. One scaffold owns the mobile stack and desktop rail with the same DOM. |
| Responsive section navigation | Extend dropdown shell, new sheet controller | `Dropdown` trigger/panel contract + native `<dialog>` | Mobile uses one self-explanatory sticky trigger and a modal bottom sheet; desktop uses the sticky rail. One semantic link list moves between them and is never cloned. The sheet deliberately does not reuse anchored positioning or ARIA-menu keyboard behavior. |
| Section headings and surfaces | Reuse | `text-type-subheading`, `text-type-section`, semantic surface/border tokens, `@container` | Outer section headings use the stronger subheading role; nested field-group headings use the section role. |
| Grouped form fields | Extend | `FormFields` | Fieldsets are another organization mode of the existing renderer. A second renderer would drift on errors, checkboxes, hidden fields, and field presentations. |
| Checkbox/select/number/text controls | Reuse | Django fields + `PrimitiveWidgetsMixin` + `FormFields` | The mixin already maps field types to the canonical native controls, including disabled styling and the 42px control height. `field_widget` is filter-criterion machinery and is intentionally excluded. |
| Source and locked indicators | New composite | `Badge` + `Popover` + `TooltipDefinitionList` | One static badge sits beside the field label and contains the source plus a lock icon when pinned. Every source has an accessible hover/focus/tap tooltip explaining its origin; locked variants also include the field-specific reason. Its term/value presentation is the same shared definition-list treatment used by game-name tooltips. It is not a removable `Pill` filter tag. `Badge` gains a semantic `tone` option so callers do not fight its palette with class overrides. Badges on unlocked/editable fields are provisional and subject to the source-badge deletion gate in `settings-panel-epic.md`; a badge never replaces a visible field label. |
| Locked field | Extend through metadata | Django `Field.disabled`, `DISABLED_CONTROL_CLASS`, `FormFieldPresentation` | A real disabled control supplies native semantics and the existing disabled look. The merged source/lock badge stays on the label line while the human-readable reason stays below the control. |
| Masked secret | New | Native read-only password input + canonical input class | The component never accepts or emits the secret. It renders only a fixed mask (or an empty state), so view source cannot reveal the value. |
| Live save | New custom element, reuse request pattern | `fetchWithHtmxTriggers` and `behaviors/select.ts` | A form-level delegated behavior covers every native setting control, performs an optimistic PATCH, and restores the last committed value on failure. It follows `register_element`/`gen_element_types`. |
| Saved feedback | Extend API response | Django messages + `HTMXMessagesMiddleware` | Successful settings PATCHes enqueue a success message. `fetchWithHtmxTriggers` turns the `HX-Trigger` response into the existing toast; failures use the same client error toast as select PATCHes. |
| Tests before consumers | New isolated harnesses | component tests, Vitest custom-element tests, Playwright synthetic URLconf | The kit is exercised without `/settings` or `/admin-settings`, keeping Stage 3 independent of page wiring in Stages 4 and 8. |

## Composition contract

A page supplies ordered `SettingsSection` values to `SettingsScaffold`. Inside a
section, ordinary fields are a Django form rendered by grouped `FormFields`.
`SettingsFieldLayout` exposes the only supported field flows: a
`w-full max-w-xl` single column, a responsive two-column grid, or a responsive
three-column grid. `LiveSettingFields` always composes the first, so it may fill
a narrow pane but can never stretch across the whole wide content pane.
The scaffold owns section hierarchy and rhythm: its outer title uses
`text-type-subheading` (20px/700), while nested field-group legends use
`text-type-section` (18px/600). Title and description form an 8px header group,
separated by 24px from section content. Consumers provide content only; they do
not recreate or tune these styles per page. Server-rendered and browser tests
lock the anatomy, computed typography, and gaps.
`SettingFieldState` adds the registry key, origin, help, and optional lock reason;
the kit puts the merged source/lock badge beside the label and gives every badge
an origin tooltip. Locked tooltips repeat the field-specific reason, while help
and the visible lock reason stay below the control. The kit also stamps the
live-save hook and sets Django's real `disabled` flag when locked.
`LiveSettingFields` wraps that `FormFields` output and PATCHes the endpoint
template only for controls carrying `data-live-setting-control`; a
`data-setting-key` identifies a setting but does not by itself grant save
ownership. Successful saves dispatch one validated `setting-committed` response,
which each matching `SettingSourceBadgeElement` presents independently. Checkbox rows keep a 24px
minimum label-to-control gap and prevent the control from shrinking; spare
space is still distributed by `justify-between` inside the capped field column.

Infrastructure secrets use `MaskedSecretField` instead of a bound value. Its API
accepts only whether a value exists, never the value itself.
