# DateTime Field Follows the Session Zone Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A session timestamp's typed digits are always interpreted in the zone currently selected in its paired `time-zone-row` picker — client-side (live, as the picker changes), server-side (rendering and binding), never by reprojecting already-typed digits.

**Architecture:** The `date-time-field` custom element gains a `zone-field-name` prop linking it to its paired `time-zone-row` (same precedent as `DateTimeCopyTarget`). The wire codec takes a zone-resolver callback so `encode()` stamps the selected zone's offset; the row dispatches a bubbling `time-zone-row:change` event and the field re-encodes its unchanged segment buffers on it. Server-side, `DateTimeFieldWidget._wire_value` renders in the field's resolved zone (stored zone → display zone, via one shared helper) and `AwareDateTimeField` binds naive fallback values under `timezone.override(selected_zone)`.

**Tech Stack:** Django 6 forms/widgets, Python components (`common/components`), TypeScript custom elements + Temporal, vitest, pytest, Playwright e2e.

## Global Constraints

- `make check` (lint + format-check + mypy + ts-check + vitest + full pytest incl. `e2e/`) is the verification gate; `ARGS` is for iterating only, never the gate.
- Never write to `GeneratedField`s (`duration_calculated`, `duration_total`, `price_per_game`, `days_to_finish`).
- Build UI with `common.components` node builders (htpy form: kwargs attributes, `[]` children); never raw HTML strings.
- New interactive behavior is a custom element + TypeScript under `ts/elements/`; server↔client props are one TypedDict registered with `register_element(...)`; run `make gen-element-types` after changing props; run `make ts` after editing any `.ts`.
- JS-bearing components declare `Media`; never re-add `scripts=` threading for component-owned JS.
- Complete, unabbreviated variable names (`element`, `event`, `zoneFieldName` — no `el`/`e`/`tz` locals).
- Comments explain present intent only — no issue/PR/history references except forward TODOs.
- This repo is Python 3.14-only: `except A, B:` (PEP 758, unparenthesized) is the formatter's own output — do not "fix" it.

## Locked design decisions (do not re-litigate)

1. **Decision "B", categorical:** the typed digits mean the zone currently selected in the paired picker. Changing the zone never converts or re-renders the digits; only the committed wire value's offset (and therefore the instant) changes. There is no instant-preserving reprojection anywhere.
2. **What re-renders on a zone change: nothing visible in the datetime field.** The segment inputs keep their exact buffers. The only mutations are (a) the hidden `[data-date-time-hidden]` input is re-encoded — same wall clock, new offset suffix (or bare wall clock if the digits fall in the new zone's DST gap), and (b) `date-time-field:change` fires because the hidden value changed. The `time-zone-row` trigger label updates via its own existing code.
3. **"Now" (design call):** fills the current wall clock *in the field's currently selected zone*, offset-qualified. Rationale: a "Now" in any other zone stores an instant the user never meant; in the selected zone it is always the true current instant. This flips the old "account wall clock" behavior (and its e2e test) — on the add form the capture default selects the browser zone, so "Now" now writes the browser's wall clock, which is *correct* because the offset rides along.
4. **Copy ↓/↑ arrows (design call):** copy the digits verbatim (wall clock + sub-minute residual); the target field's own selected zone gives them meaning. Rationale: the dominant use is same-session convenience where both zones agree; digits visibly identical is predictable; instant-conversion would change visible digits, the exact thing decision B forbids. Mechanically this is already what `setValue()` does once `encode` is zone-aware (decode drops the offset, re-encode uses the target's zone) — the plan only pins it with a test. Consequence when the two pickers differ: the two hidden values name different instants for the same digits. Accepted.
5. **Accepted consequence (add-form prefill):** `add_session` seeds `timestamp_start` with "now" rendered in the account zone; the capture default then stamps the browser zone, so for a traveling user the prefilled digits are reinterpreted in the browser zone (instant shifts by the zone difference). This is decision B applied consistently; the emphasized trigger names the zone, and one "Now" click produces the exact current instant. No special-casing.
6. **Server naive fallback follows the selected zone.** A DST-gap submission posts a bare wall clock. Today Django interprets/rejects it in the *account* zone; with per-field zones that is wrong both ways (silently accepts a gap wall clock valid in the account zone; rejects an account-zone gap that is valid in the selected zone). `AwareDateTimeField` gains a zone resolver and binds under `timezone.override`.
7. **The edit form's zone is always the session's own, never the display preference.** `SESSION_TIME_ZONE_DISPLAY` only governs how the read-only list/table renders a session; it has no bearing on what zone the datetime field interprets when editing. A session tagged Asia/Tokyo always edits in Tokyo digits, even when the account's display preference (governing the list) is "account". This can mean the same session shows different digits on the list page and the edit page — accepted, because editing exposes the authoritative recorded zone via the always-visible zone-picker label right next to the field ("Start time zone: Asia/Tokyo"), so which zone you're looking at is never ambiguous. Confirmed with the user rather than silently assumed.

---

### Task 1: Shared zone-name parsing helper

**Files:**
- Modify: `common/date_time_presentation.py` (add `zone_or_none` near the bottom, after `DateTimePresentation`)
- Modify: `games/formatting.py:12-24` (`_presentation_in_zone` uses the helper)
- Test: `tests/test_datetime_field_binding.py`

**Interfaces:**
- Produces: `zone_or_none(zone_name: str | None) -> ZoneInfo | None` in `common.date_time_presentation` — Tasks 2 and 3 import it in `games/forms.py`.

- [ ] **Step 1: Write the failing test** (append to `tests/test_datetime_field_binding.py`; it already imports `ZoneInfo`)

```python
from common.date_time_presentation import zone_or_none


def test_zone_or_none_parses_valid_zones_and_rejects_junk():
    assert zone_or_none("Asia/Tokyo") == ZoneInfo("Asia/Tokyo")
    assert zone_or_none(None) is None
    assert zone_or_none("") is None
    assert zone_or_none("Not/AZone") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `make test ARGS="tests/test_datetime_field_binding.py::test_zone_or_none_parses_valid_zones_and_rejects_junk -x"`
Expected: FAIL with `ImportError: cannot import name 'zone_or_none'`

- [ ] **Step 3: Write minimal implementation**

In `common/date_time_presentation.py`, extend the zoneinfo import at the top to `from zoneinfo import ZoneInfo, ZoneInfoNotFoundError`, then add after the `DateTimePresentation` class:

```python
def zone_or_none(zone_name: str | None) -> ZoneInfo | None:
    """``ZoneInfo`` for a stored zone name, or ``None`` when the name is
    missing or unusable (e.g. removed from tzdata) — every caller falls back
    to the account display zone rather than crashing on a stale row."""
    if not zone_name:
        return None
    try:
        return ZoneInfo(zone_name)
    except ZoneInfoNotFoundError, ValueError:
        return None
```

In `games/formatting.py`, rewrite `_presentation_in_zone` to delegate (and drop the now-unused `ZoneInfoNotFoundError` import if ruff flags it):

```python
from common.date_time_presentation import (
    DateTimePresentation,
    DateTimeStyle,
    zone_or_none,
)


def _presentation_in_zone(
    presentation: DateTimePresentation, zone_name: str | None
) -> DateTimePresentation | None:
    """``presentation`` re-aimed at a session's own zone, or ``None`` when the
    stored name is missing or unusable — the caller falls back to the account
    zone rather than crashing a list page."""
    zone = zone_or_none(zone_name)
    return None if zone is None else replace(presentation, timezone=zone)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `make test ARGS="tests/test_datetime_field_binding.py tests/test_session_time_range_timezones.py -x"`
Expected: PASS (the range-timezone tests prove the refactor changed nothing)

- [ ] **Step 5: Commit**

```bash
git add common/date_time_presentation.py games/formatting.py tests/test_datetime_field_binding.py
git commit -m "refactor: extract shared zone_or_none helper"
```

---

### Task 2: Server renders each timestamp in its resolved zone, and names its paired row

**Files:**
- Modify: `common/components/custom_elements.py:185-190` (`DateTimeFieldProps`)
- Modify: `common/components/date_time_picker.py` (`DateTimePicker` signature + `_DateTimeField` call)
- Modify: `games/forms.py` (`DateTimeFieldWidget`, `SessionForm.__init__`, new `_TIMESTAMP_ZONE_FIELDS`)
- Generated: `ts/generated/props.ts` via `make gen-element-types`
- Test: `tests/test_datetime_field_binding.py`

**Interfaces:**
- Consumes: `zone_or_none` (Task 1).
- Produces:
  - `DateTimeFieldProps` gains `zone_field_name: str` → attribute `zone-field-name` and `readDateTimeFieldProps(...).zoneFieldName` (Task 6 reads it client-side).
  - `DateTimePicker(..., zone_field_name: str = "")`.
  - `DateTimeFieldWidget(*, presentation, label, copy_target=None, zone_field_name: str = "", zone_resolver: Callable[[], ZoneInfo] | None = None, attrs=None)`.
  - `SessionForm._resolved_field_zone(zone_field_name: str) -> ZoneInfo` (Task 3 reuses the same `partial` resolver).

- [ ] **Step 1: Write the failing tests** (append to `tests/test_datetime_field_binding.py`)

```python
def test_edit_form_renders_the_wall_clock_in_the_sessions_own_zone(db):
    """A Tokyo-tagged 06:37 UTC start must render as Tokyo's 15:37+09:00, not
    the account's 08:37+02:00 — the digits shown are the digits that were
    typed against that zone."""
    game = Game.objects.create(name="Hades")
    session = Session.objects.create(
        game=game,
        timestamp_start=datetime(2026, 7, 28, 6, 37, tzinfo=UTC),
        timestamp_start_timezone="Asia/Tokyo",
    )
    rendered = str(
        SessionForm(instance=session, presentation=_presentation("Europe/Prague"))[
            "timestamp_start"
        ]
    )
    hidden = re.search(r'name="timestamp_start" value="([^"]*)"', rendered)
    assert hidden is not None
    assert hidden.group(1) == "2026-07-28T15:37:00+09:00"


def test_an_unusable_stored_zone_falls_back_to_the_display_zone(db):
    game = Game.objects.create(name="Hades")
    session = Session.objects.create(
        game=game,
        timestamp_start=datetime(2026, 7, 28, 6, 37, tzinfo=UTC),
        timestamp_start_timezone="Not/AZone",
    )
    rendered = str(
        SessionForm(instance=session, presentation=_presentation("Europe/Prague"))[
            "timestamp_start"
        ]
    )
    hidden = re.search(r'name="timestamp_start" value="([^"]*)"', rendered)
    assert hidden is not None
    assert hidden.group(1) == "2026-07-28T08:37:00+02:00"


def test_session_datetime_widgets_name_their_paired_zone_row(db):
    form = SessionForm(presentation=_presentation("Europe/Prague"))
    assert 'zone-field-name="timestamp_start_timezone"' in str(form["timestamp_start"])
    assert 'zone-field-name="timestamp_end_timezone"' in str(form["timestamp_end"])
    # The GameStatusChange form has no zone rows: its widget stays unpaired.
    status_form = GameStatusChangeForm(presentation=_presentation("Europe/Prague"))
    assert 'zone-field-name=""' in str(status_form["timestamp"])
```

Note: `Not/AZone` fails the `timestamp_start_timezone` form *choice* validation on submit, but `Session.objects.create` bypasses forms — exactly how a zone later removed from tzdata looks.

- [ ] **Step 2: Run tests to verify they fail**

Run: `make test ARGS="tests/test_datetime_field_binding.py -x -k 'own_zone or unusable_stored or paired_zone_row'"`
Expected: FAIL — first on the Tokyo assertion (renders `2026-07-28T08:37:00+02:00`)

- [ ] **Step 3: Implement**

`common/components/custom_elements.py` — extend the TypedDict:

```python
class DateTimeFieldProps(TypedDict):
    field_name: str  # the Django field name, e.g. "timestamp_start" — how a
    # copy control on one datetime field addresses another one on the same page
    zone_field_name: str  # the paired time-zone-row's field name, e.g.
    # "timestamp_start_timezone"; "" = no paired row, the display zone applies
```

Run `make gen-element-types` (regenerates `ts/generated/props.ts`; `readDateTimeFieldProps` gains `zoneFieldName`).

`common/components/date_time_picker.py` — `DateTimePicker` gains the parameter and forwards it:

```python
def DateTimePicker(
    *,
    presentation: DateTimePresentation,
    label: str,
    name: str,
    value: str = "",
    input_id: str = "",
    required: bool = False,
    invalid: bool = False,
    copy_target: DateTimeCopyTarget | None = None,
    zone_field_name: str = "",
) -> Node:
```

and inside it:

```python
    field = _DateTimeField(
        class_="relative", field_name=name, zone_field_name=zone_field_name
    )[
```

`games/forms.py` — imports (top of file): add `from collections.abc import Callable`, `from functools import partial`, `from zoneinfo import ZoneInfo`, and `zone_or_none` to the existing `common.date_time_presentation` import. Then:

```python
class DateTimeFieldWidget(forms.Widget):
    def __init__(
        self,
        *,
        presentation: DateTimePresentation,
        label: str,
        copy_target: DateTimeCopyTarget | None = None,
        zone_field_name: str = "",
        zone_resolver: Callable[[], ZoneInfo] | None = None,
        attrs=None,
    ):
        super().__init__(attrs)
        self.presentation = presentation
        self.label = label
        self.copy_target = copy_target
        self.zone_field_name = zone_field_name
        self.zone_resolver = zone_resolver
```

`_wire_value` — the aware branch projects into the resolved zone (keep the existing naive-value comment above it):

```python
if timezone.is_aware(value):
    zone = self.zone_resolver() if self.zone_resolver else self.presentation.timezone
    value = timezone.localtime(value, zone)
```

`render()` — pass `zone_field_name=self.zone_field_name` to `DateTimePicker(...)`.

After `SESSION_TIMEZONE_EMBEDS` add:

```python
# Host timestamp → its zone field: the inverse view the datetime widgets need.
_TIMESTAMP_ZONE_FIELDS: Final[dict[str, str]] = {
    host_name: zone_name for zone_name, host_name in SESSION_TIMEZONE_EMBEDS.items()
}
```

`SessionForm.__init__` — store the presentation and wire the resolver (replaces the existing `_TIMESTAMP_COPY_TARGETS` loop body):

```python
    def __init__(self, *args, presentation: DateTimePresentation, **kwargs):
        super().__init__(*args, **kwargs)
        self._presentation = presentation
        for field_name, copy_target in _TIMESTAMP_COPY_TARGETS.items():
            zone_field_name = _TIMESTAMP_ZONE_FIELDS[field_name]
            zone_resolver = partial(self._resolved_field_zone, zone_field_name)
            self.fields[field_name].widget = DateTimeFieldWidget(
                presentation=presentation,
                label=str(self.fields[field_name].label or field_name),
                copy_target=copy_target,
                zone_field_name=zone_field_name,
                zone_resolver=zone_resolver,
            )
```

and add the method to `SessionForm`:

```python
    def _resolved_field_zone(self, zone_field_name: str) -> ZoneInfo:
        """The zone this timestamp's digits are meant in: the paired zone
        picker's current value when usable, else the account display zone."""
        if self.is_bound:
            raw_zone = self.data.get(zone_field_name)
        else:
            raw_zone = self.initial.get(zone_field_name)
        zone = zone_or_none(raw_zone if isinstance(raw_zone, str) else None)
        return zone or self._presentation.timezone
```

(An instance-backed unbound form's `self.initial` already carries the model's zone via `model_to_dict` — `timestamp_start_timezone` is in `Meta.fields`.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `make test ARGS="tests/test_datetime_field_binding.py tests/test_session_timezone_form.py -x"`
Expected: PASS (including the pre-existing ambiguous-DST round-trip test — NULL zone still resolves to the display zone)

- [ ] **Step 5: Commit**

```bash
git add common/components/custom_elements.py common/components/date_time_picker.py games/forms.py ts/generated/props.ts tests/test_datetime_field_binding.py
git commit -m "feat: render session timestamps in their own zone, link widget to zone row"
```

---

### Task 3: Naive fallback values bind in the selected zone

**Files:**
- Modify: `games/forms.py` (`AwareDateTimeField`, `SessionForm.__init__`)
- Test: `tests/test_datetime_field_binding.py`

**Interfaces:**
- Consumes: `_resolved_field_zone` / the `partial` resolver from Task 2.
- Produces: `AwareDateTimeField.zone_resolver: Callable[[], ZoneInfo] | None` (instance attribute, default `None`).

- [ ] **Step 1: Write the failing tests** (append to `tests/test_datetime_field_binding.py`; reuse the file's middleware harness)

```python
def test_naive_input_is_interpreted_in_the_selected_zone(db):
    """A DST-gap submission posts the bare wall clock; the digits were typed
    against the *picked* zone, so that is the zone they bind in."""
    user = get_user_model().objects.create_user(username="tester", password="pw")
    game = Game.objects.create(name="Hades")
    UserPreferences.objects.create(user=user, display_time_zone="Europe/Prague")
    settings_resolver.clear_cache()
    captured: dict[str, object] = {}

    def response(request):
        form = SessionForm(
            data={
                **_session_form_data(game, "2026-07-28T15:37"),
                "timestamp_start_timezone": "Asia/Tokyo",
            },
            presentation=_presentation("Europe/Prague"),
        )
        assert form.is_valid(), form.errors
        captured["timestamp_start"] = form.cleaned_data["timestamp_start"]
        return HttpResponse()

    request = RequestFactory().post("/tracker/session/add")
    request.user = user
    TimezoneActivationMiddleware(response)(request)

    assert captured["timestamp_start"] == datetime(2026, 7, 28, 6, 37, tzinfo=UTC)


def test_naive_gap_in_the_selected_zone_is_rejected_naming_it(db):
    """2026-03-08 02:30 does not exist in America/New_York. The account zone
    (Tokyo, no DST) would accept it happily — the rejection must come from the
    selected zone, and name it."""
    user = get_user_model().objects.create_user(username="tester", password="pw")
    game = Game.objects.create(name="Hades")
    UserPreferences.objects.create(user=user, display_time_zone="Asia/Tokyo")
    settings_resolver.clear_cache()
    captured: dict[str, object] = {}

    def response(request):
        form = SessionForm(
            data={
                **_session_form_data(game, "2026-03-08T02:30"),
                "timestamp_start_timezone": "America/New_York",
            },
            presentation=_presentation("Asia/Tokyo"),
        )
        captured["errors"] = form.errors.as_text()
        return HttpResponse()

    request = RequestFactory().post("/tracker/session/add")
    request.user = user
    TimezoneActivationMiddleware(response)(request)

    assert "couldn’t be interpreted in time zone America/New_York" in str(
        captured["errors"]
    )


def test_naive_value_valid_in_the_selected_zone_survives_an_account_zone_gap(db):
    """The mirror case: 02:30 on 2026-03-08 is the account zone's spring-forward
    gap, but a perfectly ordinary Tokyo wall clock — it must bind, not error."""
    user = get_user_model().objects.create_user(username="tester", password="pw")
    game = Game.objects.create(name="Hades")
    UserPreferences.objects.create(user=user, display_time_zone="America/New_York")
    settings_resolver.clear_cache()
    captured: dict[str, object] = {}

    def response(request):
        form = SessionForm(
            data={
                **_session_form_data(game, "2026-03-08T02:30"),
                "timestamp_start_timezone": "Asia/Tokyo",
            },
            presentation=_presentation("America/New_York"),
        )
        assert form.is_valid(), form.errors
        captured["timestamp_start"] = form.cleaned_data["timestamp_start"]
        return HttpResponse()

    request = RequestFactory().post("/tracker/session/add")
    request.user = user
    TimezoneActivationMiddleware(response)(request)

    assert captured["timestamp_start"] == datetime(2026, 3, 7, 17, 30, tzinfo=UTC)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `make test ARGS="tests/test_datetime_field_binding.py -x -k naive"`
Expected: the two new selected-zone tests FAIL (bound in / rejected by the account zone); the two pre-existing account-zone tests still PASS (no zone posted → resolver falls back to the display zone).

- [ ] **Step 3: Implement**

`games/forms.py` — extend `AwareDateTimeField` (keep the existing docstring, add the second paragraph):

```python
class AwareDateTimeField(forms.DateTimeField):
    """A ``DateTimeField`` that hands its widget the *aware* stored value.

    [existing paragraph unchanged]

    ``zone_resolver`` (set by ``SessionForm``) is the paired zone picker's
    current zone. The offset-qualified value the widget normally submits binds
    the same under any active zone; the *naive* fallback shape (a DST-gap
    submission) must be interpreted — and gap/ambiguity-checked — in the zone
    the digits were typed against, not the account zone.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.zone_resolver: Callable[[], ZoneInfo] | None = None

    def prepare_value(self, value):
        return value

    def to_python(self, value):
        if self.zone_resolver is None:
            return super().to_python(value)
        with timezone.override(self.zone_resolver()):
            return super().to_python(value)
```

`SessionForm.__init__` — inside the `_TIMESTAMP_COPY_TARGETS` loop, after assigning the widget:

```python
            timestamp_field = self.fields[field_name]
            assert isinstance(timestamp_field, AwareDateTimeField)
            timestamp_field.zone_resolver = zone_resolver
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `make test ARGS="tests/test_datetime_field_binding.py tests/test_session_timezone_form.py"`
Expected: PASS (all of both files)

- [ ] **Step 5: Commit**

```bash
git add games/forms.py tests/test_datetime_field_binding.py
git commit -m "feat: bind naive timestamp fallbacks in the selected session zone"
```

---

### Task 4: The wire codec encodes against a resolver-supplied zone

**Files:**
- Modify: `ts/elements/date-time-codec.ts`
- Test: `ts/elements/date-time-codec.test.ts`

**Interfaces:**
- Produces: `createDateTimeCodec(initialValue: string, resolveZone?: () => string | null): DateTimeCodec`. `encode` uses `resolveZone?.() ?? presentationClock().timeZone`; the hour cycle still always comes from the presentation contract (it is a format preference, not a zone property). Task 6 passes the resolver.

- [ ] **Step 1: Write the failing tests** (append to the `describe("date-time codec encode", ...)` block; the file's `codecModule`/`PARTS` helpers already exist)

```ts
  it("encodes against the zone the resolver names, not the contract's", async () => {
    const { createDateTimeCodec } = await codecModule("Europe/Prague", "h23");
    const codec = createDateTimeCodec("", () => "Asia/Tokyo");

    expect(codec.encode(PARTS, true)).toBe("2026-07-27T14:30:00.000000+09:00");
  });

  it("falls back to the contract zone when the resolver has nothing", async () => {
    const { createDateTimeCodec } = await codecModule("Europe/Prague", "h23");
    const codec = createDateTimeCodec("", () => null);

    expect(codec.encode(PARTS, true)).toBe("2026-07-27T14:30:00.000000+02:00");
  });

  it("submits a resolver-zone DST gap bare, exactly like a contract-zone gap", async () => {
    const { createDateTimeCodec } = await codecModule("Asia/Tokyo", "h23");
    const codec = createDateTimeCodec("", () => "America/New_York");

    // 02:30 on 2026-03-08 does not exist in New York; Tokyo would accept it.
    expect(
      codec.encode({ ...PARTS, month: "03", day: "08", hour: "02" }, true),
    ).toBe("2026-03-08T02:30:00.000000");
  });

  it("submits bare when the resolver names a zone this runtime does not know", async () => {
    const { createDateTimeCodec } = await codecModule("Europe/Prague", "h23");
    const codec = createDateTimeCodec("", () => "Not/AZone");

    expect(codec.encode(PARTS, true)).toBe("2026-07-27T14:30:00.000000");
    expect(reportClientError).toHaveBeenCalled();
  });
```

The last case makes the codec report for the first time, so stub the reporter at the top of the file alongside the existing `../date-time-presentation.js` mock (otherwise the real one console.errors and fires a fetch on every run):

```ts
const reportClientError = vi.hoisted(() => vi.fn());

vi.mock("../client-errors.js", () => ({ reportClientError }));
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `make test-ts`
Expected: the four new cases FAIL (resolver argument ignored → contract-zone offsets / a throw on the unknown zone)

- [ ] **Step 3: Implement** (`ts/elements/date-time-codec.ts`)

```ts
export function createDateTimeCodec(
  initialValue: string,
  resolveZone?: () => string | null,
): DateTimeCodec {
```

and in `encode`, after the `clock` guard:

```ts
      const timeZone = resolveZone?.() ?? clock.timeZone;
```

then replace the `plain.toZonedDateTime(clock.timeZone, ...)` call (keep the existing disambiguation comment above it). Every other degrade path in this area reports; a silent `catch` here would be the one blind spot:

```ts
      let zoned: Temporal.ZonedDateTime;
      try {
        zoned = plain.toZonedDateTime(timeZone, { disambiguation: "earlier" });
      } catch (error) {
        // A zone this runtime's tzdata does not know: report it, then submit
        // the bare wall clock and let the server's own zone resolution
        // interpret it.
        reportClientError("date-time-codec", String(error), { toast: false });
        return wallClock;
      }
```

`date-time-codec.ts` imports nothing from `client-errors.js` today, so add `import { reportClientError } from "../client-errors.js";` next to its existing imports. Note `errorDetail` is module-private to `date-time-presentation.ts` and is *not* exported — do not import it; `String(error)` is what `ts/elements/quick-filter-bar.ts` and `ts/elements/filter-group.ts` already pass as the detail. (Re-check both facts against the real files before writing the import.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `make test-ts`
Expected: PASS (whole vitest suite)

- [ ] **Step 5: Commit**

```bash
git add ts/elements/date-time-codec.ts ts/elements/date-time-codec.test.ts
git commit -m "feat: date-time codec encodes against a resolver-supplied zone"
```

---

### Task 5: "Now" can name a zone

**Files:**
- Modify: `ts/date-time-presentation.ts` (`nowInPresentationZone`)
- Test: `ts/date-time-presentation.test.ts` (extend the existing `describe("nowInPresentationZone", ...)` block, reusing its `importFormatter` helper and system-time setup)

**Interfaces:**
- Produces: `nowInPresentationZone(timeZoneOverride: string | null = null): string | null` — override wins over the contract zone; an unusable override reports (with a toast, since a click is waiting on it) and returns `null` (callers already degrade on `null`). Task 6 calls it with the selected zone.

- [ ] **Step 1: Write the failing tests** (append inside the existing `describe("nowInPresentationZone", ...)` block)

These follow that block's own pattern exactly: `installConfig(alteredConfig(...))` to give the module a real contract, then an offset-delta assertion against a live `Temporal.Now.plainDateTimeISO("UTC")`. Do **not** reach for `vi.setSystemTime` — `Temporal.Now` does not read `Date.now()`, and the block's `beforeEach` strips the contract attribute, so a test that skips `installConfig` only proves `getPresentation()` returned `null`.

```ts
  it("projects into an override zone when one is named", async () => {
    installConfig(
      alteredConfig((config) => {
        // The contract says +14 year-round; the override says +09. Reading
        // back +09 is only possible if the override won.
        config.time_zone = "Pacific/Kiritimati";
      }),
    );
    const { nowInPresentationZone } = await importFormatter();

    const value = nowInPresentationZone("Asia/Tokyo");
    expect(value).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/);

    const minutesAheadOfUTC = Temporal.PlainDateTime.from(value!)
      .since(Temporal.Now.plainDateTimeISO("UTC"))
      .total({ unit: "minute" });
    expect(Math.abs(minutesAheadOfUTC - 9 * 60)).toBeLessThan(2);
    expect(reportClientError).not.toHaveBeenCalled();
  });

  it("toasts and returns null for an override zone tzdata does not know", async () => {
    installConfig(validConfig());
    const { nowInPresentationZone } = await importFormatter();

    expect(nowInPresentationZone("Not/AZone")).toBeNull();
    // A click is waiting on this one, unlike the contract-zone failures.
    expect(reportClientError).toHaveBeenCalledWith(
      "date-time-presentation",
      expect.any(String),
      { toast: true },
    );
  });
```

Leave the block's pre-existing "returns null on a missing contract" case as is — it reports from `getPresentation()` before the try, so it keeps asserting the silent no-contract degrade the new toast must not reach.

- [ ] **Step 2: Run tests to verify they fail**

Run: `make test-ts`
Expected: FAIL — the first case reads +14 (the override argument is ignored); the second reports with `{ toast: false }`

- [ ] **Step 3: Implement**

```ts
export function nowInPresentationZone(
  timeZoneOverride: string | null = null,
): string | null {
  const presentation = getPresentation();
  if (!presentation) return null;

  try {
    return Temporal.Now.plainDateTimeISO(
      timeZoneOverride ?? presentation.timeZone,
    ).toString({
      smallestUnit: "minute",
    });
  } catch (error) {
    // With an override there is a "Now" click waiting on this: returning null
    // makes the button do visibly nothing, so say so. Without one nothing
    // interactive is blocked, and the quiet degrade stands.
    reportClientError("date-time-presentation", errorDetail(error), {
      toast: timeZoneOverride !== null,
    });
    return null;
  }
}
```

Update its doc comment: "The current wall clock in the contract's zone — or in `timeZoneOverride` when the caller's field follows a session zone — shaped for a `datetime-local` input. …"

- [ ] **Step 4: Run tests to verify they pass**

Run: `make test-ts`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ts/date-time-presentation.ts ts/date-time-presentation.test.ts
git commit -m "feat: nowInPresentationZone accepts a zone override"
```

---

### Task 6: The row announces zone changes; the field follows them

**Files:**
- Create: `ts/elements/time-zone-row-events.ts` (the neutral event contract)
- Modify: `ts/elements/time-zone-row.ts` (dispatch + re-entry guard + live emphasis)
- Modify: `ts/elements/date-time-field.ts` (zone-field-name prop, resolver, resync, "Now")
- Test: `ts/elements/time-zone-row.test.ts`, `ts/elements/date-time-field.test.ts`

**Interfaces:**
- Consumes: `createDateTimeCodec(initialValue, resolveZone)` (Task 4), `nowInPresentationZone(override)` (Task 5), `readDateTimeFieldProps(...).zoneFieldName` (Task 2's codegen).
- Produces, in a **neutral shared module** `ts/elements/time-zone-row-events.ts` that contains only the event name and the detail type — no `customElements.define`, no DOM, no imports. Both elements and both test files import it; neither element imports the other. This is load-bearing, not tidiness: an ES module's body is evaluated *before* the body of any module importing it, so if `date-time-field.ts` imported `time-zone-row.js`, the row would call `customElements.define` first, every `<time-zone-row>` in the DOM would upgrade and fire its capture-default announce before a single `<date-time-field>` existed to listen, and the announce would be dropped on every real page load. A module with no registration side effect cannot invert anything.

```ts
export const TIME_ZONE_ROW_CHANGE_EVENT = "time-zone-row:change";

export interface TimeZoneRowChangeDetail {
  fieldName: string; // the zone field, e.g. "timestamp_start_timezone"
  zone: string; // the effective zone the row now means (never "")
}
```

- [ ] **Step 0: Create the neutral event module** (`ts/elements/time-zone-row-events.ts`, new file)

```ts
/** The `time-zone-row:change` contract, in its own module so neither
 * `time-zone-row.ts` nor `date-time-field.ts` has to import the other's full
 * module (which would invert their `customElements.define` order — whichever
 * module a browser evaluates first upgrades first, and an already-upgraded
 * row can announce before an unregistered field has a listener). */
export const TIME_ZONE_ROW_CHANGE_EVENT = "time-zone-row:change";

export interface TimeZoneRowChangeDetail {
  fieldName: string; // the zone field, e.g. "timestamp_start_timezone"
  zone: string; // the effective zone the row now means (never "")
}
```

- [ ] **Step 1: Write the failing row tests** (append to `ts/elements/time-zone-row.test.ts`, reusing its existing `mount()`/`valueInput()`/`trigger()`/`stubBrowserZone()` helpers; the fixture markup must keep the element's own anatomy — hidden `[data-time-zone-value]` input and a `button[aria-haspopup="dialog"]` whose first child is a text node like `Start time zone: X`)

Add the event-name import at the top of the file, from the neutral module:

```ts
import { TIME_ZONE_ROW_CHANGE_EVENT } from "./time-zone-row-events.js";
```

```ts
  it("announces the picked zone", () => {
    // mount a row with field-name="timestamp_start_timezone",
    // display-zone="Europe/Prague", capture-default="false"
    const events: Array<{ fieldName: string; zone: string }> = [];
    document.addEventListener("time-zone-row:change", (event) => {
      events.push((event as CustomEvent).detail);
    });

    // dispatch the picker's own event, as the existing selection tests do:
    row.dispatchEvent(
      new CustomEvent("search-select:change", {
        bubbles: true,
        detail: { last: { value: "Asia/Tokyo", label: "Asia/Tokyo" } },
      }),
    );

    expect(events).toEqual([
      { fieldName: "timestamp_start_timezone", zone: "Asia/Tokyo" },
    ]);
  });

  it("announces the display zone when the selection is cleared", () => {
    // same mount; dispatch search-select:change with { last: { value: "" } }
    expect(events).toEqual([
      { fieldName: "timestamp_start_timezone", zone: "Europe/Prague" },
    ]);
  });

  it("announces the capture-default stamp", () => {
    // register the document listener BEFORE inserting a row with
    // capture-default="true" and an empty value input — the stamp happens in
    // connectedCallback. The zone equals the (stubbed) browser zone.
    expect(events).toEqual([
      {
        fieldName: "timestamp_start_timezone",
        zone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      },
    ]);
  });

  it("announces once per pick however often it has been reconnected", () => {
    // Without a re-entry guard every reconnect stacks another
    // search-select:change listener, and one pick fans out into N announces —
    // N re-encodes in every field following this row.
    stubBrowserZone("Europe/Prague");
    const host = mount({ storedZone: "Europe/Prague", captureDefault: false });
    const parent = host.parentElement!;
    host.remove();
    parent.append(host);

    const events: Array<{ fieldName: string; zone: string }> = [];
    document.addEventListener(TIME_ZONE_ROW_CHANGE_EVENT, (event) => {
      events.push((event as CustomEvent).detail);
    });
    host.dispatchEvent(
      new CustomEvent("search-select:change", {
        bubbles: true,
        detail: { last: { value: "Asia/Tokyo", label: "Asia/Tokyo", data: {} } },
      }),
    );

    expect(events).toHaveLength(1);
  });

  it("drops the emphasis when the user picks the browser's own zone", () => {
    stubBrowserZone("Asia/Tokyo");
    const host = mount({ storedZone: "Europe/Prague", captureDefault: false });
    expect(trigger(host).classList.contains("font-semibold")).toBe(true);

    host.dispatchEvent(
      new CustomEvent("search-select:change", {
        bubbles: true,
        detail: { last: { value: "Asia/Tokyo", label: "Asia/Tokyo", data: {} } },
      }),
    );

    expect(trigger(host).classList.contains("font-semibold")).toBe(false);
  });

  it("adds the emphasis when the user picks a zone the browser is not in", () => {
    stubBrowserZone("Europe/Prague");
    const host = mount({ storedZone: "Europe/Prague", captureDefault: false });
    expect(trigger(host).classList.contains("font-semibold")).toBe(false);

    host.dispatchEvent(
      new CustomEvent("search-select:change", {
        bubbles: true,
        detail: { last: { value: "Asia/Tokyo", label: "Asia/Tokyo", data: {} } },
      }),
    );

    expect(trigger(host).classList.contains("font-semibold")).toBe(true);
  });
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `make test-ts`
Expected: FAIL — `events` stays empty on the three announce cases; the reconnect case fails on the duplicate listener; both emphasis cases fail because the class is decided once at connect and never revisited

- [ ] **Step 3: Implement the row** (`ts/elements/time-zone-row.ts`)

Import the contract from the neutral module (never define it here):

```ts
import {
  TIME_ZONE_ROW_CHANGE_EVENT,
  type TimeZoneRowChangeDetail,
} from "./time-zone-row-events.js";
```

Add the re-entry guard — the element has no `initialized` flag today, so every reconnect re-registers the `search-select:change` listener; harmless while the handler only rewrote a label, but with `announceZone` it fans one pick out into one announce per past connect:

```ts
class TimeZoneRowElement extends HTMLElement {
  private labelPrefix = "";
  private initialized = false;

  connectedCallback(): void {
    if (this.initialized) return;
    this.initialized = true;
    const props = readTimeZoneRowProps(this);
```

Add two private methods:

```ts
  private announceZone(fieldName: string, zone: string): void {
    this.dispatchEvent(
      new CustomEvent<TimeZoneRowChangeDetail>(TIME_ZONE_ROW_CHANGE_EVENT, {
        bubbles: true,
        detail: { fieldName, zone },
      }),
    );
  }

  /** Emphasis tracks the *current* effective zone, so a manual pick can both
   * light it up and put it out — it is a live "not the zone you are in" cue,
   * not a fact about page load. */
  private updateEmphasis(trigger: HTMLElement, effectiveZone: string): void {
    const detectedZone = browserTimeZone();
    trigger.classList.toggle(EMPHASIS_CLASS, effectiveZone !== detectedZone);
  }
```

Replace the connect-time emphasis block with a call to it:

```ts
    const effectiveZone = valueInput.value || props.displayZone;
    // The zone this row will submit is not necessarily the zone this browser
    // is in — worth a look. Emphasis only: the trigger already names the value.
    this.updateEmphasis(trigger, effectiveZone);
```

and dispatch from both write sites:

```ts
    if (props.captureDefault && valueInput.value === "") {
      valueInput.value = detectedZone;
      this.updateTriggerLabel(trigger, detectedZone);
      this.announceZone(props.fieldName, detectedZone);
    }
```

```ts
    this.addEventListener("search-select:change", (event) => {
      const detail = (event as CustomEvent<SearchSelectChangeDetail>).detail;
      if (!detail || detail.last === null) return;
      valueInput.value = detail.last.value;
      this.updateTriggerLabel(trigger, detail.last.value || fallbackLabel);
      const pickedZone = detail.last.value || props.displayZone;
      this.updateEmphasis(trigger, pickedZone);
      this.announceZone(props.fieldName, pickedZone);
    });
```

Run `make test-ts` — row tests PASS.

- [ ] **Step 4: Write the failing field tests** (`ts/elements/date-time-field.test.ts`)

Update the mock declaration for the new "Now" signature:

```ts
const nowInPresentationZone = vi.hoisted(() =>
  vi.fn<(timeZoneOverride?: string | null) => string | null>(),
);
```

Add the event import from the **neutral** module, and a side-effect import that registers the real row element (nothing pulls it in otherwise — the field element does not import it, and must not):

```ts
import { TIME_ZONE_ROW_CHANGE_EVENT } from "./time-zone-row-events.js";
import "./time-zone-row.js";
```

Extend `markup()` with an optional fourth parameter and new helpers. `zoneRowMarkup` must carry the row's full anatomy — `time-zone-row.connectedCallback` bails out unless it finds *both* `[data-time-zone-value]` and a `button[aria-haspopup="dialog"]` whose first child node is the label text, so a trigger-less fixture would silently never announce anything (copy the shape from `ts/elements/time-zone-row.test.ts`'s own `mount()` helper):

```ts
function markup(fieldName: string, copyTo: string, value = "", zoneFieldName = ""): string {
  // ...unchanged body, except the element opening tag becomes:
  //   <date-time-field field-name="${fieldName}" zone-field-name="${zoneFieldName}">
}

function zoneRowMarkup(
  fieldName: string,
  displayZone: string,
  value: string,
  captureDefault = false,
): string {
  return `
    <time-zone-row field-name="${fieldName}" stored-zone="${value}"
        display-zone="${displayZone}" capture-default="${captureDefault}">
      <input type="hidden" name="${fieldName}" value="${value}" data-time-zone-value />
      <button type="button" aria-haspopup="dialog">Start time zone: ${
        value || `${displayZone} (display zone)`
      }<svg></svg></button>
    </time-zone-row>`;
}

function mountWithZoneRow(zoneValue: string): { start: HTMLElement; end: HTMLElement } {
  document.body.replaceChildren();
  document.body.innerHTML =
    markup("timestamp_start", "timestamp_end", "", "timestamp_start_timezone") +
    zoneRowMarkup("timestamp_start_timezone", "Europe/Prague", zoneValue) +
    markup("timestamp_end", "timestamp_start");
  const [start, end] = Array.from(
    document.querySelectorAll<HTMLElement>("date-time-field"),
  );
  return { start, end };
}

function changeZone(fieldName: string, zone: string): void {
  const row = document.querySelector<HTMLElement>(
    `time-zone-row[field-name="${fieldName}"]`,
  )!;
  row.querySelector<HTMLInputElement>("[data-time-zone-value]")!.value = zone;
  row.dispatchEvent(
    new CustomEvent(TIME_ZONE_ROW_CHANGE_EVENT, {
      bubbles: true,
      detail: { fieldName, zone },
    }),
  );
}
```

New tests:

```ts
  it("encodes typed digits against the zone the paired row has selected", () => {
    const { start } = mountWithZoneRow("Asia/Tokyo");

    fillWholeField(start);

    expect(hidden(start).value).toBe("2026-07-27T14:30:00.000000+09:00");
  });

  it("reinterprets on zone change: same digits, new offset, no reprojection", () => {
    // The crux of decision B. An empty row value means the display zone.
    const { start } = mountWithZoneRow("");
    fillWholeField(start);
    expect(hidden(start).value).toBe("2026-07-27T14:30:00.000000+02:00");

    changeZone("timestamp_start_timezone", "Asia/Tokyo");

    expect(partInput(start, "day").value).toBe("27");
    expect(partInput(start, "hour").value).toBe("14");
    expect(partInput(start, "minute").value).toBe("30");
    expect(hidden(start).value).toBe("2026-07-27T14:30:00.000000+09:00");
  });

  it("a zone change on an empty field commits nothing", () => {
    const { start } = mountWithZoneRow("");

    changeZone("timestamp_start_timezone", "Asia/Tokyo");

    expect(hidden(start).value).toBe("");
  });

  it("asks Now for the selected zone's wall clock", () => {
    const { start } = mountWithZoneRow("Asia/Tokyo");

    openCalendar(start);
    start.querySelector<HTMLElement>("[data-date-range-now]")!.click();

    expect(nowInPresentationZone).toHaveBeenCalledWith("Asia/Tokyo");
  });

  it("copies digits verbatim; each field's own zone gives them meaning", () => {
    // Start follows Tokyo; end has no paired row, so the contract zone
    // (Europe/Prague) applies. Same wall clock, different offsets — two
    // different instants, exactly what decision B's copy semantics say.
    const { start, end } = mountWithZoneRow("Asia/Tokyo");
    fillWholeField(start);
    expect(hidden(start).value).toBe("2026-07-27T14:30:00.000000+09:00");

    start.querySelector<HTMLElement>("[data-date-time-copy]")!.click();

    expect(partInput(end, "hour").value).toBe("14");
    expect(hidden(end).value).toBe("2026-07-27T14:30:00.000000+02:00");
  });

  it("follows the capture default with no user interaction at all", () => {
    // The load-bearing path, end to end inside jsdom: the row stamps the
    // browser zone during its own connectedCallback and announces it, and a
    // field rendered against the account zone re-encodes to the captured one
    // without anybody touching the picker. The field's markup comes first so
    // it upgrades — and subscribes — before the row does, which is the
    // ordering the neutral event module preserves in a real browser.
    const zoneSpy = stubBrowserZone("Asia/Tokyo");
    try {
      document.body.replaceChildren();
      document.body.innerHTML =
        markup(
          "timestamp_start",
          "timestamp_end",
          "2026-07-27T14:30:00.000000+02:00",
          "timestamp_start_timezone",
        ) + zoneRowMarkup("timestamp_start_timezone", "Europe/Prague", "", true);
      const start = document.querySelector<HTMLElement>("date-time-field")!;

      expect(partInput(start, "hour").value).toBe("14");
      expect(hidden(start).value).toBe("2026-07-27T14:30:00.000000+09:00");
    } finally {
      zoneSpy.mockRestore();
    }
  });

  it("stops following its row once it leaves the document", () => {
    // A detached field that still listens would keep rewriting its orphaned
    // hidden input from a replacement row's zone changes.
    const { start } = mountWithZoneRow("");
    fillWholeField(start);
    start.remove();
    const valueAfterRemoval = hidden(start).value;

    changeZone("timestamp_start_timezone", "Asia/Tokyo");

    expect(hidden(start).value).toBe(valueAfterRemoval);
  });
```

`stubBrowserZone` is the same `Intl.DateTimeFormat` spy `ts/elements/time-zone-row.test.ts` uses; copy it into this file and have it *return* the spy so the test restores it itself — a blanket `vi.restoreAllMocks()` would also reach the file's hoisted module mocks:

```ts
const REAL_DATE_TIME_FORMAT = Intl.DateTimeFormat;

function stubBrowserZone(timeZone: string) {
  return vi.spyOn(Intl, "DateTimeFormat").mockImplementation((...formatArguments) => {
    const formatter = new REAL_DATE_TIME_FORMAT(...formatArguments);
    const realResolvedOptions = formatter.resolvedOptions.bind(formatter);
    formatter.resolvedOptions = () => ({ ...realResolvedOptions(), timeZone });
    return formatter;
  });
}
```

Run: `make test-ts` — Expected: FAIL (contract-zone offsets everywhere; `changeZone` does nothing; Now called with no argument; the detached field keeps re-encoding)

- [ ] **Step 5: Implement the field** (`ts/elements/date-time-field.ts`)

Imports — the event contract comes from the **neutral** module, never from `./time-zone-row.js`: importing the row's own module here would evaluate its `customElements.define` first and let rows upgrade (and announce their capture default) before any field is registered to hear it.

```ts
import { readDateTimeFieldProps } from "../generated/props.js";
import {
  TIME_ZONE_ROW_CHANGE_EVENT,
  type TimeZoneRowChangeDetail,
} from "./time-zone-row-events.js";
```

Class changes. **Check first whether `date-time-field.ts` has grown a `disconnectedCallback` since this plan was written** — at time of writing it has none, so the one below is new; if one exists, merge the removal into it rather than declaring a second. (The pre-existing `initialized` guard means a field that is detached and re-attached as the *same node* stays unsubscribed; htmx swaps replace nodes rather than move them, so this does not arise, and re-subscribing would need the guard split per concern.)

```ts
class DateTimeFieldElement extends HTMLElement {
  private initialized = false;
  private codec!: DateTimeCodec;
  private zoneFieldName = "";
  private handleZoneRowChange: ((event: Event) => void) | null = null;

  connectedCallback(): void {
    if (this.initialized) return;
    this.initialized = true;
    this.zoneFieldName = readDateTimeFieldProps(this).zoneFieldName;
    // The residual (seconds, microseconds) is read from the value the field was
    // rendered with, so the codec has to be built before anything writes.
    this.codec = createDateTimeCodec(
      resolveHidden(this)?.value ?? "",
      () => this.selectedZone(),
    );
    if (this.zoneFieldName) {
      this.handleZoneRowChange = (event) => {
        const detail = (event as CustomEvent<TimeZoneRowChangeDetail>).detail;
        if (!detail || detail.fieldName !== this.zoneFieldName) return;
        // The digits are the user's; only their meaning moved. Re-encoding
        // the same segment buffers swaps the committed offset — nothing
        // visible in this field changes.
        syncHiddenFromSegments(
          this,
          SIDE,
          () => resolveHidden(this),
          () => this.announceChange(),
          this.codec,
        );
      };
      document.addEventListener(TIME_ZONE_ROW_CHANGE_EVENT, this.handleZoneRowChange);
    }
    this.initCalendar();
    this.initField();
    this.initCopyControl();
  }

  disconnectedCallback(): void {
    // A document-level listener outlives its element unless removed here: a
    // replaced field would keep re-encoding its detached hidden input from the
    // new row's zone changes.
    if (this.handleZoneRowChange) {
      document.removeEventListener(TIME_ZONE_ROW_CHANGE_EVENT, this.handleZoneRowChange);
      this.handleZoneRowChange = null;
    }
  }

  /** The zone the paired time-zone-row currently means, or null without one —
   * the codec then falls back to the account display zone. */
  private selectedZone(): string | null {
    if (!this.zoneFieldName) return null;
    const row = document.querySelector<HTMLElement>(
      `time-zone-row[field-name="${this.zoneFieldName}"]`,
    );
    if (!row) return null;
    const selected = row.querySelector<HTMLInputElement>(
      "[data-time-zone-value]",
    )?.value;
    return selected || row.getAttribute("display-zone") || null;
  }
```

"Now" handler (replace the comment and call inside `initCalendar`):

```ts
        // The wall clock of whichever zone this field currently follows —
        // paired row's selection, else the account's — never the browser's
        // raw clock: the pair of these digits and that zone's offset is what
        // names the true current instant.
        const now = nowInPresentationZone(this.selectedZone());
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `make test-ts`
Expected: PASS — all new tests plus every pre-existing field/codec/row test (the no-row `mount()` fixtures have `zone-field-name=""` and keep the contract-zone behavior verbatim)

- [ ] **Step 7: Compile and typecheck**

Run: `make ts && make ts-check`
Expected: clean compile, no type errors

- [ ] **Step 8: Commit**

```bash
git add ts/elements/time-zone-row-events.ts ts/elements/time-zone-row.ts ts/elements/date-time-field.ts ts/elements/time-zone-row.test.ts ts/elements/date-time-field.test.ts
git commit -m "feat: date-time-field follows its paired time-zone-row live"
```

---

### Task 7: End-to-end proof of the exact bug, and the two flipped e2e expectations

**Files:**
- Modify: `e2e/test_datetime_field_e2e.py`

**Interfaces:**
- Consumes: everything above, through the real add-session page.

- [ ] **Step 1: Write the new bug-repro test** (append; module already imports `dt`, `ZoneInfo`, `Game`, `Session`, `UserPreferences`, `_login`, `_select_first_game`, `_fill_segments`, `START_FIELD`)

```python
def test_typed_wall_clock_means_the_picked_zone(
    browser: Browser, live_server, django_user_model
):
    """The reverse-engineered check for the reported bug: account zone Prague,
    zone picker flipped to Tokyo, typed 15:37 → the stored instant must be
    06:37 UTC (15:37 Tokyo), not 13:37 UTC (15:37 Prague)."""
    user = django_user_model.objects.create_user(
        username="tester", password="secret123"
    )
    UserPreferences.objects.create(user=user, display_time_zone="Europe/Prague")
    Game.objects.create(name="Alpha Game")
    # Browser pinned to the account zone: the capture default stamps Prague,
    # so the flip to Tokyo below is a deliberate user act, as in the report.
    context = browser.new_context(timezone_id="Europe/Prague")
    try:
        page = context.new_page()
        _login(page, live_server)
        page.goto(f"{live_server.url}{reverse('games:add_session')}")
        _select_first_game(page)
        # Digits first, zone second — the order that exercises the live
        # reinterpretation, not just encode-at-typing-time.
        _fill_segments(
            page,
            START_FIELD,
            {"year": "2026", "month": "07", "day": "28", "hour": "15", "minute": "37"},
        )
        start_zone_row = page.locator(
            'time-zone-row[field-name="timestamp_start_timezone"]'
        )
        start_zone_row.locator('button[aria-haspopup="dialog"]').click()
        start_zone_row.locator("input[data-search-select-search]").fill("Tokyo")
        start_zone_row.locator(
            '[data-search-select-option][data-value="Asia/Tokyo"]'
        ).click()
        expect(
            page.locator(f"{START_FIELD} input[data-date-time-hidden]")
        ).to_have_value("2026-07-28T15:37:00.000000+09:00")

        with page.expect_navigation():
            page.get_by_role("button", name="Submit", exact=True).click()

        session = Session.objects.get()
        assert session.timestamp_start_timezone == "Asia/Tokyo"
        assert session.timestamp_start == dt.datetime(2026, 7, 28, 6, 37, tzinfo=dt.UTC)
        assert session.timestamp_start != dt.datetime(
            2026, 7, 28, 13, 37, tzinfo=dt.UTC
        ), "digits were interpreted in the account zone, not the picked zone"
    finally:
        context.close()
```

(If the option locator misses, check the option shape the timezone search API emits — `e2e/test_time_zone_row_e2e.py` and `games/api.py` show the `data-value` convention; adjust the selector, not the assertion.)

- [ ] **Step 2: Write the load-time divergence test — no zone interaction at all** (append)

Every other test in this file pins the browser to the account's zone and diverges by a manual pick. This one starts diverged, which is the moment the capture default announces a zone that no field has yet heard about: in a real browser that announce happens during the row's own upgrade, so it is the exact path that breaks if `date-time-field.ts` ever imports `time-zone-row.js` and inverts their registration order. No vitest can see that; only a real page load can.

```python
def test_capture_default_makes_typed_digits_mean_the_browser_zone(
    browser: Browser, live_server, django_user_model
):
    """Browser in Tokyo, account in Prague, and the zone picker never touched:
    the capture default alone must make the typed 15:37 a Tokyo wall clock
    (06:37 UTC), not a Prague one (13:37 UTC)."""
    user = django_user_model.objects.create_user(
        username="tester", password="secret123"
    )
    UserPreferences.objects.create(user=user, display_time_zone="Europe/Prague")
    Game.objects.create(name="Alpha Game")
    context = browser.new_context(timezone_id="Asia/Tokyo")
    try:
        page = context.new_page()
        _login(page, live_server)
        page.goto(f"{live_server.url}{reverse('games:add_session')}")
        _select_first_game(page)
        # Not one click on the zone picker below this line.
        _fill_segments(
            page,
            START_FIELD,
            {"year": "2026", "month": "07", "day": "28", "hour": "15", "minute": "37"},
        )
        expect(
            page.locator(f"{START_FIELD} input[data-date-time-hidden]")
        ).to_have_value("2026-07-28T15:37:00.000000+09:00")

        with page.expect_navigation():
            page.get_by_role("button", name="Submit", exact=True).click()

        session = Session.objects.get()
        assert session.timestamp_start_timezone == "Asia/Tokyo"
        assert session.timestamp_start == dt.datetime(2026, 7, 28, 6, 37, tzinfo=dt.UTC)
        assert session.timestamp_start != dt.datetime(
            2026, 7, 28, 13, 37, tzinfo=dt.UTC
        ), "the capture default's zone never reached the datetime field"
    finally:
        context.close()
```

- [ ] **Step 3: Pin the browser zone in `test_typed_session_timestamp_persists_as_the_instant_it_shows`**

The test currently uses the default `page` fixture, whose browser zone is the host machine's — and the add form's capture default now makes that zone the meaning of the typed digits. Rewrite it to a pinned context (same body, new harness):

```python
def test_typed_session_timestamp_persists_as_the_instant_it_shows(
    browser: Browser, live_server, django_user_model
):
    """Browser pinned to the account zone, so the capture default stamps
    Europe/Prague and the typed digits mean exactly what they show."""
    user = django_user_model.objects.create_user(
        username="tester", password="secret123"
    )
    UserPreferences.objects.create(user=user, display_time_zone="Europe/Prague")
    Game.objects.create(name="Alpha Game")
    context = browser.new_context(timezone_id="Europe/Prague")
    try:
        page = context.new_page()
        _login(page, live_server)
        page.goto(f"{live_server.url}{reverse('games:add_session')}")
        _select_first_game(page)
        # The field is seeded with "now"; retype it wholesale.
        _fill_segments(
            page,
            START_FIELD,
            {"year": "2026", "month": "03", "day": "15", "hour": "14", "minute": "30"},
        )

        with page.expect_navigation():
            page.get_by_role("button", name="Submit", exact=True).click()

        session = Session.objects.get()
        # 14:30 in Prague on 2026-03-15 is CET (+01:00).
        assert session.timestamp_start == dt.datetime(
            2026, 3, 15, 13, 30, tzinfo=dt.UTC
        )
    finally:
        context.close()
```

- [ ] **Step 4: Flip the "Now" test to the selected zone**

Replace `test_now_writes_the_account_wall_clock` wholesale (its old expectation is now wrong by design — see locked decision 3):

```python
@pytest.mark.usefixtures("account_in_kiritimati")
def test_now_writes_the_selected_zones_wall_clock(browser: Browser, live_server):
    """The add form's capture default selects the *browser* zone, so "Now"
    writes the browser's wall clock with the browser zone's offset — the pair
    that names the true current instant. The account's wall clock (a full day
    away here) with that offset would be an instant the user never meant."""
    context = browser.new_context(timezone_id=BROWSER_TIME_ZONE)
    try:
        page = context.new_page()
        _login(page, live_server)
        page.goto(f"{live_server.url}{reverse('games:add_session')}")
        hidden = page.locator(f"{START_FIELD} input[data-date-time-hidden]")
        expect(hidden).to_be_attached()

        page.locator(f"{START_FIELD} [data-date-picker-calendar-toggle]").click()
        page.locator(f"{START_FIELD} [data-date-range-now]").click()
        expect(hidden).not_to_have_value("")

        written = dt.datetime.fromisoformat(hidden.input_value())
        assert written.utcoffset() is not None, "Now must commit offset-qualified"
        # The digits are the selected (browser) zone's wall clock…
        wall_clock = written.replace(tzinfo=None)
        browser_now = dt.datetime.now(ZoneInfo(BROWSER_TIME_ZONE)).replace(tzinfo=None)
        assert abs(wall_clock - browser_now) < dt.timedelta(minutes=2)
        # …and digits + offset together name the actual current instant.
        assert abs(written - dt.datetime.now(dt.UTC)) < dt.timedelta(minutes=2)
    finally:
        context.close()
```

Also update the module docstring's line about "the timezone guard that issue #535 added": it now reads e.g. "…and Now/copy semantics under per-timestamp zones."

- [ ] **Step 5: Run the e2e file**

Run: `make test-e2e ARGS="-k 'datetime_field'"` — note `ARGS` appends to `pytest e2e/`, so use `-k`; never run while `make dev` is up.
Expected: PASS, including `test_editing_a_session_without_touching_it_keeps_its_microseconds` (NULL zone → display zone, unchanged) and the untouched copy/calendar tests.

- [ ] **Step 6: Commit**

```bash
git add e2e/test_datetime_field_e2e.py
git commit -m "test: e2e proof that typed digits mean the picked session zone"
```

---

### Task 8: Full verification gate

**Files:** none new.

- [ ] **Step 1: Rebuild assets and run the whole gate**

Run: `make ts && make check`
Expected: green across lint, format-check, mypy, ts-check, vitest, and the entire pytest suite including `e2e/` — pay attention to `e2e/test_time_zone_row_e2e.py` (its capture-default submit test asserts only the stored zone, so it must stay green) and `tests/test_session_timezone_form.py`.

- [ ] **Step 2: Fix anything red, re-run until green.** Do not gate on a subset.

- [ ] **Step 3: Commit any fixups**

```bash
git add -A
git commit -m "fix: green make check for datetime-field zone following"
```

---

## Self-Review

- **Spec coverage:** (1) live zone-following for typed digits → Tasks 4+6, e2e Task 7. (2) edit form renders the stored zone's wall clock → Task 2 (`_wire_value` via resolver; NULL → display zone pinned by the pre-existing ambiguous-DST test). (3) reinterpretation-not-reprojection, with the precise "what re-renders" answer → locked decision 2 + the crux vitest in Task 6. (4) DST gap/ambiguity per current zone → Task 4 (client gap → bare wall clock) + Task 3 (server gap/ambiguity in the selected zone). (5) Now + copy recommendations, implemented → locked decisions 3/4, Tasks 5/6/7. (6) test coverage at all three levels → Tasks 1-7. (7) `make check` gate → Task 8.
- **Placeholder scan:** the two "reuse the file's existing helpers" notes (Task 5 test fixture, Task 6 row-test mount) are deliberate deference to harnesses this plan quotes the shape of, with full assertion code given; no TBD/TODO steps remain.
- **Type consistency:** `zone_or_none` (Tasks 1→2→3), `zone_resolver: Callable[[], ZoneInfo] | None` (Tasks 2→3), `resolveZone?: () => string | null` (Tasks 4→6), `nowInPresentationZone(timeZoneOverride: string | null = null)` (Tasks 5→6), `TIME_ZONE_ROW_CHANGE_EVENT`/`TimeZoneRowChangeDetail` (Task 6 both halves), `zone_field_name`/`zoneFieldName` (Tasks 2→6) — all match.

## Self-review round 2 (post adversarial-review fixes)

A two-agent adversarial review (verify-against-the-real-code + find-defects) found real defects. Each is folded into the tasks above; this section records what changed and re-runs the checks over the edited plan.

**1. What changed, and why**

1. **The cross-import that would have silently un-fixed the whole plan is gone (Task 6).** Round 1 had `date-time-field.ts` import the event contract from `time-zone-row.js`. An imported module's body is evaluated *before* the importing module's, so `customElements.define("time-zone-row", …)` would have run first: every `<time-zone-row>` on the page upgrades, stamps its capture default and announces it, all before any `<date-time-field>` exists to have subscribed — the announce dropped on the floor on every real page load, which is exactly the bug this plan exists to fix. The contract now lives in a new neutral module `ts/elements/time-zone-row-events.ts` (Task 6, Step 0) with no `customElements.define`, no DOM and no imports of its own; `time-zone-row.ts`, `date-time-field.ts` and both `.test.ts` files import it, and neither element imports the other. The false claim that "`date-time-field.js` already pulls this module in" is deleted — it was never true; `date-time-field.test.ts` now carries an explicit `import "./time-zone-row.js"` side-effect line to register the real row for its own fixtures.
2. **The document-level listener is removed on disconnect (Task 6, `date-time-field.ts`).** The repo's own convention (stated in `ts/elements/presets.ts`, followed by `filter-count.ts`, `filter-builder.ts`, `filter-summary.ts`, `selection-fields.ts`) is that a `document.addEventListener` in `connectedCallback` must be undone in `disconnectedCallback`. The handler is now a `handleZoneRowChange` class field and a new `disconnectedCallback` removes it; a vitest case removes the field from the DOM, fires another zone change, and asserts its detached hidden input did not move. The step tells the implementer to check for a pre-existing `disconnectedCallback` and merge rather than declare a second (there is none today).
3. **`time-zone-row` gets the re-entry guard it never had (Task 6, Step 3).** `TimeZoneRowElement` has no `initialized` flag, so each reconnect stacked another `search-select:change` listener — an idempotent label rewrite today, but N announces per pick once `announceZone` exists, hence N re-encodes in every following field. Guarded exactly like `DateTimeFieldElement`, with a vitest case asserting one pick after a reconnect emits exactly one event.
4. **Mismatch emphasis is recomputed on every pick, not only at connect (Task 6, Step 3).** `EMPHASIS_CLASS` was decided once in `connectedCallback`, so it went stale both ways: bold survived a pick of the browser's own zone, and never appeared when the user picked a genuinely different one — the single case the cue exists for. Extracted into `updateEmphasis(trigger, effectiveZone)` (a `classList.toggle`), called from the connect-time check and from the end of the `search-select:change` handler with the new effective zone. Two vitest cases pin both directions.
5. **"Now" against an unknown override zone says so (Task 5).** `nowInPresentationZone` reported with `{ toast: false }` and returned `null`, and the field's handler is `if (!now) return;` — a button click that did visibly nothing. The `toast` option is now `timeZoneOverride !== null`, so only the override branch (the one with a click waiting on it) toasts; the contract-zone branch keeps its quiet degrade.
6. **The codec's new zone fallback reports (Task 4).** Its `catch` was the only silent degrade in this area. It now calls `reportClientError("date-time-codec", String(error), { toast: false })` before returning the bare wall clock. Verified against the real code: `date-time-codec.ts` imports nothing from `client-errors.js` today (the import must be added) and `errorDetail` is module-private to `date-time-presentation.ts` and **not** exported — `String(error)` is what `quick-filter-bar.ts` and `filter-group.ts` already pass. The codec test file gains a `vi.mock("../client-errors.js", …)` and asserts the report.
7. **Two broken test harnesses fixed.** (a) Task 5's cases used `vi.setSystemTime`, which `Temporal.Now` does not read, and skipped `installConfig` in a block whose `beforeEach` strips the contract attribute — so one would have failed outright and the other passed vacuously. Both are rewritten in the block's own idiom: `installConfig(alteredConfig(…))` with a `Pacific/Kiritimati` (+14) contract, then an offset-delta assertion via `Temporal.PlainDateTime.from(value).since(Temporal.Now.plainDateTimeISO("UTC"))` reading +09 for an `Asia/Tokyo` override. (b) Task 6's `zoneRowMarkup` fixture had no trigger button, and `time-zone-row.connectedCallback` returns early without one — every field test built on `mountWithZoneRow` was structurally incapable of exercising the announce path, leaving only the synthetic `changeZone()` dispatch tested. The fixture now carries the real anatomy (hidden `[data-time-zone-value]` + `button[aria-haspopup="dialog"]` with a leading text node), copied from `time-zone-row.test.ts`'s own `mount()`.
8. **A jsdom test and an e2e test now cover the load-time path, not just the manual one.** New Task 6 case: a pre-filled field plus a `capture-default="true"` row with an empty value, browser zone stubbed to Tokyo, and the hidden input must land on `+09:00` with no `changeZone()` call — the announce reaching the field end to end. jsdom cannot reproduce cross-module ES evaluation order, so it is necessary but not sufficient; the sufficient half is new Task 7 Step 2, `test_capture_default_makes_typed_digits_mean_the_browser_zone`: browser pinned to `Asia/Tokyo`, account `Europe/Prague`, zone picker never touched, submit, assert `06:37 UTC`. Both existing e2e tests pin browser zone == account zone and diverge only by a manual pick, so neither could ever have caught fix 1. Task 7's later steps renumbered to 3–6 accordingly.
9. **The edit-form zone question is recorded as a decision, not a gap.** The review flagged that the edit form shows the session's own zone regardless of `SESSION_TIME_ZONE_DISPLAY`; confirmed intentional with the user and appended as locked decision 7.

**2. Placeholder scan** — still clean. Task 6 Step 0 is a complete new file; every new test case above is full assertion code. Three deliberate "copy the real helper" notes remain, each naming the exact source to copy from: `stubBrowserZone` (from `time-zone-row.test.ts`), `zoneRowMarkup`'s anatomy (same file's `mount()`), and the e2e option-row selector (`e2e/test_time_zone_row_e2e.py`). Two "check the real file first" instructions are intentional guards against drift: the `disconnectedCallback` merge check, and the `client-errors.js` import shape in the codec.

**3. Type and name consistency across every file this plan touches**

- `TIME_ZONE_ROW_CHANGE_EVENT` (`const`, `"time-zone-row:change"`) and `TimeZoneRowChangeDetail { fieldName: string; zone: string }` are declared in exactly one place, `ts/elements/time-zone-row-events.ts`, and imported from `"./time-zone-row-events.js"` in exactly four: `time-zone-row.ts` (both, the type for the `CustomEvent<…>` generic), `date-time-field.ts` (both), `time-zone-row.test.ts` (the constant), `date-time-field.test.ts` (the constant). No file imports either name from `"./time-zone-row.js"`; the only `"./time-zone-row.js"` import left in the plan is `date-time-field.test.ts`'s bare side-effect line.
- `handleZoneRowChange: ((event: Event) => void) | null` — one field, set in `connectedCallback`, nulled in `disconnectedCallback`.
- `updateEmphasis(trigger: HTMLElement, effectiveZone: string): void` and `announceZone(fieldName: string, zone: string): void` — both private to `TimeZoneRowElement`, both called from the connect path and the `search-select:change` handler; `EMPHASIS_CLASS` and `browserTimeZone()` are the file's existing members, unrenamed.
- `nowInPresentationZone(timeZoneOverride: string | null = null): string | null` — one signature, called with the row's zone (or `null`) from `date-time-field.ts`, mocked as `vi.fn<(timeZoneOverride?: string | null) => string | null>()` in the field tests.
- `reportClientError(context, detail, { toast })` — `"date-time-codec"` context in the codec (new import from `"../client-errors.js"`), `"date-time-presentation"` context in the formatter (existing import), `toast` boolean in both.
- Unchanged from round 1 and re-verified against the edited snippets: `zone_or_none`, `zone_resolver: Callable[[], ZoneInfo] | None`, `resolveZone?: () => string | null`, `zone_field_name`/`zoneFieldName`.
