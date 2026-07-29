# Duration display format preference (#486) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One per-user preference selects how every human-visible duration renders, with a popover offering the same value under the other profiles.

**Architecture:** A request-scoped `DurationPresentation`, mirroring `DateTimePresentation`, resolves the user's profile and formats values. A `Duration()` component wraps the rendering in a popover listing deduplicated alternates. Formatting leaves the model layer entirely, because a model method has no request and cannot resolve a per-user preference.

**Tech Stack:** Django 6, the settings registry/resolver, `common.components` node tree, pytest + pytest-django, Playwright e2e.

**Depends on #583.** That PR removes the app's only client-rendered duration; without it this work also needs a TypeScript formatter and a cross-language parity contract.

**Design:** `docs/superpowers/specs/2026-07-29-issue-486-duration-format-design.md`. The rendering-rules table there is the source of truth for every expected value below.

## Global Constraints

- Python 3.14 only. Drive everything through `make`. Iterate on `make check-fast`; gate on the full `make check`.
- Never run `make test-e2e` while `make dev` is up.
- Never write to `GeneratedField`s: `duration_calculated`, `duration_total`, `price_per_game`, `days_to_finish`.
- New settings go through `config()` / the registry, never bare `os.environ`.
- Build UI with `common.components` builders in htpy form. JS-bearing components declare their own `Media`; views never thread `scripts=` for them.
- Name compound types explicitly (`TypedDict`, `NamedTuple`, `type` alias) and give primitive roles PEP 695 aliases with an example value in a trailing comment.
- Name variables with complete words. Comments explain non-obvious intent only, with no issue or PR references.
- Seconds never appear in any rendered duration. Negative durations clamp to zero.

---

### Task 1: The four profiles and their rendering rules

**Files:**
- Create: `common/duration_presentation.py`
- Test: `tests/test_duration_presentation.py`

**Interfaces:**
- Produces: `type DurationProfileId = str  # e.g. "decimal_hours"`
- Produces: `DURATION_FORMAT_PROFILES: Mapping[DurationProfileId, DurationProfile]` (a `MappingProxyType`), and `duration_format_profile(profile_id) -> DurationProfile` raising `ValueError` on an unregistered id, mirroring `date_time_format_profile()`.
- Produces: `DurationPresentation(profile, locale)` frozen dataclass with `format(value: timedelta | None) -> str`.
- Produces: `format_decimal_hours(value: timedelta | None) -> str`, preference-independent, for non-request callers.

**Gotchas:**
- **Round the total once, then decompose.** Rounding a component after the split yields `2 h 60 m` at 1 h 59 m 45 s. This single rule keeps every profile's carry correct.
- `adaptive` picks the largest unit the raw value reaches, rounds the total to the *next unit down*, decomposes, shows the top two units, and **re-picks if the rounding carried**: `6 d 23 h 40 m` is `1 w 0 d`, not `6 d 24 h`.
- `adaptive` and `hours_minutes` therefore diverge below 24 h at the boundary: 23 h 59 m 45 s renders `1 d 00 h` and `24 h 00 m` respectively. Task 3's dedup must not assume they agree.
- Year is 52 weeks = 364 days. Deliberate: a year is not a whole number of weeks, and nothing here is a calendar date.
- Padding: `hours_minutes` pads minutes to two digits only when hours are present; `adaptive` pads its second unit only when that unit is the hour. Nothing else pads.
- Zero renders `0 h` under `hours_minutes` and `adaptive`, `0.0 h` under `decimal_hours`, `0 hours` under `whole_hours`.
- Leave locale grouping out of this task — Task 2 adds it. Assert ungrouped values here.

- [ ] **Step 1: Write the failing table test**

Drive one parametrized test from the spec's rendering-rules table — every row, every profile, as `(seconds, profile_id, expected)` tuples. Include, beyond the table: `1 h 59 m 45 s` (carry into hours), `6 d 23 h 40 m` (carry into weeks), `29 m 30 s` (half-up at the minute), and a negative `timedelta` (clamps to the zero rendering). Add `test_unregistered_profile_id_raises` and `test_none_renders_as_zero`.

- [ ] **Step 2: Run to verify it fails**

```bash
make test ARGS="tests/test_duration_presentation.py -x"
```

Expected: FAIL — `ModuleNotFoundError: No module named 'common.duration_presentation'`.

- [ ] **Step 3: Implement**

The unit ladder is the only piece worth spelling out; the three fixed profiles fall out of `divmod` on a rounded total.

```python
@dataclass(frozen=True)
class DurationUnit:
    """One rung of the adaptive ladder, largest first."""

    key: str  # e.g. "day"
    seconds: int
    symbol: str  # e.g. "d"
    pad_below: bool  # zero-pad the *next* unit down to two digits


LADDER: Final[tuple[DurationUnit, ...]] = (
    DurationUnit("year", 364 * 86400, "y", pad_below=False),
    DurationUnit("week", 7 * 86400, "w", pad_below=False),
    DurationUnit("day", 86400, "d", pad_below=True),
    DurationUnit("hour", 3600, "h", pad_below=True),
    DurationUnit("minute", 60, "m", pad_below=False),
)
```

`adaptive` then: find the first ladder unit whose `seconds` the total reaches (falling back to the minute), round the total to the next unit down, and re-enter the search if the rounded total now reaches a higher unit. Decompose into that unit and the one below it, padding the lower one when the higher unit's `pad_below` is set.

- [ ] **Step 4: Run tests**

```bash
make test ARGS="tests/test_duration_presentation.py -x"
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add common/duration_presentation.py tests/test_duration_presentation.py
git commit -m "feat: four duration rendering profiles"
```

---

### Task 2: Locale grouping and the decimal separator

**Files:**
- Modify: `common/duration_presentation.py`
- Test: `tests/test_duration_presentation.py`

**Gotchas:**
- `USE_THOUSAND_SEPARATOR` is **absent from `timetracker/settings.py`**, so Django's default `False` applies and `number_format()` groups nothing. Pass `force_grouping=True` per call. Do **not** set the global — it would retroactively regroup every price on the site.
- `DATE_FORMAT_LOCALE` is deliberately never activated request-wide: `common/middleware.py:49` stashes it on the request precisely so date formatting cannot change application translations. Scope `override(locale)` around the `number_format()` call only, following `day_periods_for_locale()` (`common/date_time_presentation.py:293`).
- The `cs` thousand separator is **U+00A0**, not an ASCII space. Write it as `"\xa0"` in assertions.
- `cs` also uses `,` as the decimal separator, so `decimal_hours` renders `1,2 h` there.

- [ ] **Step 1: Write failing tests**

- `test_grouping_under_cs_uses_a_non_breaking_space` — 1234 h under `whole_hours` is `f"1{chr(0xa0)}234 hours"`
- `test_grouping_under_en_us_uses_a_comma` — `"1,234 hours"`
- `test_decimal_separator_follows_the_locale` — 1 h 12 m under `decimal_hours` is `"1,2 h"` for `cs`, `"1.2 h"` for `en-us`
- `test_small_values_are_not_grouped` — 26 h has no separator in either locale
- `test_formatting_does_not_leak_the_active_translation` — assert `get_language()` is unchanged after a `cs` format call

- [ ] **Step 2: Run to verify they fail**

```bash
make test ARGS="tests/test_duration_presentation.py -k locale -x"
```

Expected: FAIL — values render ungrouped with a `.` separator.

- [ ] **Step 3: Implement, then update Task 1's expectations**

Route every numeric component through one helper that wraps `number_format(..., force_grouping=True)` in `override(self.locale)`. Update the four-digit rows in Task 1's table test to expect grouped output.

- [ ] **Step 4: Run tests**

```bash
make test ARGS="tests/test_duration_presentation.py -x"
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add common/duration_presentation.py tests/test_duration_presentation.py
git commit -m "feat: durations group and punctuate numbers by locale"
```

---

### Task 3: Alternates and the spoken form

**Files:**
- Modify: `common/duration_presentation.py`
- Test: `tests/test_duration_presentation.py`

**Interfaces:**
- Produces: `type ProfileLabel = str  # e.g. "Hours and minutes"`
- Produces: `alternates(value) -> tuple[tuple[ProfileLabel, str], ...]` — the other profiles' renderings, deduplicated.
- Produces: `spoken(value, *, manual: bool = False) -> str`

**Gotchas:**
- **Dedup compares rendered strings**, never profile identity. `adaptive` and `hours_minutes` agree below 24 h but diverge at the carry boundary, so any "these two profiles are equivalent" shortcut is wrong.
- Drop an alternate equal to the visible rendering or to an earlier alternate. Preserve registry order otherwise.
- The spoken form is profile-independent: hours and minutes in words only, never days or weeks, each component pluralized, zero components omitted, and zero itself spoken as "0 hours". `manual=True` appends ", manual".

- [ ] **Step 1: Write failing tests**

- `test_alternates_exclude_the_visible_rendering`
- `test_alternates_drop_duplicates_below_24h` — under `decimal_hours`, a 1 h 12 m value yields exactly two lines
- `test_alternates_keep_all_three_above_24h` — an 83 h 12 m value yields three
- `test_adaptive_and_hours_minutes_diverge_at_the_carry_boundary` — 23 h 59 m 45 s under `decimal_hours` yields three lines, because `1 d 00 h` and `24 h 00 m` differ
- `test_spoken_uses_words_and_pluralizes` — `"1 hour 12 minutes"`, `"45 minutes"`, `"9000 hours"`, `"0 hours"`
- `test_spoken_never_uses_days_or_weeks`
- `test_spoken_marks_a_manual_session`

- [ ] **Step 2: Run to verify they fail**

```bash
make test ARGS="tests/test_duration_presentation.py -k 'alternates or spoken' -x"
```

Expected: FAIL — `AttributeError: 'DurationPresentation' object has no attribute 'alternates'`.

- [ ] **Step 3: Implement**

- [ ] **Step 4: Run tests**

```bash
make test ARGS="tests/test_duration_presentation.py -x"
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add common/duration_presentation.py tests/test_duration_presentation.py
git commit -m "feat: deduplicated duration alternates and a spoken form"
```

---

### Task 4: Register `DURATION_FORMAT`

**Files:**
- Modify: `timetracker/settings_registry.py`
- Modify: `common/duration_presentation.py` (add `duration_presentation_for_request`)
- Modify: `tests/test_settings_registry.py:21`, `tests/test_admin_settings_page.py:25,38,326`, `e2e/test_admin_settings_page_e2e.py:13`
- Test: `tests/test_duration_setting.py` (create)

**Interfaces:**
- Produces: `duration_presentation_for_request(request) -> DurationPresentation`, caching on the request object exactly as `date_time_presentation_for_request` does.
- Produces: `DURATION_FORMAT_CHOICES: Final[tuple[tuple[str, str], ...]]`.

**Gotchas:**
- `SettingDefinition.__post_init__` raises at import for a USER setting without a `widget` (`:148`) and for a SELECT without `choices` (`:150`). Both are required.
- `reload_after_save=True` is only legal with `ApplyTiming.LIVE` (`:163`).
- **No migration.** Unmapped keys fall through `UserPreferences.extra_preferences` (`games/models.py:570`), as `SESSION_TIME_ZONE_DISPLAY` already does.
- Five fixtures enumerate settings by hand and fail until updated: `USER_KEYS`; `SITE_SETTING_KEYS` (order-sensitive — `tests/test_admin_settings_page.py:239` asserts the rendered order matches it exactly); the literal SELECT-widget count at `:326`, which goes from 8 to 9; and the two env-scrub fixtures.

- [ ] **Step 1: Write failing tests**

In `tests/test_duration_setting.py`: `test_default_is_decimal_hours`, `test_personal_value_overrides_the_site_default`, `test_clearing_the_personal_value_restores_the_site_default`, `test_unregistered_profile_is_rejected`, `test_presentation_is_cached_on_the_request`.

- [ ] **Step 2: Run to verify they fail**

```bash
make test ARGS="tests/test_duration_setting.py -x"
```

Expected: FAIL — `UnregisteredSettingError: DURATION_FORMAT`.

- [ ] **Step 3: Implement**

```python
DURATION_FORMAT_CHOICES: Final[tuple[tuple[str, str], ...]] = (
    ("decimal_hours", "Decimal hours (1.2 h)"),
    ("hours_minutes", "Hours and minutes (1 h 12 m)"),
    ("whole_hours", "Whole hours (1 hour)"),
    ("adaptive", "Adaptive units (3 d 11 h)"),
)
```

Add `_validate_duration_format` alongside `_validate_datetime_format`, then the `SettingDefinition` with `label="Duration format"`, `SettingScope.USER`, `ApplyTiming.LIVE`, `SettingWidget.SELECT`, those choices, `reload_after_save=True`, and `default_factory=lambda: "decimal_hours"`. Update all five pinned fixtures.

- [ ] **Step 4: Run tests**

```bash
make test ARGS="tests/test_duration_setting.py tests/test_settings_registry.py tests/test_admin_settings_page.py -x"
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add timetracker/settings_registry.py common/duration_presentation.py tests/ e2e/
git commit -m "feat: register the duration format preference"
```

---

### Task 5: A popover that can omit `aria-describedby`

**Files:**
- Modify: `common/components/primitives.py:316-465`
- Test: `tests/test_components.py`

**Interfaces:**
- Produces: `Popover(..., describedby: bool = True)`; when `False`, the trigger omits `aria-describedby` while the panel keeps its `id` and `role="tooltip"`.

**Gotchas:**
- Safe for the element's JS: `ts/elements/pop-over.ts` addresses `[data-pop-over-panel]` and `[data-pop-over-trigger]` and never reads `aria-describedby`. No existing test asserts it is unconditionally present.
- The panel still needs its `id`, so the duplicate-id problem in Task 6 is unaffected by this flag.

- [ ] **Step 1: Write failing tests**

`test_popover_omits_describedby_when_disabled` and `test_panel_keeps_its_id_and_tooltip_role_when_describedby_is_off`.

- [ ] **Step 2: Run to verify they fail**

```bash
make test ARGS="tests/test_components.py -k describedby -x"
```

Expected: FAIL — `TypeError: Popover() got an unexpected keyword argument 'describedby'`.

- [ ] **Step 3: Implement**

- [ ] **Step 4: Run tests**

```bash
make test ARGS="tests/test_components.py -x"
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add common/components/primitives.py tests/test_components.py
git commit -m "feat: popovers can opt out of aria-describedby"
```

---

### Task 6: The `Duration()` component

**Files:**
- Modify: `common/components/domain.py`
- Test: `tests/test_duration_component.py` (create)

**Interfaces:**
- Produces: `Duration(value: timedelta | None, presentation: DurationPresentation, *, id_scope: str, manual: bool = False) -> Node`

**Gotchas:**
- **`id_scope` is required, and every call site must pass a unique one.** `Popover()` otherwise hashes its own content for an id (`primitives.py:450`), so two rows with the same duration collide and `assert_unique_element_ids()` raises during DEBUG page assembly (`core.py:506`). `Game.playtime` defaults to `timedelta(0)`, so any game list with two never-played games trips it — and `tests/test_html_validity.py:187` asserts exactly that page. `PurchasePrice` carries a comment about having been bitten by this.
- The trigger stays `tap=True` — a real `<button>`, keyboard-operable. The tab-stop cost is ordinary: `DEFAULT_PAGE_SIZE` is 25, and a session row already carries a game link, a device dropdown, Edit, and Delete.
- Pass `describedby=False` from Task 5: the panel duplicates what the `sr-only` text already says, and without this Orca reads the same number three ways per row.
- Visible text is `aria-hidden`; the `sr-only` sibling carries `presentation.spoken(...)`.
- The manual `*` mark goes **inside the trigger, after the visible value**, under the same `aria-hidden`, with `manual=True` adding ", manual" to the spoken text. It never appears in alternates — it qualifies the value, not its formatting.
- `tabular-nums` on both the visible cell and the popover values. The visible cell currently gets its fixed width from the `%02.1H` pattern being deleted.
- Reuse `underline decoration-dotted` so durations and prices share one hoverable-value look.

- [ ] **Step 1: Write failing tests**

- `test_visible_value_is_hidden_from_assistive_technology`
- `test_spoken_text_is_rendered_sr_only`
- `test_manual_mark_follows_the_value_and_is_spoken`
- `test_alternates_render_as_label_value_rows`
- `test_two_equal_durations_get_distinct_ids` — render two `Duration()` nodes with the same value and different `id_scope`, assert the ids differ
- `test_describedby_is_absent`

- [ ] **Step 2: Run to verify they fail**

```bash
make test ARGS="tests/test_duration_component.py -x"
```

Expected: FAIL — `ImportError: cannot import name 'Duration'`.

- [ ] **Step 3: Implement**

- [ ] **Step 4: Run tests**

```bash
make test ARGS="tests/test_duration_component.py -x"
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add common/components/domain.py common/components/__init__.py tests/test_duration_component.py
git commit -m "feat: Duration renders a value with its alternate formats"
```

---

### Task 7: Port the session and game surfaces

**Files:**
- Modify: `games/views/session.py:62`, `games/views/game.py:124,451,505,612`
- Modify: `games/views/general.py:82-83`
- Test: `tests/test_rendered_pages.py`

**Interfaces:**
- Consumes: `Duration()` and `duration_presentation_for_request()`.

**Gotchas:**
- The navbar values come from the `model_counts` context processor, which has the request — no new plumbing.
- `id_scope` per surface: `f"session-{pk}-duration"`, `f"game-{pk}-playtime"`, `"navbar-today"`, `"navbar-last-7"`. Two durations in one page must never share one.
- The session cell's `*` is now `Duration(..., manual=session.is_manual())`, not a string concatenation.

- [ ] **Step 1: Write failing tests**

Assert each page renders the popover markup and that a list with two equal-duration rows has unique ids.

- [ ] **Step 2: Run to verify they fail**

```bash
make test ARGS="tests/test_rendered_pages.py -x"
```

- [ ] **Step 3: Implement**

- [ ] **Step 4: Run tests**

```bash
make test ARGS="tests/test_rendered_pages.py tests/test_html_validity.py -x"
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add games/views/ tests/
git commit -m "feat: sessions, games, and the navbar use the duration formatter"
```

---

### Task 8: Move stats and play events to `timedelta`

**Files:**
- Modify: `games/views/stats_data.py:39,59,63,279,306,318`
- Modify: `games/views/stats_content.py:105,149,199,212`
- Modify: `games/views/playevent.py:166`
- Test: `tests/test_stats.py`

**Gotchas:**
- `compute_stats()` is documented as pure computation with no HTTP and must stay that way, so it returns `timedelta` and `stats_content` formats.
- `StatsData.total_hours` changes from `str` to `timedelta`; `longest_session_time` and `highest_session_average` change from `Any` (today `timedelta`-or-integer-`0`) to `timedelta | None`. **The `0` fallback becomes `None`** — every consumer must handle it.
- `playevent.py:166` has the same shape: return the `timedelta`, format at the call site.
- `stats_links.py` parity tests assert counts, not durations, and should be unaffected — confirm rather than assume.

- [ ] **Step 1: Write failing tests**

Assert `compute_stats()` returns `timedelta` values and `None` where a stat is absent, and that the stats page renders duration popovers.

- [ ] **Step 2: Run to verify they fail**

```bash
make test ARGS="tests/test_stats.py -x"
```

- [ ] **Step 3: Implement**

- [ ] **Step 4: Run tests**

```bash
make test ARGS="tests/test_stats.py tests/test_rendered_pages.py -x" && make typecheck
```

Expected: PASS. mypy is the real gate here — the `TypedDict` change ripples.

- [ ] **Step 5: Commit**

```bash
git add games/views/ tests/
git commit -m "refactor: stats compute durations and render them separately"
```

---

### Task 9: Delete the old formatter

**Files:**
- Modify: `common/time.py:8-79` (delete `format_duration`, `durationformat`, `durationformat_manual`)
- Modify: `games/models.py:106,273-283,352-365`
- Modify: `tests/test_time.py`, `tests/test_session_formatting.py:36-39`

**Gotchas:**
- `Session.duration_formatted()`, `duration_formatted_with_mark()`, and `Game.playtime_formatted()` are deleted — a model method has no request and cannot resolve a per-user preference.
- `Session.__str__` calls `format_decimal_hours()` from Task 1 instead. It is a debug/admin/log string, not UI.
- `SessionQuerySet.total_duration_formatted()` and `calculated_duration_formatted()` have **no callers anywhere** (verified across Python, templates, `ts/`, `dist/`, e2e, management commands, and the API). Delete them. Their `*_unformatted()` siblings **do** have callers and must stay.
- `tests/test_session_formatting.py:37` asserts `duration_formatted()` but its class also holds unrelated datetime tests, so it cannot be deleted wholesale alongside `tests/test_time.py`'s duration half.

- [ ] **Step 1: Delete and update**

- [ ] **Step 2: Verify nothing references the removed names**

```bash
grep -rn "format_duration\|durationformat\|duration_formatted\|playtime_formatted" --include=*.py . | grep -v "_unformatted"
```

Expected: no output.

- [ ] **Step 3: Run the suite**

```bash
make check-fast
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add -A common/ games/ tests/
git commit -m "refactor: retire the format_duration mini-language"
```

---

### Task 10: Documentation, changelog, and the gate

**Files:**
- Modify: `docs/configuration.md` (a `Duration format` bullet beside the other per-preference entries)
- Modify: the changelog
- Test: `e2e/test_duration_format_e2e.py` (create)

**Gotchas:**
- The per-preference list is ordered to match `SITE_SETTING_KEYS`; keep it that way.
- Document what each profile does with a sub-hour value, since that is where they visibly disagree.

- [ ] **Step 1: Write the e2e test**

Change the preference on `/settings`, confirm the sessions list re-renders in the new profile, open a duration popover, and assert the alternates exclude the visible value.

- [ ] **Step 2: Run it**

```bash
make test-e2e
```

Expected: PASS. Confirm `make dev` is not running first.

- [ ] **Step 3: Write the docs and changelog entries**

- [ ] **Step 4: Full gate**

```bash
make check && git diff --check
```

Expected: PASS.

- [ ] **Step 5: Commit and open the PR**

```bash
git add -A docs/ e2e/
git commit -m "docs: describe the duration format preference"
```

PR targets `main` and closes #486.

- [ ] **Step 6: Screen-reader pass**

Ask for an Orca run over a session list. The check: each duration is announced once, in words, with no repetition of the same number in other formats. If it is noisy, the `describedby=False` decision from Task 5 is the first thing to revisit.
