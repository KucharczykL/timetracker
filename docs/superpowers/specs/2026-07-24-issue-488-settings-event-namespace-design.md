# Issue #488 — Namespace committed settings events by mutation layer

**Status:** design approved, adversarially reviewed (Fable second opinion)
**Issue:** https://github.com/KucharczykL/timetracker/issues/488
**Follows:** #390; stacks on #487's `SettingMutation` command layer (consumes the fact that both write paths are now explicit, separately-authorized commands)
**Follow-up filed:** #497 (migrate `SettingSource`/`SOURCE_METADATA` to the same codegen mechanism this issue introduces for `SettingNamespace` — explicitly out of scope here)

## Problem

Settings presenters coordinate committed changes via a single DOM event, `setting-committed`, carrying `{key, value, source, locked}` (`ts/settings-events.ts`). The one listener today, `SettingSourceBadge` (`ts/elements/setting-source-badge.ts`), filters incoming events by `key` only. Now that personal and site controls both write the same registry keys through two independent, separately-authorized commands, a badge cannot tell "my key committed on this page" from "the same key committed somewhere else" — the event is silent about which mutation surface (user vs site) actually fired.

No page renders both namespaces simultaneously today, so this isn't a live bug — it's a type-safety gap that a future dual-namespace surface (e.g. a superuser inspecting another user's preferences) would immediately expose, and the `source` field cannot substitute: `source` reports *where the resolved value came from* (env/database/user/default), which is orthogonal to *which command emitted the event* — a personal CLEAR that falls through to an env-shadowed value reports `source=env` while still being a `namespace=user` mutation.

## Goal

Add a typed `namespace` discriminator (`user` | `site`) to the committed-settings event, make the server the sole authority for its value, and require every listener to match both `key` and `namespace` before reacting.

## Architecture

### Where namespace comes from

The server is authoritative — not a client-side static configuration. Each endpoint pair hard-codes its own literal:

| Endpoint | namespace |
|---|---|
| `update_user_setting`, `list_user_settings` | `SettingNamespace.USER` |
| `update_site_setting`, `list_site_settings` | `SettingNamespace.SITE` |

This was the central design choice, made explicitly for robustness over minimal diff: a client-side prop threaded per-page (e.g. a `namespace` prop on `LiveSettingFields` alone, trusted without verification) would let a copy-paste wiring bug — the wrong `patch_url_template` paired with the wrong `namespace` prop — silently mislabel every mutation from that surface, with listeners quietly ignoring events they should own. Making the server the authority, and having emitters verify their own expectation against it, closes that hole. (See "Emitter self-check" below.)

### New type: `SettingNamespace`

```python
class SettingNamespace(StrEnum):
    USER = "user"
    SITE = "site"

SETTING_NAMESPACE_CHOICES: tuple[tuple[str, str], ...] = (
    ("user", "User"),
    ("site", "Site"),
)
```

Placed in `timetracker/settings_commands.py`, not `timetracker/config.py` and not `timetracker/settings_registry.py`. Reasoning:

- `SettingScope` (`timetracker/settings_registry.py`) already has `USER`/`SITE`/`INFRA` — value-identical to two of `SettingNamespace`'s members, but a **different concept** (scope describes a *key's* registry classification; namespace describes *which command* emitted an event). Reusing `SettingScope` directly would wrongly admit `INFRA` as a possible event namespace and would conflate the two ideas at their point of definition.
- `settings_commands.py` is the module that **implements** the two mutation surfaces (`change_user_setting`, `change_site_setting`) — the namespace enum's two members map 1:1 onto those two functions. `games/api.py` already imports from this module, so no new import edge is introduced.
- The Python badge/field-builder layer (`common/components/settings_kit.py`) does **not** need the enum itself — it accepts `namespace: str`, matching its existing loose `source: str` parameter. This avoids any question of `common/components` needing to import from `games/` or `timetracker/settings_commands` — the enum stays confined to `timetracker/` and `games/api.py`, both of which already sit above `common/components` in the existing import direction.

### Codegen, not hand-mirroring

`common/components/ts_codegen.py`'s `render_choice_vocabulary()` already generates a closed TS vocabulary (values array + type + label map) from a Python `(value, label)` sequence — the mechanism that produces `THEME_PREFERENCES` from `THEME_CHOICES` today (`gen_element_types.py:58-63`). `SettingNamespace` uses the identical mechanism from day one:

- `games/management/commands/gen_element_types.py` gets a new target, `ts/generated/settings-vocabulary.ts`, generated via `render_choice_vocabulary(type_name="SettingNamespace", values_name="SETTING_NAMESPACES", labels_name="SETTING_NAMESPACE_LABELS", choices=SETTING_NAMESPACE_CHOICES)`.
- The output filename is deliberately not `settings-events.ts` (which would collide in spirit with the hand-written `ts/settings-events.ts`) and deliberately broad (`settings-vocabulary.ts`, not `setting-namespace.ts`) so `SettingSource`'s eventual migration (#497) lands in the same generated file without a rename.
- `ts/settings-events.ts` imports `SettingNamespace`/`SETTING_NAMESPACES` from the generated module rather than hand-declaring an `as const` array — killing the exact hand-mirror-with-no-drift-guard pattern that `SETTING_SOURCES` still has (tracked separately as #497, explicitly deferred, not fixed here).

### The event contract

`ResolvedSetting` (`ts/settings-events.ts`) gains a fourth required field:

```typescript
export interface ResolvedSetting {
  key: string;
  value: SettingValue;
  source: SettingSource;
  locked: boolean;
  namespace: SettingNamespace;
}
```

`parseResolvedSetting` validates `namespace` membership against `SETTING_NAMESPACES` the same way it validates `source` today — throws on missing or unknown values. Because the server embeds `namespace` in every `SettingOut` response, `dispatchSettingCommitted`'s signature is unchanged: it already just parses whatever JSON the server returned, which now always includes the field.

### Server: `SettingOut` and `_setting_out`

```python
class SettingOut(Schema):
    key: str
    value: str | int | None
    source: str
    locked: bool
    namespace: SettingNamespace
```

`_setting_out(key, resolved, *, locked=None, namespace: SettingNamespace)` — `namespace` is a **required** keyword argument with no default, deliberately diverging from `source`'s loose `str` typing on the schema: this field exists specifically to prevent exactly the mislabeling class of bug the issue is about, so every one of the 4 call sites (`list_user_settings`, `update_user_setting`, `list_site_settings`, `update_site_setting`) must be explicit. Forgetting one is a mypy error and an immediate `TypeError`, not a silent wrong default.

### Threading namespace to the badge (listener-side static configuration)

Regardless of how the *emitted* event's namespace is computed, a listener still has to be told, at render time, which namespace it cares about — that part is unavoidable in any design. `SettingSourceBadgeProps` gains `namespace: str`; `SettingSourceBadge(source, *, locked=False, reason="", id="", setting_key="", namespace)` threads it through; `prepare_setting_fields` and `LiveSettingFields(form, *, states, patch_url_template, csrf, namespace, groups=None, presentations=None)` carry it down from the two view functions:

- `games/views/settings.py`'s `user_settings()` passes `namespace=SettingNamespace.USER`.
- `admin_settings()` passes `namespace=SettingNamespace.SITE`.

`SettingSourceBadgeElement.onCommitted` filters on both: `if (resolved.key !== this.settingKey || resolved.namespace !== this.namespace) return;`.

### Emitter self-check

`LiveSettingFieldsElement` already defends its own contract — `if (resolved.key !== key) throw` (`live-setting-fields.ts:193`) — because the element *chose* which endpoint to call via its `patch_url_template` and therefore has a genuine expectation about what comes back. The identical reasoning applies to namespace, and skipping it was an unprincipled omission: `LiveSettingFieldsProps` gains `namespace: str` too, and the element throws if `resolved.namespace !== this.namespace`. This is the one deliberate departure from "only listeners need static namespace config" — the emitter gets one too, purely as a self-verification, mirroring its existing key check.

`ThemeCoordinator`'s existing own-contract assertion block (the one that already checks `resolved.key`, `resolved.value`, `resolved.locked` after its PATCH to `/api/settings/user/THEME`) gains `resolved.namespace !== "user"` as one more condition in the same throw. No new listening behavior — `ThemeCoordinator` doesn't listen to the event today and nothing in the issue's acceptance criteria asks it to start.

### Reload behavior

No functional change. `reloadAfterSettingSave()` (`ts/settings-reload.ts`) is a same-request side effect on the control that was just PATCHed, gated by a `data-reload-after-save` DOM attribute — it is namespace-agnostic by construction (a control only ever belongs to the one namespace its host page renders) and doesn't listen to the event system.

### Documentation

A doc-comment block at the top of `ts/settings-events.ts` covering:

- The listener contract: a listener must match both `key` and `namespace` before reacting; matching `key` alone is insufficient once namespace exists.
- Explicit disambiguation of three same-valued vocabularies that co-occur in one payload: `SettingSource.USER` (the resolved value's *origin layer*), the registry's `SettingScope.USER` (whether a *key* is user- or site-scoped — a wholly separate axis, not present in this payload at all), and `SettingNamespace.USER` (which *command/endpoint* emitted this specific event). The concrete case worth naming explicitly: a personal CLEAR that falls through to an env-shadowed value reports `source=env`, `namespace=user` — namespace is never derivable from source.
- Extension rule: adding a third namespace means extending `SETTING_NAMESPACE_CHOICES`, updating every `_setting_out` call site to pass an explicit literal, and updating every listener explicitly — there is no wildcard/catch-all listening mode by design.

### Minor hygiene

`SettingSourceBadgeElement.onCommitted`'s parse-failure catch currently swallows silently (`catch { return; }`). Given the contract is now stricter (four required fields instead of three), a `console.error` on parse failure matches the codebase's existing loud-contract idiom elsewhere and makes a future malformed-event bug visible instead of silently inert.

## Testing

- **Python:** an endpoint test parametrized over all 4 endpoints, asserting `namespace` is correct on both GET-list entries and PATCH responses.
- **Vitest, existing fixtures requiring an update** (each constructs a `ResolvedSetting`-shaped stub that must gain `namespace`): `ts/theme-coordinator.test.ts`, `ts/elements/setting-source-badge.test.ts`, `ts/elements/live-setting-fields.test.ts`.
- **Vitest, new:**
  - Two `SettingSourceBadgeElement`s, same `key`, `namespace="user"` vs `namespace="site"`; dispatch one committed event per namespace; assert each badge updates only from its own namespace's event.
  - `parseResolvedSetting` rejects a payload with a missing or unknown `namespace`.
  - `LiveSettingFieldsElement` throws when the server's response `namespace` doesn't match its own configured namespace.
- **E2E, compatibility sweep** (check for response-shape assertions needing the new field; no functional change expected): `test_admin_settings_page_e2e.py`, `test_settings_page_e2e.py`, `test_settings_ui_kit_e2e.py`, `test_theme_e2e.py`.
- **E2E, new, bidirectional:**
  - On the real admin settings page, inject a synthetic `namespace="user"` committed event for a key also rendered there → the real site badge must not react.
  - On the real user settings page, inject a synthetic `namespace="site"` committed event for `THEME` → the real user badge / `ThemeCoordinator` state must not react.
  - Synthetic injection is the only way to exercise cross-namespace behavior today, since no real page hosts both namespaces simultaneously (confirmed: the navbar's `ThemeToggle` is disabled via `is_settings_page` on both settings pages) — this is a documented constraint of the current UI, not a test-coverage gap.

## Out of scope (filed separately)

- **#497** — migrate `SettingSource`/`SETTING_SOURCES` and `SOURCE_METADATA`'s hand-written labels to the same `render_choice_vocabulary` codegen mechanism this issue introduces for `SettingNamespace`. Deliberately not folded in here: it touches a third file (badge UI label sourcing) beyond this issue's literal scope, and stands alone as a well-scoped follow-up now that the codegen precedent exists.
