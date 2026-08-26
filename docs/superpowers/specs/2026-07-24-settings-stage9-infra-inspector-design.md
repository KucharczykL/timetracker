# Settings epic — Stage 9: infrastructure config inspector

Design doc for issue #391 (part of the Settings panel epic, #381).

## Goal

A read-only inspector on `/admin-settings` so superusers can see the resolved
value and origin of every infrastructure/security setting without shell access.
No edit path.

**Depends on:** Stage 1 (resolver/registry), Stage 3 (settings kit), Stage 8
(`/admin-settings` view). All three are merged; verified present in the worktree.

## Scope

The 8 `SettingScope.INFRA` settings in `SETTINGS_REGISTRY`
(`timetracker/settings_registry.py`), rendered read-only in a new section on the
existing `admin_settings` page:

`TZ`, `DEBUG`, `SECRET_KEY`, `APP_URL`, `DEV_LOGIN_PREFILL`, `ALLOWED_HOSTS`,
`DATA_DIR`, `HASHED_STATIC` — in registry order.

## Reuse (enhance, don't duplicate)

- `resolve_with_origin(key) -> ResolvedSetting(value, source, locked)`
  (`timetracker/settings_resolver.py`) — lazy/runtime; called inside the view,
  no import-time DB access.
- `SettingSourceBadge(source, *, locked, reason, setting_key, namespace)`
  (`common/components/settings_kit.py`) — standalone source/locked badge with
  tooltip; already handles warning tone + lock icon for locked sources and
  neutral tone for `default`.
- `SettingsSection` / `SettingsScaffold` — the page section scaffold; add one
  section.
- `SETTINGS_REGISTRY` + `SettingScope.INFRA` — the setting list is the registry,
  filtered by scope. `definition.env_name or definition.key` is the shown name;
  `definition.help_text`, `definition.note`, `definition.secret` drive the row.
- **The `FormFields` row *shell*** (`_form_field_row` in
  `common/components/primitives.py`) — the label-line + control + metadata layout
  and its type-scale classes (`text-type-label text-heading` label,
  `text-type-micro text-body` metadata). The read-only row reuses this
  *presentation* so infra rows sit in the same visual family as the editable
  site-default rows on the same page (the "middle path" decision).

### What is deliberately NOT reused, and why

The editable **data path** — a Django form routed through
`prepare_setting_fields` / `LiveSettingFields` — is **not** reused, even though it
already renders disabled+badged rows for env-locked site settings. Routing infra
through it hits three walls (evaluated against the real code):

1. **Secret leak (hard blocker).** `_form_field_row` renders each field via
   `str(field)`; a Django field with `disabled=True` still renders its `initial`
   into the widget's `value=` attribute (disabled blocks editing, not rendering).
   So a form-borne `SECRET_KEY` ships the real key in the HTML. Django has no
   "disabled but value-hidden" mode, so the secret must be handled outside the
   form regardless.
2. **`disabled` ≠ `locked`.** `prepare_setting_fields` disables a field *only*
   when `state.locked`, and drives the badge's warning tone + "env takes
   priority" reason off `locked`. But `locked` means "shadowed by a
   higher-priority source," not "read-only." Default-source infra values
   (`locked=False`, e.g. `HASHED_STATIC`) must still be non-editable; forcing
   `locked=True` would mislabel their source. Honestly supporting this needs a
   new `read_only` concept in the shared `SettingFieldState`/`prepare_setting_fields` — surgery on the shared kit that the editable pages don't need.
3. **No good field for non-strings.** `ALLOWED_HOSTS` (list) / `DATA_DIR` (Path)
   would be stringified into a `CharField.initial` — a disabled textbox wrapping
   the same string a static slot would show, buying nothing. `DEBUG`/`HASHED_STATIC`
   (bool) → disabled checkbox, a worse read than literal `True`/`False`.

So form-reuse cleanly covers only the ~3 plain-string keys; the secret, the
list/path/bool, and the default-source-disabled each need special-casing plus a
kit change. The middle path reuses the row **shell** (walls 2–3 dissolve: no form
fields, no `locked` coupling, any value stringifies) and keeps the secret out of
any form (wall 1).

`MaskedSecretField` (existing kit component) is **not** reused either: the uniform
read-only row supersedes it for this page (see "Secret" below). It is left
untouched — still used by the kit preview — so no churn.

## Net-new component — `ReadonlySettingField`

New in `common/components/settings_kit.py`, exported from `__all__`. A read-only
settings row that renders through the shared `FormFields` **row shell**, so it
looks like the editable site-default rows but has no Django form, no `<input>`,
and no live-save attributes.

**Shell reuse:** factor the presentational skeleton of `_form_field_row`
(label-line with an optional `label_extra` slot for the badge → control slot →
metadata block) into a small shared row helper that both `_form_field_row` and
`ReadonlySettingField` build on, *if* that extraction stays clean against the
existing checkbox-row/error branches; otherwise `ReadonlySettingField` matches
the same class strings directly. The implementation plan picks the exact
factoring. Either way the row's label/metadata typographic scale is the shared
one, not a re-invented set.

```python
def ReadonlySettingField(
    *,
    name: str,               # env var name (definition.env_name or definition.key), shown mono
    value: str,              # str(resolved.value); caller stringifies. Ignored when secret.
    source: str,             # str(resolved.source)
    namespace: str,          # SettingNamespace.SITE
    setting_key: str,        # definition.key — badge/registry identity
    locked: bool = False,
    reason: str = "",
    help_text: str = "",
    note: str = "",
    secret_present: bool | None = None,   # not None ⇒ secret; value slot masked, `value` ignored
) -> Node
```

Row anatomy (stacked in form rhythm — no per-row card dividers, matching the
editable section):

- **Identifier line (the shell's label slot):** `name` in **monospace** as the
  primary identifier, with `SettingSourceBadge(...)` in the `label_extra` slot
  beside it. No human label is rendered; the human-readable description lives in
  the metadata beneath.
- **Value line — plain static monospace text** (the shell's control slot; a
  static node, never an `<input>` or a disabled-input box):
  - `secret_present is None` → raw repr: `str(value)` verbatim, with **no**
    interpretive substitution (`False`, `True`,
    `['tracker.example.com', 'localhost']`, `/data`, a URL). An empty string
    renders as a genuinely blank value line — faithful to the stored value.
    A placeholder like `(empty)` is deliberately avoided: `""`, `[]`, and `None`
    are distinct states, and only raw `str(value)` shows which one it is without
    the inspector guessing.
  - `secret_present` set → a fixed mask `••••••••` when `True`, blank when
    `False` (dots vs blank convey set-vs-unset without an invented label). The
    real secret is never a parameter, so it cannot reach the DOM — leak-proof by
    construction (mirrors `MaskedSecretField`'s API discipline).
- **Metadata:** `help_text` then `note`, each as muted micro-text, reusing the
  kit's existing metadata text styling. Rows whose definition has neither (e.g.
  `DEBUG`, `APP_URL`, `DATA_DIR`, `HASHED_STATIC`) show just name + value, which
  is self-explanatory. (Optional, out of scope: enrich those defs' `help_text`.)

### Decisions (from the design interview + visual mockup review)

1. **First-class kit component that reuses the `FormFields` row shell**
   (the "middle path") — not a literal disabled-form reuse (three walls above),
   not a from-scratch layout, not inline view markup. Same row shell as the
   editable rows; static value slot instead of an input.
2. **Value = raw `str(value)`** (no per-type humanizing, no empty placeholder);
   empty renders blank, so `""` / `[]` / `None` stay distinguishable.
3. **Secret** uses the same uniform row with a masked value slot; it still shows
   a source badge (acceptance requires source on every infra setting).
4. **Show both `help_text` and `note`** as muted metadata.
5. **Identifier = raw env var name only, in monospace**, in the shell's label
   slot — no human-label subtitle; descriptions live in the metadata beneath.
6. **Empty non-secret value → blank** (raw `str(value)`), no placeholder.
7. **Value slot = plain static monospace text**, not a disabled-input box.

## View wiring — `admin_settings`

In `games/views/settings.py`, add a helper and a second `SettingsSection` after
the existing "Site defaults" section:

```python
def _infra_fields() -> list[Node]:
    rows: list[Node] = []
    for definition in SETTINGS_REGISTRY.values():  # registry order
        if definition.scope is not SettingScope.INFRA:
            continue
        resolved = resolve_with_origin(definition.key)
        rows.append(
            ReadonlySettingField(
                name=definition.env_name or definition.key,
                value="" if definition.secret else str(resolved.value),
                source=str(resolved.source),
                namespace=SettingNamespace.SITE,
                setting_key=definition.key,
                locked=resolved.locked,
                help_text=definition.help_text,
                note=definition.note,
                secret_present=bool(resolved.value) if definition.secret else None,
            )
        )
    return rows
```

Section (appended to the existing `sections` list in `admin_settings`):

```python
SettingsSection(
    "infrastructure",
    "Infrastructure",
    SettingsFieldLayout(1)[*_infra_fields()],
    "Deployment and security configuration, resolved read-only. "
    "Change via env / settings.ini and restart.",
)
```

The section joins the scaffold nav automatically (same-DOM rail + mobile sheet).

## Correctness / security

- For `secret=True` definitions the view passes `value=""` and only
  `bool(resolved.value)` for `secret_present`; `str(resolved.value)` for the
  secret is never evaluated. The secret never enters the node tree, the served
  HTML, or any API.
- `locked` / `source` come straight from the resolver, so env/file/dotenv/ini
  values render the warning-tone locked badge with reason; `default` renders
  neutral. No new source logic.
- No import-time DB access: resolution happens inside the request.

## Tests

Python + minimal e2e.

- **Component** (`tests/test_settings_kit.py` or nearest kit test module):
  `ReadonlySettingField` renders the name, value, and badge; `secret_present=True`
  emits the mask and the output contains no caller-supplied secret text;
  per-type value strings render as raw repr; empty non-secret renders blank (no
  placeholder); `help_text` and `note` appear; `locked=True` passes through to
  the badge.
- **View** (`tests/test_admin_settings_page.py`): a superuser GET renders the
  Infrastructure section with all 8 keys, each with a source; a known planted
  `SECRET_KEY` value is **absent** from the response body; a non-superuser still
  gets 403.
- **e2e** (`e2e/test_settings_page_e2e.py`): a superuser sees the Infrastructure
  section at mobile (390×844) and desktop (1280×900). Read-only, no interaction.
  (Note: the settings e2e area has a known rare full-suite flake, issue #476;
  investigated and deferred — root cause is shared in-memory SQLite cross-thread
  contention, unrelated to this read-only page.)

## Cross-cutting

- `docs/configuration.md` + `CHANGELOG.md`: note the read-only infra inspector.
- Gate on the full `direnv exec . make check` (incl. `e2e/`) in the Nix shell.

## Divergences from issue #391 (recorded deliberately)

- The issue says "SECRET_KEY rendered through the **masked-secret field**." This
  design instead merges masking into the uniform `ReadonlySettingField` (masked
  value slot, `secret_present: bool`) so the secret row matches every other row
  and still carries a source badge. `MaskedSecretField` stays for the kit
  preview. Same leak-proof guarantee, better layout consistency.
- Values render as raw repr and the identifier is the env var name (not the
  human label) — chosen for an admin-facing inspector where the machine name is
  the actionable identity.
