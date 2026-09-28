# Platform icons name their glyphs — implementation plan

**Goal:** a platform's `icon` names a snippet drawing a distinct glyph;
nothing derives it from the name.

**Spec:** [docs/superpowers/specs/2026-09-28-issue-1321-platform-icon-glyphs-design.md](../specs/2026-09-28-issue-1321-platform-icon-glyphs-design.md)

**Branch:** `claude/issue-1321-icon-glyphs`, cut from `origin/main`
at `5f04542f`. Rebase onto `origin/main` before Task 1.

## Global constraints

- Drive everything through `make`; wrap every pytest target in
  `flock "$(git rev-parse --git-common-dir)/heavy-tests.lock"`.
- Iterate with `make test-fast ARGS="<path> -x"`; the gate is one full
  `make check` at the end.
- Run `make format`, `make lint-fix`, `make vale` before each commit.
- Complete-word identifiers; name compound types; comments ≤ 7 words.
- Never edit `common/components/icons_generated.py` by hand.
- Aliases, verbatim: `nintendo-3ds`→`nintendo`,
  `physical-media`→`physical`, `ps1`→`playstation`. Fallback
  `unspecified`.

---

### Task 1: The vocabulary

**Files:** `common/platform_icons.py`,
`tests/test_icon_picker.py`.

**Produces:**
- `RETIRED_ICONS: Mapping[PlatformIcon, PlatformIcon]`
  (`MappingProxyType`), the three aliases.
- `UNSPECIFIED_ICON: PlatformIcon = "unspecified"`.
- `canonical_icon(slug: str) -> PlatformIcon`: in `PLATFORM_ICONS` →
  itself; in `RETIRED_ICONS` → its glyph; else `UNSPECIFIED_ICON`.

**Tests (write first):**
- `canonical_icon("steam") == "steam"`.
- each alias gives its glyph (parametrize over the three).
- `""`, `"playstation-5"`, `"pc"` give `"unspecified"`.
- every `RETIRED_ICONS` value is in `PLATFORM_ICONS`, no key is.

Commit: `feat: platform icons name retired aliases (#1321)`.

### Task 2: The snippets

**Files:** delete `games/templates/icons/{nintendo-3ds,physical-media,ps1}.html`;
regenerate `common/components/icons_generated.py` with `make gen-icons`;
`tests/test_icon_picker.py`.

**Tests:**
- Replace `test_no_two_picker_icons_draw_one_glyph` with
  `test_no_two_snippets_draw_one_glyph`: read every
  `games/templates/icons/*.html`, strip `<title>…</title>` and all
  whitespace, assert the set has one member per file. (Checked: the
  three aliases are the only duplicates today, interface icons
  included.)
- `test_the_platform_form_starts_on_the_current_icon` uses
  `icon="physical"` already; leave it.

Gotcha: `test_every_platform_icon_is_a_named_snippet` must stay green;
no `PLATFORM_ICONS` key is removed.

Commit: `fix: retire the three alias icon snippets (#1321)`.

### Task 3: The model, the form, and the test sweep

One task, because `clean()` refusing an unknown slug turns ~100 test
platforms red at once.

**Files:**
- `games/models.py` (`Platform`, around line 471 and 508):
  `icon = models.SlugField(default=UNSPECIFIED_ICON)` (not blank);
  `save()` drops the `slugify` branch (keep the `slugify` import if
  `Game` still uses it, line 417); `clean()` raises
  `ValidationError({"icon": …})` when `self.icon not in PLATFORM_ICONS`.
  Sentence: `"Pick one of the listed icons."`.
- `games/forms.py` `PlatformForm` (around line 2111): choices are
  `PLATFORM_ICONS.items()`, initial `self.instance.icon or
  UNSPECIFIED_ICON`; delete the "older slug stays pickable" branch; add
  `clean_icon()` returning the value or `UNSPECIFIED_ICON`, so `""` and
  an omitted key both state Unspecified. Field stays `required=False`.
- `games/management/commands/loadplatforms.py`: help text stops
  saying a blank icon is slugified.
- `games/fixtures/platforms.yaml`: add `icon:` to each of the seven
  rows — Steam `steam`, Xbox Gamepass `xbox-gamepass`, Epic Games
  Store `egs`, Playstation 5 `ps5`, Playstation 4 `ps4`, Nintendo
  Switch `nintendo-switch`, Nintendo 3DS `nintendo`.
- Migration file is Task 4; generate nothing here. `make check` runs a
  migration drift check, so Task 3 and 4 land before any full run.

**Test sweep** (`grep -rnE 'icon="[^"]*"' tests e2e`, 53 files):
- A slug in `PLATFORM_ICONS` stays.
- A test that reads the icon (filters on `PlatformFilter.icon`,
  rendering assertions, `test_loadplatforms`) takes a real slug, the
  same one wherever the test compares values; `"pc"` → `"steam"`,
  a second distinct value → `"gog"`.
- Every other invented slug (`"test"`, `"system"`, `"dark"`,
  `"light"`, `"p"`, `"switch"`, `"*test"`, `"retro"`, `"edit"`,
  `"delete"`) is dropped from the call.
- `tests/test_library_form_isolation.py:113,176` and
  `tests/test_reference_form.py:133` post `"icon": ""`: keep, they now
  prove the empty value states Unspecified.
- `tests/test_loadplatforms.py:23-41`: expect `egs` from the fixture,
  and replace `icon="custom-icon"` with a real slug.
- Delete `test_an_older_slug_stays_pickable`.

**New tests** (`tests/test_platform_icon.py`):
- a platform created with no icon holds `"unspecified"`;
  `Platform(name="Playstation 5")` saved holds `"unspecified"`.
- `Platform.objects.create(icon="pc")` raises `ValidationError` whose
  `message_dict` has `"icon"`.
- `PlatformForm({"name": "Amiga", "group": ""})` and with `"icon": ""`
  both save `"unspecified"`.
- `PlatformForm` with `"icon": "pc"` is invalid on `icon`.
- `POST /api/platforms/` with a name alone answers 201 and the row
  holds `"unspecified"` (pattern: `tests/test_row_creation_api.py`).
- `make loadplatforms` equivalent: `call_command("loadplatforms")`
  leaves only slugs in `PLATFORM_ICONS`.

Commit: `feat: a platform states its icon; nothing derives it (#1321)`.

### Task 4: The migration

**Files:** `games/migrations/0018_platform_icon_glyphs.py` (latest is
`0017_batch_change`), `tests/test_platform_icon_migration.py`.

**Shape:**
- `AlterField` for `icon` (`SlugField(default="unspecified")`) —
  generate with `make makemigrations ARGS="games --name platform_icon_glyphs"`,
  then add the data step by hand.
- Module-level literals `KNOWN_ICONS` (the 19 slugs) and
  `RETIRED_ICONS` (the three aliases); a module-level function
  `_canonical(slug)` over them. Import no application module.
- `name_glyphs(apps, schema_editor)`: for `Platform` rows whose icon
  is not in `KNOWN_ICONS`, `update(icon=_canonical(icon))` grouped by
  current value; for `BatchChange` rows with
  `model_label="games.platform", field="icon"`, rewrite `earlier` and
  `stated` where each is a string outside `KNOWN_ICONS`.
- `RunPython(name_glyphs, RunPython.noop)`.

**Tests** (call `name_glyphs(django.apps.apps, None)` from the module,
loaded with `importlib.import_module`; seed values through
`.update()` so `clean()` does not refuse them):
- `nintendo-3ds` → `nintendo`, `physical-media` → `physical`,
  `ps1` → `playstation`.
- `""` and `"playstation-5"` → `"unspecified"`.
- `"steam"` untouched.
- a `BatchChange` with `earlier="ps1"`, `stated="steam"` → `earlier`
  `"playstation"`, `stated` untouched; a `BatchChange` on `group` is
  untouched.
- every slug the migration writes is a key of `PLATFORM_ICONS` (its
  `KNOWN_ICONS` and `RETIRED_ICONS` values ⊆ the live set). A subset,
  not equality, so #1325 adding icons keeps it green.

Rehearse: `make verify-dump` on the newest dump; expect 8 platform
rows rewritten. Record the count in the PR body.

Commit: `feat: stored platform icons name their glyphs (#1321)`.

### Task 5: The sample loader

**Files:** `games/management/commands/load_sample_data.py` (around
line 460), a test in `tests/test_anonymize_sample.py`, whose round trip runs the loader.

- `icon=canonical_icon(fields.get("icon", ""))`.
- Test: after `load_sample_data`, every `Platform.icon` is in
  `PLATFORM_ICONS`, and at least one row holds `"nintendo"` (the
  fixture's `nintendo-3ds`).

Gotcha: a `clean()` refusal inside `_load_platforms` reports "no
reusable exact identity"; `canonical_icon` keeps it from firing.

Commit: `fix: the sample loader states canonical icons (#1321)`.

### Task 6: Docs and gate

- `CLAUDE.md`, Conventions → **Platform icons**: a snippet is named for
  its glyph; a new one goes in `PLATFORM_ICONS` too; `Platform.icon`
  holds a `PLATFORM_ICONS` slug, `unspecified` by default, refused
  otherwise by `clean()`; `RETIRED_ICONS` and `canonical_icon` map old
  slugs. Models → **Platform** line: "icon (slug, auto-generated from
  name)" becomes "icon (a `PLATFORM_ICONS` slug)".
- `make format && make lint-fix && make vale`.
- Full gate once: `flock … make check`, exit code read from the log.

Commit: `docs: platform icons name their glyphs (#1321)`.

## Follow-up issues (filed)

- #1325 — glyphs for consoles the picker lacks.
- #1326 — an icon a person uploads.
