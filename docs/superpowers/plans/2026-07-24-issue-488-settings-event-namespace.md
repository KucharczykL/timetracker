# Settings Event Namespace (#488) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a server-authoritative `namespace` (`user`/`site`) discriminator to the committed-settings event, codegenned rather than hand-mirrored, so every listener matches both `key` and `namespace` before reacting.

**Architecture:** `SettingNamespace(StrEnum)` lives in `timetracker/settings_commands.py` (the module implementing the two namespaces' commands). `games/api.py` stamps it on every `SettingOut` response (`_setting_out`'s `namespace` becomes a required kwarg, no default). The TS side generates `SettingNamespace`/`SETTING_NAMESPACES` via the existing `render_choice_vocabulary` codegen (same mechanism that already produces `THEME_PREFERENCES`) into a new `ts/generated/settings-vocabulary.ts`. `ResolvedSetting` gains a required `namespace` field, validated in `parseResolvedSetting`. The badge (`SettingSourceBadge`) is a listener and needs a static per-instance `namespace` to filter on; `LiveSettingFields` (the emitter) gets the identical static `namespace` too, purely to self-check its own PATCH response against what it expects — mirroring its existing `resolved.key !== key` guard. `ThemeCoordinator`'s existing own-contract check gains the same assertion.

**Tech Stack:** Django 6 + Django Ninja, TypeScript compiled via `tsc`, vitest, Playwright e2e. Python 3.14.

## Global Constraints

- Run every command inside the Nix dev shell: prefix with `direnv exec .`. In a fresh worktree run `direnv allow .` once first.
- After any codegen-affecting Python change, run `direnv exec . uv run python manage.py gen_element_types` before running `tsc`/vitest/e2e against the regenerated file — `ts/generated/` is gitignored, never edited by hand, never committed.
- Run `direnv exec . make ts` after editing any `.ts` file so `dist/` reflects it before e2e runs.
- Name compound/primitive roles explicitly; unabbreviated identifiers.
- Verification gate before "done"/PR: full `direnv exec . make check` (lint + format-check + mypy + ts-check + vitest + entire pytest incl. `e2e/`) green. Never a hand-picked subset.
- Commit style: end messages with `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
- **Do not** touch `SettingSource`/`SETTING_SOURCES`/`SOURCE_METADATA` — that hand-mirror problem is tracked separately as issue #497, explicitly out of scope here.

**Spec:** `docs/superpowers/specs/2026-07-24-issue-488-settings-event-namespace-design.md` (read it first).

---

### Task 1: `SettingNamespace` enum + codegen target

**Files:**
- Modify: `timetracker/settings_commands.py` (add enum + choices tuple)
- Modify: `games/management/commands/gen_element_types.py` (new target)
- Test: `tests/test_settings_commands.py` (already tests `timetracker/settings_commands.py`, where the enum lives)

**Interfaces:**
- Produces: `SettingNamespace(StrEnum)` with `USER = "user"`, `SITE = "site"`; `SETTING_NAMESPACE_CHOICES: tuple[tuple[str, str], ...] = (("user", "User"), ("site", "Site"))`. Generated file `ts/generated/settings-vocabulary.ts` exports `SETTING_NAMESPACES`, `type SettingNamespace`, `SETTING_NAMESPACE_LABELS`.

- [ ] **Step 1: Add the enum + choices to `timetracker/settings_commands.py`**

Near the top of the module, after the existing imports (the file already imports `StrEnum` for `SettingOperation` if present — check; if not, add `from enum import StrEnum` to the existing `enum` import):

```python
class SettingNamespace(StrEnum):
    """Which mutation surface emitted a settings-committed event: the personal
    settings page or the site-admin settings page. Distinct from SettingScope
    (a *key's* registry classification) and from SettingSource (where a
    resolved *value* came from) — namespace is never derivable from either."""

    USER = "user"
    SITE = "site"


SETTING_NAMESPACE_CHOICES: tuple[tuple[str, str], ...] = (
    ("user", "User"),
    ("site", "Site"),
)
```

Add `"SettingNamespace"` and `"SETTING_NAMESPACE_CHOICES"` to the module's `__all__`.

- [ ] **Step 2: Write a test asserting the enum values**

```python
def test_setting_namespace_values():
    from timetracker.settings_commands import SettingNamespace

    assert SettingNamespace.USER == "user"
    assert SettingNamespace.SITE == "site"
```

Run: `direnv exec . uv run pytest tests/test_settings_commands.py -k setting_namespace_values -v`
Expected: PASS immediately (no red/green needed — this is a data assertion, not new behavior).

- [ ] **Step 3: Wire the codegen target**

In `games/management/commands/gen_element_types.py`, add the import:

```python
from timetracker.settings_commands import SETTING_NAMESPACE_CHOICES
```

Add to the `targets` dict (after the `theme-preferences.ts` entry):

```python
            output_dir / "settings-vocabulary.ts": render_choice_vocabulary(
                type_name="SettingNamespace",
                values_name="SETTING_NAMESPACES",
                labels_name="SETTING_NAMESPACE_LABELS",
                choices=SETTING_NAMESPACE_CHOICES,
            ),
```

- [ ] **Step 4: Generate and inspect**

Run: `direnv exec . uv run python manage.py gen_element_types`
Expected output includes `Wrote .../ts/generated/settings-vocabulary.ts`.

Run: `cat ts/generated/settings-vocabulary.ts`
Expected content:

```typescript
// GENERATED by `manage.py gen_element_types` — do not edit.

export const SETTING_NAMESPACES = ["user", "site"] as const;
export type SettingNamespace = typeof SETTING_NAMESPACES[number];
export const SETTING_NAMESPACE_LABELS = {
  user: "User",
  site: "Site",
} satisfies Record<SettingNamespace, string>;
```

- [ ] **Step 5: Commit**

```bash
git add timetracker/settings_commands.py games/management/commands/gen_element_types.py tests/test_settings_commands.py
git commit -m "feat(settings): add SettingNamespace enum + codegen target

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

(`ts/generated/settings-vocabulary.ts` is gitignored — do not add it.)

---

### Task 2: Server stamps `namespace` on every `SettingOut`

**Files:**
- Modify: `games/api.py` (`SettingOut`, `_setting_out`, all 4 settings endpoints)
- Test: `tests/test_settings_api.py` — the existing test file for exactly these 4 endpoints. It already has `auth_client`/`superuser_client` fixtures and `_user_url()`/`_user_patch_url(key)`/`_site_url()`/`_site_patch_url(key)`/`_patch(client, url, value)`/`_setting(payload_list, key)` module-local helpers (lines 19-98) — reuse them, don't invent parallel ones.

**Interfaces:**
- Consumes: Task 1's `SettingNamespace`.
- Produces: `SettingOut.namespace: SettingNamespace`; `_setting_out(key, resolved, *, locked=None, namespace: SettingNamespace) -> dict`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_settings_api.py` (matching its existing helper usage):

```python
def test_user_endpoints_report_user_namespace(auth_client):
    listed = _setting(auth_client.get(_user_url()).json(), "THEME")
    assert listed["namespace"] == "user"

    patched = _patch(auth_client, _user_patch_url("THEME"), "dark").json()
    assert patched["namespace"] == "user"


def test_site_endpoints_report_site_namespace(superuser_client):
    listed = _setting(superuser_client.get(_site_url()).json(), "DEFAULT_CURRENCY")
    assert listed["namespace"] == "site"

    patched = _patch(
        superuser_client, _site_patch_url("DEFAULT_CURRENCY"), "eur"
    ).json()
    assert patched["namespace"] == "site"
```

- [ ] **Step 2: Run to verify failures**

Run: `direnv exec . uv run pytest tests/test_settings_api.py -k "reports_user_namespace or reports_site_namespace" -v`
Expected: FAIL — `KeyError: 'namespace'`.

- [ ] **Step 4: Update `SettingOut` and `_setting_out`**

In `games/api.py`, add to the existing `timetracker.settings_commands` import:

```python
from timetracker.settings_commands import (
    SettingLockedError,
    SettingNamespace,
    change_site_setting,
    change_user_setting,
)
```

Update the schema (lines ~537-548):

```python
class SettingOut(Schema):
    """One resolved setting for the settings panel.

    ``value`` is ``str | int | None`` (device id is an int, unset is None) — a
    ``str``-only field would 500. ``locked`` marks an env/`.env`/`.ini`-pinned
    value; ``/user`` forces it ``False`` (see :func:`list_user_settings`).
    ``namespace`` identifies which mutation surface produced this entry — the
    personal or site-admin page — independent of ``source`` (where the
    resolved value came from).
    """

    key: str
    value: str | int | None
    source: str
    locked: bool
    namespace: SettingNamespace
```

Update `_setting_out` (line ~564):

```python
def _setting_out(
    key: SettingKey,
    resolved,
    *,
    locked: bool | None = None,
    namespace: SettingNamespace,
) -> dict:
    return {
        "key": key,
        "value": resolved.value,
        "source": resolved.source,
        "locked": resolved.locked if locked is None else locked,
        "namespace": namespace,
    }
```

- [ ] **Step 5: Update the 4 call sites**

`list_user_settings` (line ~590-593):

```python
    return [
        _setting_out(
            key,
            resolve_for_user_with_origin(request.user, key),
            locked=False,
            namespace=SettingNamespace.USER,
        )
        for key in _settings_of_scope(SettingScope.USER)
    ]
```

`update_user_setting` (line ~614):

```python
    return _setting_out(
        key, mutation.effective, locked=False, namespace=SettingNamespace.USER
    )
```

`list_site_settings` (line ~623-626):

```python
    return [
        _setting_out(key, resolve_with_origin(key), namespace=SettingNamespace.SITE)
        for key in _settings_of_scope(SettingScope.SITE, SettingScope.USER)
    ]
```

`update_site_setting` (line ~648):

```python
    return _setting_out(key, mutation.effective, namespace=SettingNamespace.SITE)
```

- [ ] **Step 6: Run to verify pass**

Run: `direnv exec . uv run pytest tests/test_settings_api.py -v`
Expected: PASS (new + all pre-existing tests in that file).

- [ ] **Step 7: Commit**

```bash
git add games/api.py tests/test_settings_api.py
git commit -m "feat(settings): stamp namespace on every SettingOut response

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: `ResolvedSetting` gains `namespace`; `parseResolvedSetting` validates it

**Files:**
- Modify: `ts/settings-events.ts`
- Test: `ts/elements/setting-source-badge.test.ts` (its `"resolved setting events"` describe block already covers `parseResolvedSetting`)

**Interfaces:**
- Consumes: Task 1's generated `ts/generated/settings-vocabulary.ts` (`SettingNamespace`, `SETTING_NAMESPACES`).
- Produces: `ResolvedSetting.namespace: SettingNamespace` (required); `parseResolvedSetting` throws on missing/unknown `namespace`.

- [ ] **Step 1: Write the failing tests**

In `ts/elements/setting-source-badge.test.ts`, extend the existing `"accepts only complete payloads with recognized sources"` test (replace it entirely with):

```typescript
  it("accepts only complete payloads with recognized sources and namespaces", () => {
    expect(parseResolvedSetting({
      key: "THEME",
      value: "dark",
      source: "user",
      locked: false,
      namespace: "user",
    })).toEqual({
      key: "THEME", value: "dark", source: "user", locked: false, namespace: "user",
    });

    for (const invalid of [
      null,
      { key: "THEME", value: "dark", source: "mystery", locked: false, namespace: "user" },
      { key: "THEME", value: { nested: true }, source: "user", locked: false, namespace: "user" },
      { key: "", value: "dark", source: "user", locked: false, namespace: "user" },
      { key: "THEME", value: "dark", source: "user", namespace: "user" },
      { key: "THEME", value: "dark", source: "user", locked: false },
      { key: "THEME", value: "dark", source: "user", locked: false, namespace: "planet" },
    ]) {
      expect(() => parseResolvedSetting(invalid)).toThrow("Invalid resolved setting");
    }
  });
```

- [ ] **Step 2: Run to verify it fails**

Run: `direnv exec . pnpm test:ts -- setting-source-badge -t "recognized sources and namespaces"`
Expected: FAIL — the valid-payload assertion fails (`namespace` not yet part of the parsed/returned shape) and/or TS fails to compile (`ResolvedSetting` has no `namespace` field yet, so the "valid" literal isn't assignable — but since `parseResolvedSetting` takes `unknown`, this is a runtime failure, not a compile failure: the returned object simply won't include `namespace` yet, failing `toEqual`).

- [ ] **Step 3: Regenerate the vocabulary module (if not already done in Task 1) and update `ts/settings-events.ts`**

Run: `direnv exec . uv run python manage.py gen_element_types` (idempotent if Task 1 already ran it).

Update `ts/settings-events.ts`:

```typescript
import {
  SETTING_NAMESPACES,
  type SettingNamespace,
} from "./generated/settings-vocabulary.js";

export type { SettingNamespace };

export type SettingValue = string | number | boolean | null;

export const SETTING_SOURCES = [
  "user",
  "env_file",
  "env",
  "dotenv",
  "ini",
  "database",
  "default",
] as const;
export type SettingSource = typeof SETTING_SOURCES[number];

/**
 * A committed setting's full resolved state. Two axes commonly get confused
 * because they share the string "user": `source` is WHERE the resolved value
 * came from (env/database/user/default) — a property of the *value*.
 * `namespace` is WHICH mutation surface (the personal settings page or the
 * site-admin page) emitted this event — a property of the *command that ran*.
 * They are independent: a personal preference CLEAR that falls through to an
 * env-shadowed value reports `source: "env"` while `namespace` stays `"user"`,
 * because a user-scoped command still executed it. (A third, unrelated axis —
 * the registry's SettingScope, whether a *key* is user- or site-scoped — never
 * appears in this payload at all.)
 *
 * Listener contract: match BOTH `key` and `namespace` before reacting to a
 * committed event. Matching `key` alone was sufficient before namespace
 * existed and is no longer safe — a badge or coordinator that only checks
 * `key` could react to the wrong page's mutation.
 *
 * Adding a third namespace: extend `SETTING_NAMESPACE_CHOICES` in
 * `timetracker/settings_commands.py`, update every `_setting_out` call site
 * in `games/api.py` to pass an explicit namespace literal, and update every
 * listener explicitly — there is no wildcard/catch-all listening mode.
 */
export interface ResolvedSetting {
  key: string;
  value: SettingValue;
  source: SettingSource;
  locked: boolean;
  namespace: SettingNamespace;
}

export const SETTING_COMMITTED_EVENT = "setting-committed" as const;

function isSettingValue(value: unknown): value is SettingValue {
  return value === null || ["string", "number", "boolean"].includes(typeof value);
}

export function parseResolvedSetting(value: unknown): ResolvedSetting {
  if (typeof value !== "object" || value === null) {
    throw new Error("Invalid resolved setting response");
  }
  const candidate = value as Record<string, unknown>;
  if (
    typeof candidate.key !== "string" ||
    candidate.key.length === 0 ||
    !isSettingValue(candidate.value) ||
    !SETTING_SOURCES.includes(candidate.source as SettingSource) ||
    typeof candidate.locked !== "boolean" ||
    !SETTING_NAMESPACES.includes(candidate.namespace as SettingNamespace)
  ) {
    throw new Error("Invalid resolved setting response");
  }
  return {
    key: candidate.key,
    value: candidate.value,
    source: candidate.source as SettingSource,
    locked: candidate.locked,
    namespace: candidate.namespace as SettingNamespace,
  };
}

export function dispatchSettingCommitted(value: unknown): ResolvedSetting {
  const resolved = parseResolvedSetting(value);
  document.body.dispatchEvent(
    new CustomEvent<ResolvedSetting>(SETTING_COMMITTED_EVENT, {
      detail: resolved,
      bubbles: true,
    }),
  );
  return resolved;
}
```

- [ ] **Step 4: Run to verify pass**

Run: `direnv exec . pnpm test:ts -- setting-source-badge`
Expected: this specific test PASSes; other tests in this file will now fail (their fixtures lack `namespace`) — that's expected, fixed in Task 5. Confirm via the test output that only the fixture-shape failures remain, not the new validation test.

- [ ] **Step 5: Commit**

```bash
git add ts/settings-events.ts tests/test_settings_commands.py
git commit -m "feat(settings): ResolvedSetting gains namespace; parseResolvedSetting validates it

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

(Do not commit `ts/generated/settings-vocabulary.ts` — gitignored.)

---

### Task 4: Thread `namespace` through the Python badge/field-builder layer

**Files:**
- Modify: `common/components/custom_elements.py` (`SettingSourceBadgeProps`, `LiveSettingFieldsProps`)
- Modify: `common/components/settings_kit.py` (`SettingSourceBadge`, `prepare_setting_fields`, `LiveSettingFields`)

**Interfaces:**
- Produces: `SettingSourceBadge(source, *, locked=False, reason="", id="", setting_key="", namespace: str)`; `prepare_setting_fields(form, states, presentations=None, *, namespace: str)`; `LiveSettingFields(form, *, states, patch_url_template, csrf, namespace: str, groups=None, presentations=None)`. All three take `namespace` as a **required** keyword-only argument (no default) — this deliberately breaks every existing call site so none can be missed; Task 8/9 fix them.
- Note: this layer takes `namespace: str` (loose), **not** the `SettingNamespace` enum — `common/components` does not need to import from `timetracker.settings_commands`; callers pass `SettingNamespace.USER`/`SettingNamespace.SITE` (StrEnum members satisfy a `str` parameter directly, no `.value` needed).

- [ ] **Step 1: Update the TypedDicts in `common/components/custom_elements.py`**

```python
class SettingSourceBadgeProps(TypedDict):
    key: str
    namespace: str


register_element("setting-source-badge", "SettingSourceBadge", SettingSourceBadgeProps)
```

```python
class LiveSettingFieldsProps(TypedDict):
    patch_url_template: str  # contains the literal __key__ placeholder
    csrf: str
    namespace: str


register_element("live-setting-fields", "LiveSettingFields", LiveSettingFieldsProps)
```

- [ ] **Step 2: Update `SettingSourceBadge` in `common/components/settings_kit.py`**

Add `namespace: str` as a required keyword-only parameter (after `setting_key: str = ""`, before the closing `)`):

```python
def SettingSourceBadge(
    source: str,
    *,
    locked: bool = False,
    reason: str = "",
    id: str = "",
    setting_key: str = "",
    namespace: str,
) -> Node:
```

Update the final return line:

```python
    return _SettingSourceBadge(key=setting_key, namespace=namespace)[popover]
```

- [ ] **Step 3: Update `prepare_setting_fields`**

Add `namespace: str` as a required keyword-only parameter:

```python
def prepare_setting_fields(
    form,
    states: Mapping[str, SettingFieldState],
    presentations: Mapping[str, FormFieldPresentation] | None = None,
    *,
    namespace: str,
) -> dict[str, FormFieldPresentation]:
```

Update the `SettingSourceBadge(...)` call inside it (~line 430-436):

```python
        label_extra = SettingSourceBadge(
            state.source,
            locked=state.locked,
            reason=_lock_reason(state) if state.locked else "",
            id=tooltip_id,
            setting_key=state.key,
            namespace=namespace,
        )
```

- [ ] **Step 4: Update `LiveSettingFields`**

```python
def LiveSettingFields(
    form,
    *,
    states: Mapping[str, SettingFieldState],
    patch_url_template: str,
    csrf: str,
    namespace: str,
    groups: Sequence[FormFieldGroup] | None = None,
    presentations: Mapping[str, FormFieldPresentation] | None = None,
) -> Node:
    """Render existing ``FormFields`` inside the optimistic live-save host."""
    if "__key__" not in patch_url_template:
        raise ValueError("patch_url_template must contain the literal __key__ token.")
    prepared = prepare_setting_fields(form, states, presentations, namespace=namespace)
    return _LiveSettingFields(
        patch_url_template=patch_url_template,
        csrf=csrf,
        namespace=namespace,
        class_="block w-full @container",
    )[
        SettingsFieldLayout(1)[
            FormFields(
                form,
                presentations=prepared,
                groups=groups,
            )
        ]
    ]
```

- [ ] **Step 5: Confirm the break is total and expected**

Run: `direnv exec . uv run python manage.py gen_element_types && direnv exec . uv run mypy common/components/settings_kit.py games/views/settings.py`
Expected: mypy errors on `games/views/settings.py`'s two `LiveSettingFields(...)` calls (missing required `namespace` argument) and on `e2e/test_settings_ui_kit_e2e.py`'s call — this is intentional; fixed in Tasks 8 and 9. Confirm no OTHER unexpected errors.

- [ ] **Step 6: Commit**

```bash
git add common/components/custom_elements.py common/components/settings_kit.py
git commit -m "feat(settings): thread namespace through SettingSourceBadge/LiveSettingFields

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

(This commit leaves the tree red at 3 call sites by design — Tasks 8/9 fix them, Task 11 is the real gate.)

---

### Task 5: `SettingSourceBadgeElement` filters on key + namespace

**Files:**
- Modify: `ts/elements/setting-source-badge.ts`
- Test: `ts/elements/setting-source-badge.test.ts`

**Interfaces:**
- Consumes: Task 3's `ResolvedSetting.namespace`; Task 4's `SettingSourceBadgeProps.namespace` (available via the regenerated `readSettingSourceBadgeProps`).
- Produces: the badge only updates when `resolved.key === this.settingKey && resolved.namespace === this.namespace`.

- [ ] **Step 1: Update `mountBadges()` and add a namespace-isolation test**

In `ts/elements/setting-source-badge.test.ts`, add `namespace="user"` to both `<setting-source-badge>` tags in `mountBadges()`:

```typescript
    <setting-source-badge key="THEME" namespace="user">
```
```typescript
    <setting-source-badge key="PAGE_SIZE" namespace="user">
```

Update the existing `"updates only the matching badge from a committed event"` test's `dispatchSettingCommitted` call to include `namespace: "user"`:

```typescript
    dispatchSettingCommitted({
      key: "THEME",
      value: "dark",
      source: "user",
      locked: false,
      namespace: "user",
    });
```

Add a new test:

```typescript
  it("ignores a same-key event from a different namespace", () => {
    document.body.innerHTML = `
    <setting-source-badge key="THEME" namespace="site">
      <pop-over>
        <button data-pop-over-trigger aria-label="Default source">
          <span data-setting-origin="default"
              class="bg-neutral-quaternary text-heading">
            <span data-setting-source-label>Default</span>
          </span>
        </button>
        <div data-pop-over-panel>
          <dl><div data-setting-source-description><dt>Source</dt>
            <dd>The built-in default.</dd></div>
            <div data-setting-source-status hidden><dt>Status</dt><dd>Status</dd></div>
          </dl>
        </div>
      </pop-over>
    </setting-source-badge>`;
    const badge = document.querySelector<HTMLElement>("setting-source-badge")!;

    dispatchSettingCommitted({
      key: "THEME",
      value: "dark",
      source: "user",
      locked: false,
      namespace: "user",
    });

    expect(badge.querySelector("[data-setting-source-label]")?.textContent).toBe(
      "Default",
    );
    expect(
      badge.querySelector<HTMLElement>("[data-setting-origin]")?.dataset.settingOrigin,
    ).toBe("default");
  });
```

- [ ] **Step 2: Run to verify failures**

Run: `direnv exec . pnpm test:ts -- setting-source-badge`
Expected: FAIL — the element doesn't yet read/compare `namespace`, so the new isolation test's badge would incorrectly update (the mismatch check doesn't exist yet); the updated existing test may still pass by coincidence but the new test must fail.

- [ ] **Step 3: Implement the element change**

In `ts/elements/setting-source-badge.ts`:

```typescript
class SettingSourceBadgeElement extends HTMLElement {
  private settingKey = "";
  private namespace = "";

  connectedCallback(): void {
    const props = readSettingSourceBadgeProps(this);
    this.settingKey = props.key;
    this.namespace = props.namespace;
    document.body.addEventListener(SETTING_COMMITTED_EVENT, this.onCommitted);
  }

  disconnectedCallback(): void {
    document.body.removeEventListener(SETTING_COMMITTED_EVENT, this.onCommitted);
  }

  private onCommitted = (event: Event): void => {
    if (!(event instanceof CustomEvent)) return;
    let resolved: ResolvedSetting;
    try {
      resolved = parseResolvedSetting(event.detail);
    } catch (error) {
      console.error("Ignoring malformed setting-committed event", error);
      return;
    }
    if (resolved.key !== this.settingKey || resolved.namespace !== this.namespace) {
      return;
    }
    this.update(resolved);
  };
```

(rest of the class unchanged.)

- [ ] **Step 4: Run to verify pass**

Run: `direnv exec . pnpm test:ts -- setting-source-badge`
Expected: PASS all tests in this file.

- [ ] **Step 5: Commit**

```bash
git add ts/elements/setting-source-badge.ts ts/elements/setting-source-badge.test.ts
git commit -m "feat(settings): SettingSourceBadge filters on key and namespace

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 6: `LiveSettingFieldsElement` self-checks namespace

**Files:**
- Modify: `ts/elements/live-setting-fields.ts`
- Test: `ts/elements/live-setting-fields.test.ts`

**Interfaces:**
- Consumes: Task 3's `ResolvedSetting.namespace`; Task 4's `LiveSettingFieldsProps.namespace`.
- Produces: the element throws (same as its existing key check) when the PATCH response's `namespace` doesn't match its own configured namespace.

- [ ] **Step 1: Update `mountFields()` and add every response fixture's `namespace`**

In `ts/elements/live-setting-fields.test.ts`, update the `<live-setting-fields>` and `<setting-source-badge>` tags in `mountFields()`:

```typescript
    <live-setting-fields patch-url-template="/api/settings/user/__key__"
        csrf="token" namespace="user">
```
```typescript
      <setting-source-badge key="DESTINATION" namespace="user"><pop-over>
```

Add `namespace: "user"` (or `"namespace": "user",` for the JSON-response-shaped literals) to every **valid** resolved-setting object in this file — the two deliberately-malformed fixtures (line ~157 `{ key: "NAME", value: "After" }` in `"rejects a malformed successful response..."`, and line ~368 `{ key: "DATETIME_FORMAT", value: "mdy_12h" }` in `"does not reload after a malformed date/time format response"`) stay as-is; they must remain invalid regardless of namespace.

Add the field to each of these (one `namespace: "user"` line added per object, immediately after `locked: false,` or, where there's no `locked` field, after `source: "user"`/`source: "database"`/`source: "default"`):

- The `resolved` object in `"PATCHes the changed key and dispatches the complete committed response"` (~line 109-114).
- All three `.mockResolvedValueOnce({...})` bodies in `"updates source metadata from each resolved PATCH response"` (~lines 179-184, 189-194, 199-204).
- `"reconciles normalized text values..."` (~lines 257-262).
- `"shows the effective fallback after clearing a text override"` (~lines 278-283).
- `"keeps a cleared select on its use-default sentinel"` (~lines 299-304).
- `"reloads after a successful presentation setting save"` (~lines 320-325).
- `"reloads after a successful date/time format save"` (~lines 342-347).
- `"preserves newer typing when an older successful response resolves"` (~lines 400-405).
- `"serializes rapid writes..."`, both `first.resolve(...)` and `second.resolve(...)` bodies (~lines 455-459, 471-476).
- `"does not let a superseded failure revert the newer queued edit"`, the `second.resolve(...)` body (~lines 508-513).
- `"sends native boolean, null, and numeric JSON values"` — the dynamic response builder `{ key, value, source: "user", locked: false }` (~line 551) gains `namespace: "user"`.

- [ ] **Step 2: Add the failing test**

```typescript
  it("throws when the response namespace does not match its own", async () => {
    window.fetchWithHtmxTriggers = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        key: "NAME",
        value: "After",
        source: "user",
        locked: false,
        namespace: "site",
      }),
    } as Response);
    vi.spyOn(console, "error").mockImplementation(() => {});
    const host = mountFields();
    const input = host.querySelector<HTMLInputElement>('[name="name"]')!;
    input.value = "After";

    change(input);

    await vi.waitFor(() => expect(input.value).toBe("Before"));
    expect(window.toast).toHaveBeenCalledWith(
      "Couldn't save your change — please try again.",
      "error",
    );
  });
```

- [ ] **Step 3: Run to verify it fails**

Run: `direnv exec . pnpm test:ts -- live-setting-fields`
Expected: without the check, this response would be treated as valid and committed — the new test's rollback assertion fails.

- [ ] **Step 4: Implement**

In `ts/elements/live-setting-fields.ts`, add a `namespace` field to the class and read it in `connectedCallback`:

```typescript
class LiveSettingFieldsElement extends HTMLElement {
  private patchUrlTemplate = "";
  private csrf = "";
  private namespace = "";
  private committed = new Map<SettingControl, ControlSnapshot>();
  private pending = new Map<SettingControl, PendingSave>();

  connectedCallback(): void {
    const props = readLiveSettingFieldsProps(this);
    this.patchUrlTemplate = props.patchUrlTemplate;
    this.csrf = props.csrf;
    this.namespace = props.namespace;
```

In `performSave`, extend the existing key check:

```typescript
      const resolved = parseResolvedSetting(await response.json());
      if (resolved.key !== key) throw new Error(`PATCH ${url} returned ${resolved.key}`);
      if (resolved.namespace !== this.namespace) {
        throw new Error(`PATCH ${url} returned namespace ${resolved.namespace}`);
      }
```

- [ ] **Step 5: Run to verify pass**

Run: `direnv exec . pnpm test:ts -- live-setting-fields`
Expected: PASS all tests in this file.

- [ ] **Step 6: Commit**

```bash
git add ts/elements/live-setting-fields.ts ts/elements/live-setting-fields.test.ts
git commit -m "feat(settings): LiveSettingFields self-checks its response namespace

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 7: `ThemeCoordinator` asserts `namespace === "user"`

**Files:**
- Modify: `ts/theme-coordinator.ts`
- Test: `ts/theme-coordinator.test.ts`

**Interfaces:**
- Consumes: Task 3's `ResolvedSetting.namespace`.
- Produces: the coordinator's existing PATCH-response contract check gains one more condition; a namespace mismatch is treated identically to today's other contract violations (rollback, toast, no commit).

- [ ] **Step 1: Add `namespace: "user"` to every response fixture**

In `ts/theme-coordinator.test.ts`, add `namespace: "user"` to each of these object literals (the `{ key: "THEME" }` "malformed response" fixture at line ~201 stays as-is — it's deliberately incomplete):

- `~line 153`: `{ key: "THEME", value: "light", source: "user", locked: false }`.
- `~line 180-183`: `{ key: "THEME", value: "dark", source: "database", locked: false }`.
- `~line 203`: `{ key: "THEME", value: "dark", source: "user", locked: false }` (the "contract mismatch" case — keep it hitting its intended value-mismatch check, not an incidental missing-namespace failure).
- `~line 224`: `{ key: "THEME", value: "light", source: "user", locked: false }`.
- `~line 243`: `{ key: "THEME", value: "light", source: "user", locked: false }`.

- [ ] **Step 2: Add a namespace-mismatch test**

```typescript
  it("rolls back when the response namespace is not user", async () => {
    configureAccount();
    vi.mocked(window.fetchWithHtmxTriggers).mockResolvedValueOnce(response({
      key: "THEME", value: "light", source: "user", locked: false, namespace: "site",
    }));
    vi.spyOn(console, "error").mockImplementation(() => {});
    const coordinator = new ThemeCoordinator();

    expect(await coordinator.requestPreferenceChange("light")).toBe("rolled-back");
    expect(window.toast).toHaveBeenCalledWith(
      "Couldn't save your theme — please try again.",
      "error",
    );
    coordinator.destroy();
  });
```

- [ ] **Step 3: Run to verify it fails**

Run: `direnv exec . pnpm test:ts -- theme-coordinator`
Expected: without the check, `namespace: "site"` is accepted and the change commits instead of rolling back.

- [ ] **Step 4: Implement**

In `ts/theme-coordinator.ts`, extend the existing contract-check condition in `requestPreferenceChange` (the block starting `if (resolved.key !== "THEME" || ...)`):

```typescript
      if (
        resolved.key !== "THEME" ||
        resolved.namespace !== "user" ||
        !isThemePreference(resolved.value) ||
        resolved.locked ||
        (desired === null && resolved.source === "user") ||
        (desired !== null && (
          resolved.source !== "user" || resolved.value !== desired
        ))
      ) {
        throw new Error("Theme PATCH response violated its contract");
      }
```

- [ ] **Step 5: Run to verify pass**

Run: `direnv exec . pnpm test:ts -- theme-coordinator`
Expected: PASS all tests in this file.

- [ ] **Step 6: Commit**

```bash
git add ts/theme-coordinator.ts ts/theme-coordinator.test.ts
git commit -m "feat(settings): ThemeCoordinator asserts its PATCH response namespace

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 8: Wire the two real settings pages

**Files:**
- Modify: `games/views/settings.py`

**Interfaces:**
- Consumes: Task 1's `SettingNamespace`; Task 4's `LiveSettingFields(..., namespace=...)`.

- [ ] **Step 1: Add the import**

Add to the existing imports in `games/views/settings.py`:

```python
from timetracker.settings_commands import SettingNamespace
```

- [ ] **Step 2: Pass `namespace` in `user_settings()`**

Find the `LiveSettingFields(form, states=states, patch_url_template=patch_url, csrf=get_token(request), presentations={...})` call inside `user_settings()` and add `namespace=SettingNamespace.USER`:

```python
            LiveSettingFields(
                form,
                states=states,
                patch_url_template=patch_url,
                csrf=get_token(request),
                namespace=SettingNamespace.USER,
                presentations={
                    "theme": FormFieldPresentation(decorate_control=ThemeSetting)
                },
            ),
```

- [ ] **Step 3: Pass `namespace` in `admin_settings()`**

Find the `LiveSettingFields(form, states=states, patch_url_template=patch_url, csrf=get_token(request))` call inside `admin_settings()` and add `namespace=SettingNamespace.SITE`:

```python
            LiveSettingFields(
                form,
                states=states,
                patch_url_template=patch_url,
                csrf=get_token(request),
                namespace=SettingNamespace.SITE,
            ),
```

- [ ] **Step 4: Verify**

Run: `direnv exec . uv run mypy games/views/settings.py`
Expected: no errors related to `LiveSettingFields` call sites (other pre-existing errors elsewhere, if any, are unrelated — do not fix them here).

Run: `direnv exec . uv run pytest tests/test_settings_page.py tests/test_admin_settings_page.py -v`
Expected: PASS (page rendering tests, no behavior change to assert on `namespace` yet — that's Task 10's e2e work).

- [ ] **Step 5: Commit**

```bash
git add games/views/settings.py
git commit -m "feat(settings): wire namespace into the user and admin settings pages

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 9: Fix the synthetic e2e harness's third `LiveSettingFields` call site

**Files:**
- Modify: `e2e/test_settings_ui_kit_e2e.py`

**Interfaces:**
- Consumes: Task 1's `SettingNamespace`; Task 4's `LiveSettingFields(..., namespace=...)`.

This file's `settings_kit_view` is a **third** real call site of `LiveSettingFields` (a synthetic isolated-URLconf test harness, unrelated to the real user/site pages) — easy to miss since it's in `e2e/`, not `games/`.

- [ ] **Step 1: Add the import**

```python
from timetracker.settings_commands import SettingNamespace
```

- [ ] **Step 2: Pass `namespace` in the harness's `LiveSettingFields(...)` call**

```python
    fields = LiveSettingFields(
        form,
        states=states,
        patch_url_template="/settings-kit-patch/__key__/",
        csrf=get_token(request),
        namespace=SettingNamespace.USER,
        groups=groups,
    )
```

- [ ] **Step 3: Update the harness's fake PATCH endpoint to include `namespace`**

```python
    return JsonResponse(
        {
            "key": key,
            "value": payload.get("value"),
            "source": "user",
            "locked": False,
            "namespace": "user",
        }
    )
```

- [ ] **Step 4: Verify**

Run: `direnv exec . uv run mypy e2e/test_settings_ui_kit_e2e.py`
Expected: no errors on the `LiveSettingFields` call.

- [ ] **Step 5: Commit**

```bash
git add e2e/test_settings_ui_kit_e2e.py
git commit -m "fix(e2e): wire namespace into the settings-kit synthetic harness

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 10: E2E — response-shape fixes + bidirectional cross-namespace coverage

**Files:**
- Modify: `e2e/test_admin_settings_page_e2e.py`
- Modify: `e2e/test_settings_page_e2e.py` (add the new user-page test)

**Interfaces:**
- Consumes: everything from Tasks 1-9 running end to end against real pages.

- [ ] **Step 1: Fix the two exact-dict PATCH assertions in `test_admin_settings_page_e2e.py`**

Line ~135-140:

```python
    assert saved.value.json() == {
        "key": "DEFAULT_CURRENCY",
        "value": "EUR",
        "source": "database",
        "locked": False,
        "namespace": "site",
    }
```

Line ~165-170:

```python
    assert cleared.value.json() == {
        "key": "DEFAULT_CURRENCY",
        "value": "CZK",
        "source": "default",
        "locked": False,
        "namespace": "site",
    }
```

- [ ] **Step 2: Run the existing admin settings e2e suite to confirm the fix**

Run: `direnv exec . uv run pytest e2e/test_admin_settings_page_e2e.py -v`
Expected: PASS.

- [ ] **Step 3: Add the cross-namespace test to the admin (site) page**

Append to `e2e/test_admin_settings_page_e2e.py`:

```python
def test_site_page_ignores_a_synthetic_user_namespace_event(
    live_server,
    superuser_page: Page,
):
    """A same-key event from the OTHER namespace must not update this page's
    badge — issue #488's core acceptance criterion, exercised in the
    direction real traffic can't reach today (no page hosts both
    namespaces), so the cross-namespace event is injected synthetically."""
    page = superuser_page
    page.goto(f"{live_server.url}{reverse('games:admin_settings')}")
    _wait_for_live_settings(page)

    badge = _source_badge(page, "DEFAULT_CURRENCY")
    expect(badge).to_have_attribute("data-setting-origin", "database")

    page.evaluate(
        """() => {
            document.body.dispatchEvent(new CustomEvent("setting-committed", {
                detail: {
                    key: "DEFAULT_CURRENCY",
                    value: "USD",
                    source: "user",
                    locked: false,
                    namespace: "user",
                },
                bubbles: true,
            }));
        }"""
    )

    expect(badge).to_have_attribute("data-setting-origin", "database")
```

- [ ] **Step 4: Add the mirror test to the user settings page**

`e2e/test_settings_page_e2e.py` already has the `authenticated_page` fixture (returns `(page, preferred_device)`, logs in user `tester`) and the `_wait_for_live_settings(page)` helper. The page's URL name is `games:settings` (registered as `path("settings", settings_views.user_settings, name="settings")` in `games/urls.py`) — **not** `games:user_settings`. Append:

```python
def test_user_page_ignores_a_synthetic_site_namespace_event(
    live_server,
    authenticated_page,
):
    """Mirror of test_site_page_ignores_a_synthetic_user_namespace_event, in
    the other direction: a synthetic site-namespace THEME event must not
    affect the user page's theme state."""
    page, _preferred = authenticated_page
    page.goto(f"{live_server.url}{reverse('games:settings')}")
    _wait_for_live_settings(page)

    before = page.evaluate("document.documentElement.dataset.themePreference")

    page.evaluate(
        """() => {
            document.body.dispatchEvent(new CustomEvent("setting-committed", {
                detail: {
                    key: "THEME",
                    value: "dark",
                    source: "database",
                    locked: false,
                    namespace: "site",
                },
                bubbles: true,
            }));
        }"""
    )

    after = page.evaluate("document.documentElement.dataset.themePreference")
    assert after == before
```

- [ ] **Step 5: Run both new tests + the full settings/theme e2e sweep**

Run: `direnv exec . uv run pytest e2e/test_admin_settings_page_e2e.py e2e/test_settings_page_e2e.py e2e/test_settings_ui_kit_e2e.py e2e/test_theme_e2e.py -v`
Expected: PASS all.

- [ ] **Step 6: Commit**

```bash
git add e2e/test_admin_settings_page_e2e.py e2e/test_settings_page_e2e.py
git commit -m "test(e2e): fix namespace in PATCH assertions; bidirectional cross-namespace coverage

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 11: Full verification gate

**Files:** none (verification only)

- [ ] **Step 1: Regenerate and run the full gate**

Run: `direnv exec . uv run python manage.py gen_element_types && direnv exec . make check`
Expected: green — lint, format-check, mypy, ts-check, vitest, and the entire pytest suite **including `e2e/`**.

- [ ] **Step 2: If anything is red, fix it in place**

Likely candidates if something slipped through: a fourth call site of `LiveSettingFields`/`SettingSourceBadge` not covered above (grep to confirm none remain: `direnv exec . rg -n "LiveSettingFields\(" --type py` and `direnv exec . rg -n "SettingSourceBadge\(" --type py` — every hit must now pass `namespace=`), or a vitest fixture missed in Tasks 5-7 (re-check the enumerated line lists against the current file state).

- [ ] **Step 3: Commit any fixes**

```bash
git add -A
git commit -m "fix(settings): address make check failures after namespace rollout

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

(Skip this commit if Step 1 was already green.)

---

## Follow-up issues to file

None new — the design already fans out to **#497** (migrate `SettingSource`/`SOURCE_METADATA` to the same codegen mechanism this issue introduces for `SettingNamespace`), filed during design.

## Self-review notes

- **Spec coverage:** namespace type + codegen (T1), server stamping on all 4 endpoints (T2), event contract + doc-comment (T3), Python prop threading (T4), badge listener (T5), emitter self-check (T6), coordinator self-check (T7), both real pages wired (T8), the synthetic harness's third call site (T9) — easy to have missed, explicitly caught during exploration — response-shape fixes + bidirectional cross-namespace e2e (T10), full gate (T11). All mapped.
- **Types:** `SettingNamespace`, `SETTING_NAMESPACE_CHOICES`, `SETTING_NAMESPACES`, generated module path (`ts/generated/settings-vocabulary.ts`) used consistently across tasks.
- **Exhaustive fixture edits:** Tasks 6 and 7 enumerate every existing test object literal needing `namespace` added, and explicitly call out which deliberately-malformed fixtures must NOT gain it (so they keep testing what they claim to test).
