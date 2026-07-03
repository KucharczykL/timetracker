# Cross-model field comparison + comparison spaces (#169) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Field-comparison rows can traverse one forward to-one FK (`game__year_released`) and compare in a declared space (`raw`/`date`/`year`), with strict both-operands-non-NULL semantics.

**Architecture:** Extend `FieldComparisonCriterion` operands to one-hop FK paths validated against introspected forward FKs; widen `granularity` into a comparison-space model where `year` projects temporal operands to numbers via `ExtractYear`; add explicit NULL guards so all modifiers are strict two-valued and side-symmetric. UI packs (modifier × space) into the operator dropdown and groups column selects by per-FK `<optgroup>`.

**Tech Stack:** Django 6 ORM (`F`, `TruncDate`, `ExtractYear`), Python components (`common/components`), TypeScript custom elements, vitest + pytest + Playwright.

**Spec:** `docs/superpowers/specs/2026-07-03-issue-169-cross-model-field-comparison-design.md` — read it first; it records every decision and its rationale.

## Global Constraints

- Run every command via `direnv exec .` (Nix dev shell): `direnv exec . uv run pytest …`, `direnv exec . make ts`, etc.
- Final gate before PR: `direnv exec . make check` green (includes e2e).
- Complete-word identifiers (`operand`, not `op`) per CLAUDE.md.
- Never write to `GeneratedField`s.
- `make gen-element-types` after changing `ComparableColumn`; never hand-edit `ts/generated/*`.
- JSON leaf shape stays `{left, right, modifier, granularity?}`; `granularity` emitted only when ≠ `"raw"`.
- Commit messages: conventional commits, reference `#169`.

---

### Task 1: Comparison spaces — type + parse + validation

**Files:**
- Modify: `common/criteria.py:736` (`ComparisonGranularity`), `common/criteria.py:803-811` (`from_json`), `common/criteria.py:1349-1378` (`_apply_operators` validation)
- Test: `tests/test_filters.py` (extend `TestFieldComparisonWiring` area)

**Interfaces:**
- Produces: `type ComparisonGranularity = Literal["raw", "date", "year"]`; module constant `_SPACE_GROUPS: dict[str, frozenset[ComparisonGroup]]`; validation accepting cross-group pairs inside a space. Consumed by Tasks 2-4.

- [ ] **Step 1: Write failing tests** — in `tests/test_filters.py`, next to the existing field-comparison wiring tests:

```python
class TestComparisonSpaces:
    def test_year_space_accepts_two_datetimes(self):
        filter_object = SessionFilter(
            field_comparisons=[
                FieldComparisonCriterion(
                    left="timestamp_start", right="timestamp_end",
                    modifier=Modifier.EQUALS, granularity="year",
                )
            ]
        )
        filter_object.to_q()  # must not raise

    def test_date_space_accepts_date_vs_datetime(self):
        # PlayEvent.started is a DateField, created_at a DateTimeField
        filter_object = PlayEventFilter(
            field_comparisons=[
                FieldComparisonCriterion(
                    left="started", right="created_at",
                    modifier=Modifier.EQUALS, granularity="date",
                )
            ]
        )
        filter_object.to_q()

    def test_raw_space_keeps_same_group_rule(self):
        filter_object = PlayEventFilter(
            field_comparisons=[
                FieldComparisonCriterion(
                    left="started", right="created_at", modifier=Modifier.EQUALS,
                )
            ]
        )
        with pytest.raises(FilterError, match="cannot compare"):
            filter_object.to_q()

    def test_year_space_rejects_string_operand(self):
        filter_object = SessionFilter(
            field_comparisons=[
                FieldComparisonCriterion(
                    left="note", right="timestamp_start",
                    modifier=Modifier.EQUALS, granularity="year",
                )
            ]
        )
        with pytest.raises(FilterError, match="year"):
            filter_object.to_q()

    def test_non_raw_space_rejects_containment_modifiers(self):
        filter_object = SessionFilter(
            field_comparisons=[
                FieldComparisonCriterion(
                    left="timestamp_start", right="timestamp_end",
                    modifier=Modifier.INCLUDES, granularity="year",
                )
            ]
        )
        with pytest.raises(FilterError, match="not allowed"):
            filter_object.to_q()

    def test_from_json_accepts_year_granularity(self):
        parsed = FieldComparisonCriterion.from_json(
            {"left": "timestamp_start", "right": "timestamp_end",
             "modifier": "EQUALS", "granularity": "year"}
        )
        assert parsed is not None and parsed.granularity == "year"

    def test_from_json_rejects_unknown_granularity(self):
        with pytest.raises(FilterError, match="unknown granularity"):
            FieldComparisonCriterion.from_json(
                {"left": "a", "right": "b", "modifier": "EQUALS",
                 "granularity": "month"}
            )

    def test_year_granularity_roundtrips_json(self):
        criterion = FieldComparisonCriterion(
            left="timestamp_start", right="timestamp_end",
            modifier=Modifier.EQUALS, granularity="year",
        )
        assert criterion.to_json()["granularity"] == "year"
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `direnv exec . uv run pytest tests/test_filters.py::TestComparisonSpaces -v`
Expected: FAIL (`granularity="year"` rejected by `from_json`/validation).

- [ ] **Step 3: Implement.** In `common/criteria.py`:

```python
type ComparisonGranularity = Literal["raw", "date", "year"]

# Comparison spaces (#169): the operand groups each non-raw granularity accepts.
# "raw" is special-cased in _apply_operators (both operands must share a group).
# In "date" space datetime operands are projected to calendar dates; in "year"
# space temporal operands are projected to their year and compared as numbers.
_SPACE_GROUPS: dict[ComparisonGranularity, frozenset[ComparisonGroup]] = {
    "date": frozenset({"date", "datetime"}),
    "year": frozenset({"date", "datetime", "number"}),
}
```

`from_json` (line ~809): `("raw", "date")` → `("raw", "date", "year")`.

Replace the group/modifier/granularity checks inside `_apply_operators` (lines 1361-1377):

```python
                left_group = _comparison_group_for(model, comparison.left)
                right_group = _comparison_group_for(model, comparison.right)
                if comparison.granularity == "raw":
                    if left_group != right_group:
                        raise FilterError(
                            f"cannot compare {comparison.left!r} ({left_group})"
                            f" to {comparison.right!r} ({right_group})"
                        )
                    allowed_modifiers = _allowed_comparison_modifiers(left_group)
                else:
                    accepted_groups = _SPACE_GROUPS[comparison.granularity]
                    for operand, group in (
                        (comparison.left, left_group),
                        (comparison.right, right_group),
                    ):
                        if group not in accepted_groups:
                            raise FilterError(
                                f"{operand!r} ({group}) cannot take part in a"
                                f" {comparison.granularity}-granularity comparison"
                            )
                    allowed_modifiers = Modifier.for_ordered_field_comparisons()
                if comparison.modifier not in allowed_modifiers:
                    raise FilterError(
                        f"modifier {comparison.modifier} not allowed"
                        f" for this comparison"
                    )
```

(The old `granularity == "date" and left_group != "datetime"` check is subsumed:
`date` space now legitimately accepts `date` operands too.)

- [ ] **Step 4: Run tests, verify pass** — same command, plus the existing suite: `direnv exec . uv run pytest tests/test_filters.py -v -k "Comparison or field_comparison or FieldComparison"`
Note: existing tests asserting "date-granular comparison needs datetime operands" will fail — update them to the new rule (date space accepts date+datetime; a string operand in date space is the new error).

- [ ] **Step 5: Commit** — `feat(filters): comparison spaces — granularity "year" + space-aware validation (#169)`

---

### Task 2: `to_q` — space projection + strict NULL guards

**Files:**
- Modify: `common/criteria.py:1723-1766` (`_field_comparison_to_q`), `common/criteria.py:784-789` (`FieldComparisonCriterion.to_q`), `common/criteria.py:1378` (call site), `common/criteria.py:741-772` (docstring rewrite)
- Test: `tests/test_filters.py` (`TestFieldComparisonCriterion`, `TestFieldComparisonEndToEnd`)

**Interfaces:**
- Consumes: `_SPACE_GROUPS`, groups resolved in `_apply_operators` (Task 1).
- Produces: `_field_comparison_to_q(left, right, modifier, granularity, *, left_group, right_group) -> Q`. `FieldComparisonCriterion.to_q()` now raises `RuntimeError` (needs model context; the only builder is `_apply_operators`). Task 3 relies on the same function accepting path operands unchanged.

- [ ] **Step 1: Write failing tests**

```python
class TestStrictNullSemantics:
    """#169: a row matches only if BOTH operands are non-NULL — every modifier,
    either side. Kills the raw-ORM asymmetry (A≠B vs B≠A) and supersedes the
    old NULL-counts-as-not-equal same-model behavior."""

    @pytest.fixture
    def session_without_game(self, db):
        return Session.objects.create(
            timestamp_start=timezone.now(), note="orphan", game=None,
        )

    def test_not_equals_excludes_null_operand_rows_lookup_side(
        self, session_without_game
    ):
        q = SessionFilter(
            field_comparisons=[
                FieldComparisonCriterion(
                    left="game__name", right="note", modifier=Modifier.NOT_EQUALS,
                )
            ]
        ).to_q()
        assert session_without_game not in Session.objects.filter(q)

    def test_not_equals_excludes_null_operand_rows_expression_side(
        self, session_without_game
    ):
        q = SessionFilter(
            field_comparisons=[
                FieldComparisonCriterion(
                    left="note", right="game__name", modifier=Modifier.NOT_EQUALS,
                )
            ]
        ).to_q()
        assert session_without_game not in Session.objects.filter(q)

    def test_not_equals_is_side_symmetric(self, db, game, session_without_game):
        matching = Session.objects.create(
            timestamp_start=timezone.now(), note="differs", game=game,
        )
        left_form = SessionFilter(field_comparisons=[FieldComparisonCriterion(
            left="game__name", right="note", modifier=Modifier.NOT_EQUALS)]).to_q()
        right_form = SessionFilter(field_comparisons=[FieldComparisonCriterion(
            left="note", right="game__name", modifier=Modifier.NOT_EQUALS)]).to_q()
        assert list(Session.objects.filter(left_form)) == list(
            Session.objects.filter(right_form)
        )

    def test_same_model_not_equals_now_excludes_null_rows(self, db):
        # Behavior change pinned: previously included (NULL counted as "not equal").
        session = Session.objects.create(
            timestamp_start=timezone.now(), timestamp_end=None,
        )
        q = SessionFilter(field_comparisons=[FieldComparisonCriterion(
            left="timestamp_end", right="timestamp_start",
            modifier=Modifier.NOT_EQUALS)]).to_q()
        assert session not in Session.objects.filter(q)


class TestYearProjection:
    def test_year_space_headline_example(self, db):
        # Session started in the game's release year — the #169 headline query.
        game = Game.objects.create(name="Doom", year_released=2020)
        hit = Session.objects.create(
            game=game, timestamp_start=datetime(2020, 6, 1, tzinfo=UTC),
        )
        miss = Session.objects.create(
            game=game, timestamp_start=datetime(2021, 6, 1, tzinfo=UTC),
        )
        q = SessionFilter(field_comparisons=[FieldComparisonCriterion(
            left="timestamp_start", right="game__year_released",
            modifier=Modifier.EQUALS, granularity="year")]).to_q()
        results = Session.objects.filter(q)
        assert hit in results and miss not in results

    def test_year_space_number_left_temporal_right(self, db):
        # Symmetric: number on the lookup side, temporal behind F().
        game = Game.objects.create(name="Doom", year_released=2020)
        hit = Session.objects.create(
            game=game, timestamp_start=datetime(2020, 6, 1, tzinfo=UTC),
        )
        q = SessionFilter(field_comparisons=[FieldComparisonCriterion(
            left="game__year_released", right="timestamp_start",
            modifier=Modifier.EQUALS, granularity="year")]).to_q()
        assert hit in Session.objects.filter(q)
```

Also rewrite `TestFieldComparisonCriterion`'s direct-call tests to call
`_field_comparison_to_q(left, right, modifier, granularity, left_group=..., right_group=...)`
and assert the guard structure, e.g.:

```python
def test_equals_includes_null_guards(self):
    q = _field_comparison_to_q(
        "timestamp_start", "timestamp_end", Modifier.EQUALS, "raw",
        left_group="datetime", right_group="datetime",
    )
    assert str(q).count("isnull") == 2
```

- [ ] **Step 2: Run, verify fail** — `direnv exec . uv run pytest tests/test_filters.py::TestStrictNullSemantics tests/test_filters.py::TestYearProjection -v`

- [ ] **Step 3: Implement.**

```python
from django.db.models.functions import ExtractYear, TruncDate  # ExtractYear is new


def _field_comparison_to_q(
    left: str,
    right: str,
    modifier: Modifier,
    granularity: ComparisonGranularity = "raw",
    *,
    left_group: ComparisonGroup,
    right_group: ComparisonGroup,
) -> Q:
    """Build a Q comparing two operands: ``left <op> right`` in the row's space.

    Operands may be one-hop relation paths (``game__year_released``); the ORM
    joins for a lookup path on the left and for ``F("relation__column")`` on the
    right, and both operands on one relation share a single join.

    Space projection: ``date`` truncates datetime operands to calendar day
    (``__date`` / ``TruncDate``), ``year`` extracts the year from temporal
    operands (``__year`` / ``ExtractYear``) so they compare against numbers.

    NULL semantics are strict two-valued (#169): every Q carries explicit
    ``__isnull=False`` guards on both operand paths, so a row matches only when
    both operands exist and the predicate holds — for every modifier, on either
    side. This is deliberately independent of Django's declared-nullability
    guard injection (which is asymmetric for join-introduced NULLs) and
    supersedes the previous NULL-counts-as-not-equal NOT_EQUALS behavior.
    """
    temporal_groups = ("date", "datetime")
    left_base = left
    right_expr: F | TruncDate | ExtractYear = F(right)
    if granularity == "date":
        if left_group == "datetime":
            left_base = f"{left}__date"
        if right_group == "datetime":
            right_expr = TruncDate(F(right))
    elif granularity == "year":
        if left_group in temporal_groups:
            left_base = f"{left}__year"
        if right_group in temporal_groups:
            right_expr = ExtractYear(F(right))

    guards = Q(**{f"{left}__isnull": False}) & Q(**{f"{right}__isnull": False})
    if modifier == Modifier.EQUALS:
        return Q(**{left_base: right_expr}) & guards
    if modifier == Modifier.NOT_EQUALS:
        return ~Q(**{left_base: right_expr}) & guards
    if modifier == Modifier.GREATER_THAN:
        return Q(**{f"{left_base}__gt": right_expr}) & guards
    if modifier == Modifier.LESS_THAN:
        return Q(**{f"{left_base}__lt": right_expr}) & guards
    if modifier == Modifier.GREATER_THAN_OR_EQUAL:
        return Q(**{f"{left_base}__gte": right_expr}) & guards
    if modifier == Modifier.LESS_THAN_OR_EQUAL:
        return Q(**{f"{left_base}__lte": right_expr}) & guards
    if modifier == Modifier.INCLUDES:
        return Q(**{f"{left_base}__icontains": right_expr}) & guards
    if modifier == Modifier.EXCLUDES:
        return ~Q(**{f"{left_base}__icontains": right_expr}) & guards
    raise FilterError(f"Unsupported modifier {modifier} for field comparison")
```

`FieldComparisonCriterion.to_q` (it cannot know the model, and groups are
required now):

```python
    def to_q(self, field_name: str = "") -> Q:
        # Static mis-wiring, never user input: comparisons are built by
        # OperatorFilter._apply_operators, which resolves operand groups
        # against the filter's model first.
        raise RuntimeError(
            "FieldComparisonCriterion.to_q needs model context;"
            " build it via OperatorFilter._apply_operators"
        )
```

Call site in `_apply_operators` (was `q &= comparison.to_q()`):

```python
                q &= _field_comparison_to_q(
                    comparison.left,
                    comparison.right,
                    comparison.modifier,
                    comparison.granularity,
                    left_group=left_group,
                    right_group=right_group,
                )
```

Rewrite the `FieldComparisonCriterion` class docstring: delete the old NULL
truth-table paragraphs (lines 747-766) and describe strict semantics + spaces
(the `_field_comparison_to_q` docstring above is the model). Keep the
empty-string INCLUDES caveat (still true for `""` values, which are not NULL).

Grep for other callers first: `grep -rn "comparison.to_q\|\.to_q()" common/ games/ | grep -i comparison` — update any stragglers.

- [ ] **Step 4: Run, verify pass** — `direnv exec . uv run pytest tests/test_filters.py -v` (full file: the old NULL-semantics tests in `TestFieldComparisonEndToEnd` asserting inclusion of NULL rows for NOT_EQUALS must be updated to strict expectations; `str(q)`-shape tests gain the guard terms).

- [ ] **Step 5: Commit** — `feat(filters): space projection + strict two-valued NULL semantics for field comparisons (#169)`

---

### Task 3: Path operands — grammar + validation

**Files:**
- Modify: `common/criteria.py` (new `ComparisonOperand` alias + `_comparison_operand_group`; use it in `_apply_operators`; `left`/`right` field annotations)
- Test: `tests/test_filters.py`

**Interfaces:**
- Produces: `type ComparisonOperand = str  # own column "playtime" or one-hop FK path "game__year_released"`; `_comparison_operand_group(model, operand, *, side) -> ComparisonGroup`. Consumed by Task 4 (`comparable_columns`) for the same FK-acceptance rule via `_comparison_relations`.

- [ ] **Step 1: Write failing tests**

```python
class TestComparisonOperandPaths:
    def test_fk_path_resolves_related_group(self):
        assert _comparison_operand_group(Session, "game__year_released", side="left") == "number"

    def test_own_column_still_resolves(self):
        assert _comparison_operand_group(Session, "note", side="left") == "string"

    def test_m2m_path_rejected(self):
        with pytest.raises(FilterError, match="games"):
            _comparison_operand_group(Purchase, "games__name", side="left")

    def test_reverse_accessor_rejected(self):
        with pytest.raises(FilterError, match="session"):
            _comparison_operand_group(Game, "session__note", side="right")

    def test_two_hop_rejected(self):
        with pytest.raises(FilterError, match="game__platform__name"):
            _comparison_operand_group(Session, "game__platform__name", side="left")

    def test_unknown_relation_names_path_and_side(self):
        with pytest.raises(FilterError, match=r"right operand.*'nonexistent__name'"):
            _comparison_operand_group(Session, "nonexistent__name", side="right")

    def test_unknown_related_column_names_full_path(self):
        with pytest.raises(FilterError, match="game__nonexistent"):
            _comparison_operand_group(Session, "game__nonexistent", side="left")

    def test_cross_model_wiring_end_to_end(self, db):
        # Purchase name contains its base game's name (the DLC-naming check).
        game = Game.objects.create(name="Doom")
        dlc = Purchase.objects.create(
            name="Doom: Eternal DLC", related_game=game, ...,
        )
        q = PurchaseFilter(field_comparisons=[FieldComparisonCriterion(
            left="name", right="related_game__name",
            modifier=Modifier.INCLUDES)]).to_q()
        assert dlc in Purchase.objects.filter(q)

    def test_shared_join_for_both_side_paths(self, db):
        q = GameFilter(field_comparisons=[FieldComparisonCriterion(
            left="platform__name", right="platform__group",
            modifier=Modifier.EQUALS)]).to_q()
        sql = str(Game.objects.filter(q).query)
        assert sql.count("JOIN") == 1
```

(Adapt the `Purchase.objects.create` required fields to the existing test factories/fixtures in the file.)

- [ ] **Step 2: Run, verify fail** — `direnv exec . uv run pytest tests/test_filters.py::TestComparisonOperandPaths -v`
Expected: FAIL — `_comparison_group_for(Session, "game__year_released")` raises "Session has no field".

- [ ] **Step 3: Implement.** Next to `_comparison_group_for`:

```python
type ComparisonOperand = str  # own column "playtime" or one-hop FK path "game__year_released"


def _comparison_operand_group(
    model: type[models.Model], operand: ComparisonOperand, *, side: str
) -> ComparisonGroup:
    """Resolve a comparison operand to its group, enforcing the operand grammar.

    Grammar (#169): a bare comparable column, or exactly one forward to-one FK
    hop (``relation__column``). M2M and reverse relations are rejected — ``F()``
    across a multi-valued relation fans out rows (see the spec's follow-up
    issue for Exists()-based semantics). Terminal classification is delegated
    to ``_comparison_group_for`` against the related model, so type-group
    gating and its error vocabulary stay single-sourced. ``side`` ("left"/
    "right") only decorates error messages.
    """
    segments = operand.split("__")
    if len(segments) == 1:
        return _comparison_group_for(model, operand)
    if len(segments) > 2:
        raise FilterError(
            f"{side} operand {operand!r} traverses more than one relation"
            f" (one hop allowed)"
        )
    relation, column = segments
    try:
        relation_field = model._meta.get_field(relation)
    except FieldDoesNotExist as exc:
        raise FilterError(
            f"{side} operand {operand!r}: {model.__name__}"
            f" has no relation {relation!r}"
        ) from exc
    if not isinstance(relation_field, (models.ForeignKey, models.OneToOneField)):
        raise FilterError(
            f"{side} operand {operand!r}: {model.__name__}.{relation}"
            f" is not a to-one relation (only forward FK hops are comparable)"
        )
    try:
        return _comparison_group_for(relation_field.related_model, column)
    except FilterError as exc:
        raise FilterError(f"{side} operand {operand!r}: {exc}") from exc
```

In `_apply_operators`, replace the two `_comparison_group_for(model, …)` calls
(Task 1's code) with:

```python
                left_group = _comparison_operand_group(
                    model, comparison.left, side="left"
                )
                right_group = _comparison_operand_group(
                    model, comparison.right, side="right"
                )
```

Annotate `FieldComparisonCriterion.left/right` as `ComparisonOperand` and note
`isinstance(relation_field, models.ForeignKey)` covers `OneToOneField` (a
subclass) — keep both spelled out for the reader.

- [ ] **Step 4: Run, verify pass** — `direnv exec . uv run pytest tests/test_filters.py -v -k "Operand or FieldComparison or Comparison"` then the whole file.

- [ ] **Step 5: Commit** — `feat(filters): one-hop FK path operands for field comparisons (#169)`

---

### Task 4: `comparable_columns` — related columns + `source` discriminator

**Files:**
- Modify: `common/criteria.py:1839-1879` (`ComparableColumn`, `comparable_columns`, new `_comparison_relations`)
- Modify: `ts/generated/filter-metadata.ts` via `direnv exec . make gen-element-types` (never by hand)
- Test: `tests/test_filters.py::TestComparableColumns`

**Interfaces:**
- Consumes: nothing new.
- Produces: `ComparableColumn` gains `source: str` (`""` for own columns, else the FK's title-cased `verbose_name`); related entries have `value=f"{fk_name}__{column}"` and label `f"{source}: {column_label}"`. Tasks 5-7 render/filter on `source`; summary chips consume the pre-qualified `label`.

- [ ] **Step 1: Write failing tests**

```python
class TestComparableColumnsCrossModel:
    def test_session_includes_game_and_device_columns(self):
        columns = comparable_columns(Session)
        values = {column["value"] for column in columns}
        assert "game__year_released" in values
        assert "device__name" in values

    def test_purchase_includes_both_fk_sources(self):
        # Purchase has TWO forward FKs: platform and related_game.
        sources = {c["source"] for c in comparable_columns(Purchase)}
        assert "" in sources  # own columns
        assert len(sources) >= 3

    def test_related_labels_are_qualified_and_own_labels_bare(self):
        columns = comparable_columns(Session)
        by_value = {column["value"]: column for column in columns}
        assert by_value["note"]["source"] == ""
        assert ": " not in by_value["note"]["label"]
        related = by_value["game__year_released"]
        assert related["source"] and related["label"].startswith(related["source"])

    def test_own_columns_first_then_relation_blocks(self):
        columns = comparable_columns(Session)
        sources = [column["source"] for column in columns]
        assert sources == sorted(sources, key=lambda s: (s != "", ))  # "" block first
        own_labels = [c["label"] for c in columns if c["source"] == ""]
        assert own_labels == sorted(own_labels, key=str.lower)

    def test_m2m_and_reverse_not_enumerated(self):
        purchase_values = {c["value"] for c in comparable_columns(Purchase)}
        assert not any(v.startswith("games__") for v in purchase_values)
        game_values = {c["value"] for c in comparable_columns(Game)}
        assert not any(v.startswith("session__") for v in game_values)

    def test_platform_and_device_have_no_related_columns(self):
        for model in (Platform, Device):
            assert all(c["source"] == "" for c in comparable_columns(model))
```

- [ ] **Step 2: Run, verify fail** — `direnv exec . uv run pytest tests/test_filters.py::TestComparableColumnsCrossModel -v`

- [ ] **Step 3: Implement.**

```python
class ComparableColumn(TypedDict):
    """A comparison-operand option, ready for a picker: operand value, human
    label, comparison group, allowed raw-space operators, and the source
    optgroup it renders under."""

    value: ComparisonOperand  # "timestamp_end" or "game__year_released"
    label: str  # own: "Timestamp End"; related: "Base Game: Year Released"
    group: ComparisonGroup
    operators: list[ModifierValue]  # valid for this column's group, raw space (#152)
    source: str  # optgroup label: "" own columns, else the FK's verbose name


def _comparison_relations(
    model: type[models.Model],
) -> list[tuple[str, type[models.Model], str]]:
    """The forward to-one FKs comparison operands may traverse, introspected
    (never configured): ``(fk_name, related_model, title-cased verbose name)``
    per concrete ForeignKey/OneToOneField, in ``_meta`` declaration order.
    The same acceptance rule ``_comparison_operand_group`` validates against."""
    relations: list[tuple[str, type[models.Model], str]] = []
    for model_field in model._meta.get_fields():
        if (
            isinstance(model_field, (models.ForeignKey, models.OneToOneField))
            and model_field.concrete
            and model_field.related_model is not None
        ):
            relations.append(
                (
                    model_field.name,
                    model_field.related_model,
                    str(model_field.verbose_name).title(),
                )
            )
    return relations
```

Rework `comparable_columns`: extract the current per-model loop into a helper
`_own_comparable_columns(model, *, prefix="", source="")` that builds entries
(label qualified as `f"{source}: {label}"` when `source`), sorts by label; then:

```python
def comparable_columns(model: type[models.Model]) -> list[ComparableColumn]:
    columns = _own_comparable_columns(model)
    for fk_name, related_model, source in _comparison_relations(model):
        columns.extend(
            _own_comparable_columns(related_model, prefix=f"{fk_name}__", source=source)
        )
    return columns
```

(Own block sorted alphabetically, then one sorted block per FK in declaration
order — no global re-sort.)

Run `direnv exec . make gen-element-types` and commit the regenerated
`ts/generated/filter-metadata.ts` (adds `source: string` to the TS interface).

- [ ] **Step 4: Run, verify pass** — `direnv exec . uv run pytest tests/test_filters.py -v` and `direnv exec . make ts-check` (new field is additive; existing TS ignores it).

- [ ] **Step 5: Commit** — `feat(filters): enumerate related-model comparison columns with per-FK sources (#169)`

---

### Task 5: Widget server side — optgroups + packed operator prefill, checkbox removed

**Files:**
- Modify: `common/components/primitives.py` (whitelist `Optgroup`), `common/components/__init__.py` (export)
- Modify: `common/components/filters.py:750-935` (`_fc_row_from_dict`, `_fc_column_options`, `_field_comparison_row`)
- Test: `tests/test_filter_bars.py` (`FieldComparisonWidgetTest`)

**Interfaces:**
- Consumes: `ComparableColumn.source` (Task 4).
- Produces: left select markup `<optgroup label="…"><option value="game__year_released" data-group="number">…`; operator select `data-selected` now holds the packed token `modifier` (raw) or `modifier:granularity`; the day-granular checkbox is gone. Task 6's TS reads exactly these.

- [ ] **Step 1: Write failing tests** (rendered-HTML assertions in `tests/test_filter_bars.py`, following the existing `FieldComparisonWidgetTest` style):

```python
def test_left_select_groups_related_options_by_source(self):
    html = str(FieldComparisonSet(columns=comparable_columns(Session), rows=[], mode="AND"))
    # Own columns stay top-level (source == ""); related sources get optgroups.
    assert "<optgroup" in html
    assert 'value="game__year_released"' in html
    own_option_position = html.index('value="note"')
    first_optgroup_position = html.index("<optgroup")
    assert own_option_position < first_optgroup_position

def test_saved_year_row_prefills_packed_operator(self):
    row = FieldComparisonRow(
        left="timestamp_start", right="game__year_released",
        modifier="EQUALS", granularity="year",
    )
    html = str(FieldComparisonSet(columns=comparable_columns(Session), rows=[row], mode="AND"))
    assert 'data-selected="EQUALS:year"' in html

def test_raw_row_prefills_bare_modifier(self):
    row = FieldComparisonRow(left="a", right="b", modifier="LESS_THAN", granularity="raw")
    html = str(FieldComparisonSet(columns=comparable_columns(Session), rows=[row], mode="AND"))
    assert 'data-selected="LESS_THAN"' in html

def test_day_granular_checkbox_gone(self):
    html = str(FieldComparisonSet(columns=comparable_columns(Session), rows=[], mode="AND"))
    assert "data-fc-granularity" not in html
```

- [ ] **Step 2: Run, verify fail** — `direnv exec . uv run pytest tests/test_filter_bars.py -v -k FieldComparison`

- [ ] **Step 3: Implement.**

`primitives.py`: add `"optgroup"` to the generated-builder whitelist →
`Optgroup = _html_element("optgroup")`; export from `common/components/__init__.py`.

`filters.py`:

```python
def _pack_operator(modifier: str, granularity: str) -> str:
    """The operator <select> value: bare modifier in raw space, else
    ``modifier:granularity`` — mirrored by unpackOperator in
    ts/elements/field-comparison-set.ts."""
    return modifier if granularity == "raw" else f"{modifier}:{granularity}"


def _fc_column_options(columns: list[ComparableColumn], selected: str) -> list[Node]:
    """Left-column options, one <optgroup> per source. The bar model's own
    columns (source == "") render under the model's own name — callers pass
    columns from comparable_columns, whose own-block comes first."""
    options: list[Node] = [Option(value="")["column…"]]
    grouped: dict[str, list[ComparableColumn]] = {}
    for column in columns:
        grouped.setdefault(column["source"], []).append(column)
    for source, members in grouped.items():
        member_options: list[Node] = []
        for column in members:
            attributes = [("value", column["value"]), ("data-group", column["group"])]
            if column["value"] == selected:
                attributes.append(("selected", ""))
            member_options.append(Option(attributes)[column["label"]])
        if source == "":
            options.extend(member_options)
        else:
            options.append(Optgroup(label=source)[member_options])
    return options
```

(Own columns stay top-level ungrouped options — matches mockup B; only related
sources get optgroups. `label` is already source-qualified for related entries,
so the collapsed select stays readable.)

`_field_comparison_row`: delete the whole `Label(...)` granularity block and
its `granularity_date` local; change
`operator_value = row.modifier if row else ""` to
`operator_value = _pack_operator(row.modifier, row.granularity) if row else ""`;
drop the now-unused grid column (`md:grid-cols-[1fr_auto_1fr_auto_auto]` →
`md:grid-cols-[1fr_auto_1fr_auto]`).

`_fc_row_from_dict` granularity parse:
`"date" if raw.get("granularity") == "date" else "raw"` →

```python
        granularity=(
            raw["granularity"]
            if raw.get("granularity") in ("date", "year")
            else "raw"
        ),
```

- [ ] **Step 4: Run, verify pass** — `direnv exec . uv run pytest tests/test_filter_bars.py tests/test_components.py -v`

- [ ] **Step 5: Commit** — `feat(filters): optgroup column pickers + packed operator prefill in comparison rows (#169)`

---

### Task 6: Widget TS — packed operators, space-aware right list, optgroup fillSelect

**Files:**
- Modify: `ts/elements/field-comparison-set.ts`, `ts/elements/filter-tree/types.ts:45-57`
- Check: `ts/elements/filter-group.ts` (nested-builder comparison-leaf wiring — it calls `refreshRow`/`readComparisonRow`; make sure the operator-change listener lands where BOTH consumers get it)
- Test: `ts/elements/field-comparison-set.test.ts` (create if absent — vitest, happy-dom per existing `ts/**/*.test.ts` conventions), `ts/elements/filter-tree/operations.test.ts`

**Interfaces:**
- Consumes: markup + packed `data-selected` from Task 5; `SPACE_GROUPS` knowledge duplicated nowhere — derive from the codegen'd `ComparableColumn` data plus one local constant mirroring `_SPACE_GROUPS` (see step 3 note).
- Produces: `unpackOperator(value): {modifier, granularity}`; `refreshRow` fills operator optgroups per space and right list per (group, space); `readComparisonRow` emits `granularity: "date" | "year"`. `ComparisonRow.granularity?: "date" | "year"`.

- [ ] **Step 1: Write failing vitest tests** (DOM-level, building the row markup the server emits):

```typescript
import { describe, expect, it } from "vitest";
import { readComparisonRow, refreshRow, unpackOperator } from "./field-comparison-set.js";

const COLUMNS = [
  { value: "timestamp_start", label: "Timestamp Start", group: "datetime", operators: ORDERED, source: "" },
  { value: "timestamp_end", label: "Timestamp End", group: "datetime", operators: ORDERED, source: "" },
  { value: "note", label: "Note", group: "string", operators: STRING_OPERATORS, source: "" },
  { value: "game__year_released", label: "Game: Year Released", group: "number", operators: ORDERED, source: "Game" },
];

describe("unpackOperator", () => {
  it("bare modifier is raw space", () => {
    expect(unpackOperator("EQUALS")).toEqual({ modifier: "EQUALS", granularity: "raw" });
  });
  it("suffixed modifier carries its space", () => {
    expect(unpackOperator("LESS_THAN:year")).toEqual({ modifier: "LESS_THAN", granularity: "year" });
  });
});

describe("refreshRow with a datetime left operand", () => {
  it("offers raw, date and year operator groups", () => {
    const row = buildRow("timestamp_start", "", "");
    refreshRow(row, COLUMNS);
    const groups = [...row.querySelectorAll("[data-fc-op] optgroup")].map((g) => g.label);
    expect(groups).toEqual(["By date", "By year"]);  // raw options are top-level
  });
  it("year-space operator admits number columns on the right", () => {
    const row = buildRow("timestamp_start", "EQUALS:year", "");
    refreshRow(row, COLUMNS);
    const values = [...row.querySelectorAll("[data-fc-right] option")].map((o) => o.value);
    expect(values).toContain("game__year_released");
  });
  it("raw operator keeps the right list same-group", () => {
    const row = buildRow("timestamp_start", "EQUALS", "");
    refreshRow(row, COLUMNS);
    const values = [...row.querySelectorAll("[data-fc-right] option")].map((o) => o.value);
    expect(values).not.toContain("game__year_released");
    expect(values).toContain("timestamp_end");
  });
});

describe("readComparisonRow", () => {
  it("emits year granularity from a packed operator", () => {
    const row = buildRow("timestamp_start", "EQUALS:year", "game__year_released");
    refreshRow(row, COLUMNS);
    expect(readComparisonRow(row)).toEqual({
      left: "timestamp_start", right: "game__year_released",
      modifier: "EQUALS", granularity: "year",
    });
  });
  it("omits granularity in raw space", () => {
    const row = buildRow("timestamp_start", "LESS_THAN", "timestamp_end");
    refreshRow(row, COLUMNS);
    expect(readComparisonRow(row)).toEqual({
      left: "timestamp_start", right: "timestamp_end", modifier: "LESS_THAN",
    });
  });
});
```

(`buildRow(left, operatorSelected, rightSelected)` helper constructs the Task-5
markup: three selects with `data-fc-left/op/right`, `data-selected` attributes,
left options with `data-group`.)

- [ ] **Step 2: Run, verify fail** — `direnv exec . make test-ts`

- [ ] **Step 3: Implement** in `field-comparison-set.ts`:

```typescript
import type { ComparableColumn, ComparisonGroup } from "../generated/filter-metadata.js";

// Mirrors _SPACE_GROUPS in common/criteria.py — the operand groups each
// non-raw space accepts. Two entries; if this grows, move it into the
// gen-element-types codegen next to ComparableColumn.
const SPACE_GROUPS: Record<"date" | "year", ComparisonGroup[]> = {
  date: ["date", "datetime"],
  year: ["date", "datetime", "number"],
};
const SPACE_HEADERS: Record<"date" | "year", string> = {
  date: "By date",
  year: "By year",
};
const ORDERED_MODIFIERS = [
  "EQUALS", "NOT_EQUALS", "GREATER_THAN", "LESS_THAN",
  "GREATER_THAN_OR_EQUAL", "LESS_THAN_OR_EQUAL",
];

export type Granularity = "raw" | "date" | "year";

export function packOperator(modifier: string, granularity: Granularity): string {
  return granularity === "raw" ? modifier : `${modifier}:${granularity}`;
}

export function unpackOperator(value: string): { modifier: string; granularity: Granularity } {
  const [modifier, granularity] = value.split(":");
  return {
    modifier,
    granularity: granularity === "date" || granularity === "year" ? granularity : "raw",
  };
}
```

Rework `fillSelect` to accept grouped options
(`{ header: string | null; options: [string, string][] }[]`), emitting
`<optgroup>` for non-null headers, keeping the placeholder blank option and
`selected` restore; skip groups whose option list is empty.

`refreshRow` changes:
1. Operator options: raw group first (left group's `operators` with existing
   glyph labels, top-level), then per space where
   `SPACE_GROUPS[space].includes(group)`, an optgroup `SPACE_HEADERS[space]`
   with `ORDERED_MODIFIERS` packed values (`packOperator(modifier, space)`) and
   labels `` `${OPERATOR_LABELS[modifier] ?? modifier} (${SPACE_HEADERS[space].toLowerCase()})` ``.
2. Right list: `const { granularity } = unpackOperator(operator.value)`;
   allowed groups = `granularity === "raw" ? [group] : SPACE_GROUPS[granularity]`;
   filter columns by allowed groups (and `column.value !== left.value`),
   grouped into optgroups by `column.source` (own `""` block top-level).
3. Delete the granularity-checkbox show/hide block.
4. `wireRow`: add `operator.addEventListener("change", () => refreshRowRightList(...))`
   — extract the right-list rebuild so an operator change re-filters the right
   list while preserving a still-valid selection. **Check `filter-group.ts`'s
   comparison-leaf wiring**: if it wires rows itself (not via `wireRow`),
   export the wiring helper and use it there too, so the nested builder gets
   the operator listener.

`readComparisonRow`:

```typescript
  const { modifier, granularity } = unpackOperator(operatorValue);
  if (!left || !right || !modifier || left === right) return null;
  const entry: ComparisonRow = { left, right, modifier };
  if (granularity !== "raw") entry.granularity = granularity;
  return entry;
```

`types.ts`: `granularity?: "date" | "year";` (update the comment: "date or year
comparison space; omitted → raw").

- [ ] **Step 4: Run, verify pass** — `direnv exec . make test-ts && direnv exec . make ts-check`

- [ ] **Step 5: Commit** — `feat(filters): space-aware comparison widget — packed operators, optgroup pickers (#169)`

---

### Task 7: Summary chips — spaces + qualified labels

**Files:**
- Modify: `ts/elements/filter-tree/summary.ts:129-137` (`renderComparison`)
- Test: `ts/elements/filter-tree/summary.test.ts`

**Interfaces:**
- Consumes: `ComparisonRow.granularity` (Task 6); `SummaryModel.columns` map — values are the pre-qualified labels from Task 4 (no `filter-summary.ts` change needed: it already copies `column.label` into the map).

- [ ] **Step 1: Write failing tests** in `summary.test.ts` (existing patterns):

```typescript
it("renders a year-space comparison with its suffix", () => {
  // model.columns seeded with value→label incl. "game__year_released" → "Game: Year Released"
  expect(render(comparisonLeaf({
    left: "timestamp_start", right: "game__year_released",
    modifier: "EQUALS", granularity: "year",
  }), model)).toBe("Timestamp Start = Game: Year Released (by year)");
});

it("falls back to the raw path when the column map misses it", () => {
  expect(render(comparisonLeaf({
    left: "game__nonexistent", right: "note", modifier: "EQUALS",
  }), model)).toContain("game__nonexistent");
});
```

- [ ] **Step 2: Run, verify fail** — `direnv exec . make test-ts`

- [ ] **Step 3: Implement** — in `renderComparison`:

```typescript
  const suffix =
    granularity === "date" ? " (by date)" : granularity === "year" ? " (by year)" : "";
```

(The existing " (by day)" wording changes to " (by date)" for consistency with
the widget's "By date" optgroup — update any test pinning "(by day)".)

- [ ] **Step 4: Run, verify pass** — `direnv exec . make test-ts`

- [ ] **Step 5: Commit** — `feat(filters): summary chips render comparison spaces and qualified labels (#169)`

---

### Task 8: Cross-language contract fixtures

**Files:**
- Modify: `ts/elements/filter-tree/fixtures.json` (new cases + `registry`), `tests/test_filter_tree_contract.py:26` (`FILTER_FOR_MODEL`)
- Test: the contract itself (`ts/elements/filter-tree/serializer.test.ts` writes `fixtures.canonical.json`; `tests/test_filter_tree_contract.py` asserts `to_q()` equivalence)

**Interfaces:**
- Consumes: everything above (Python `to_q` must parse the new shapes).

- [ ] **Step 1: Add fixture cases** (following the existing case shape in `fixtures.json`):
  - session: `{left: "timestamp_start", right: "game__year_released", modifier: "EQUALS", granularity: "year"}`
  - session: both-sides paths `{left: "game__name", right: "device__name", modifier: "EQUALS"}` (two string columns via two different FKs, raw space)
  - purchase: `{left: "name", right: "related_game__name", modifier: "INCLUDES"}`
  - playevent: date space `{left: "started", right: "created_at", modifier: "EQUALS", granularity: "date"}` (date-vs-datetime, newly legal)

  Add `"purchase": PurchaseFilter` (and `"playevent": PlayEventFilter` if used) to `FILTER_FOR_MODEL` and the fixtures `registry` per its existing format.

- [ ] **Step 2: Run both sides** —
`direnv exec . make test-ts` (regenerates `fixtures.canonical.json`), then
`direnv exec . uv run pytest tests/test_filter_tree_contract.py -v`
Expected: PASS both.

- [ ] **Step 3: Commit** — `test(filters): contract fixtures for path operands and comparison spaces (#169)`

---

### Task 9: e2e — update bar widget test, add builder-page cross-model case

**Files:**
- Modify: `e2e/test_field_comparison_e2e.py` (selects restructured: checkbox gone, packed operator values, optgroups)
- Modify: `e2e/test_filter_builder_e2e.py` (new case)

**Interfaces:**
- Consumes: the full stack. Run against real Chromium via `live_server`.

- [ ] **Step 1: Update `test_field_comparison_e2e.py`** — wherever it toggles `[data-fc-granularity]`, select the packed operator instead (`select_option(value="EQUALS:date")`); assertions about the day-granular checkbox are deleted.

- [ ] **Step 2: Add builder-page case** (adapting the file's existing helpers/fixtures):

```python
def test_cross_model_year_comparison_filters_sessions(page, live_server, ...):
    # Data: one session in its game's release year, one outside it.
    ...
    page.goto(f"{live_server.url}/sessions/")
    # open the comparison row, pick operands:
    page.select_option("[data-fc-left]", "timestamp_start")
    page.select_option("[data-fc-op]", "EQUALS:year")
    page.select_option("[data-fc-right]", "game__year_released")
    # apply, assert exactly the in-year session row remains
    ...
```

- [ ] **Step 3: Run** — `direnv exec . uv run pytest e2e/test_field_comparison_e2e.py e2e/test_filter_builder_e2e.py -v`
Expected: PASS.

- [ ] **Step 4: Commit** — `test(e2e): cross-model + space comparison coverage (#169)`

---

### Task 10: Full gate + PR + follow-up issues

- [ ] **Step 1:** `direnv exec . make check` — green, no subset shortcuts.
- [ ] **Step 2:** Push branch, open PR against `main` titled
`feat(filters): cross-model field comparison + comparison spaces (#169)`; body summarizes: path operands (one forward-FK hop), spaces (raw/date/year), strict NULL semantics (behavior change for same-model NOT_EQUALS — called out explicitly), UI packing; link the spec file; `Closes #169`.
- [ ] **Step 3: File follow-up issues** (gh):
  1. "Field comparison: multi-valued relation operands (M2M/reverse) via Exists()" — carries the "session vs its game's finish date" example from #169; reference the spec section.
  2. "Audit FK verbose_names as comparison optgroup labels" — only if Task 4 review showed awkward labels not fixed inline.
- [ ] **Step 4:** After merge: reap local+remote branch (post-merge cleanup).

---

## Self-review notes (spec→plan coverage)

- Spec "Operand grammar" → Task 3; "Comparison spaces" → Task 1; "Q construction + NULL" → Task 2; "Column enumeration" → Task 4; "UI" → Tasks 5-6; "Summary chips" → Task 7 (no `filter-summary.ts` change — labels pre-qualified in Task 4, simpler than spec's two-file description); "Contract" → Task 8; "Testing/e2e" → Tasks 1-9; "Follow-ups" → Task 10.
- `MAX_FIELD_COMPARISONS`, JSON shape, preset compat: untouched by design; Task 5's `_fc_row_from_dict` covers year prefill.
- Type names used consistently: `ComparisonOperand`, `_comparison_operand_group`, `_comparison_relations`, `ComparableColumn.source`, `packOperator`/`unpackOperator`, `Granularity`.
