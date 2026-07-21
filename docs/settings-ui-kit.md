# Settings UI kit inventory

Issue [#384](https://github.com/KucharczykL/timetracker/issues/384) builds the
settings UI vocabulary before a settings page consumes it. This inventory is the
implementation boundary: later stages compose these pieces instead of inventing
page-local variants.

| Need | Decision | Existing base | Why |
|---|---|---|---|
| Page width and shell | Reuse | `render_page()` + `ContentContainer` | Settings are a normal page body and must keep the shared max width and gutters. |
| Responsive section layout | New | `ContentContainer`; container-query vocabulary | There is no existing rail/two-pane component. One scaffold owns the mobile stack and desktop rail with the same DOM. |
| Anchor-chip overflow | New behavior, shared math | Quick-filter `ResizeObserver` priority-plus pattern | The nav moves, rather than clones, anchors so focus and state survive. Its desktop bypass and menu-role changes differ from filter facets, so only the width-fit calculation is extracted; the load-bearing quick-filter movement stays specialized. |
| Section headings and surfaces | Reuse | `text-type-section`, semantic surface/border tokens, `@container` | The visual audit reserved this type token and established the surface/radius vocabulary for this kit. |
| Grouped form fields | Extend | `FormFields` | Fieldsets are another organization mode of the existing renderer. A second renderer would drift on errors, checkboxes, hidden fields, and extras. |
| Checkbox/select/number/text controls | Reuse | Django fields + `PrimitiveWidgetsMixin` + `FormFields` | The mixin already maps field types to the canonical native controls, including disabled styling and the 42px control height. `field_widget` is filter-criterion machinery and is intentionally excluded. |
| Source and locked indicators | New composite | `Badge` | Indicators are static labels, not removable `Pill` filter tags. `Badge` gains a semantic `tone` option so callers do not fight its palette with class overrides. |
| Locked field | Extend through metadata | Django `Field.disabled`, `DISABLED_CONTROL_CLASS`, `FormFields.extras` | A real disabled control supplies native semantics and the existing disabled look. The kit adds the source badge and human-readable reason beside it. |
| Masked secret | New | Native read-only password input + canonical input class | The component never accepts or emits the secret. It renders only a fixed mask (or an empty state), so view source cannot reveal the value. |
| Live save | New custom element, reuse request pattern | `fetchWithHtmxTriggers` and `behaviors/select.ts` | A form-level delegated behavior covers every native setting control, performs an optimistic PATCH, and restores the last committed value on failure. It follows `register_element`/`gen_element_types`. |
| Saved feedback | Extend API response | Django messages + `HTMXMessagesMiddleware` | Successful settings PATCHes enqueue a success message. `fetchWithHtmxTriggers` turns the `HX-Trigger` response into the existing toast; failures use the same client error toast as select PATCHes. |
| Tests before consumers | New isolated harnesses | component tests, Vitest custom-element tests, Playwright synthetic URLconf | The kit is exercised without `/settings` or `/admin-settings`, keeping Stage 3 independent of page wiring in Stages 4 and 8. |

## Composition contract

A page supplies ordered `SettingsSection` values to `SettingsScaffold`. Inside a
section, ordinary fields are a Django form rendered by grouped `FormFields`.
`SettingFieldState` adds the registry key, origin, help, and optional lock reason;
the kit stamps the live-save hook and sets Django's real `disabled` flag when
locked. `LiveSettingFields` wraps that unchanged `FormFields` output and PATCHes
the endpoint template for controls that carry a setting key.

Infrastructure secrets use `MaskedSecretField` instead of a bound value. Its API
accepts only whether a value exists, never the value itself.
