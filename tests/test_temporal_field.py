import json
from datetime import date
from types import SimpleNamespace

import pytest
from django.core import serializers
from django.core.exceptions import ValidationError
from django.db import DatabaseError, NotSupportedError, connection, models, transaction
from django.test.utils import isolate_apps

from timetracker.temporal import (
    TemporalEndKind,
    TemporalEndPrecision,
    TemporalEndQualifier,
    TemporalKind,
    TemporalLowerBound,
    TemporalPrecisionValue,
    TemporalQualifierValue,
    TemporalStartKind,
    TemporalStartPrecision,
    TemporalStartQualifier,
    TemporalUpperBound,
    TemporalValue,
    TemporalValueField,
    temporal_exact_day_q,
    temporal_has_known_day_q,
    temporal_has_known_month_q,
    temporal_has_known_year_q,
    temporal_is_approximate_q,
    temporal_is_uncertain_q,
)


def test_temporal_field_has_fixed_portable_migration_contract():
    field = TemporalValueField()
    _, path, args, kwargs = field.deconstruct()

    assert path == "timetracker.temporal.TemporalValueField"
    assert args == []
    assert kwargs == {
        "blank": False,
        "default": None,
        "editable": False,
        "max_length": 64,
        "null": True,
    }
    with pytest.raises(ValueError, match="fixed at 64"):
        TemporalValueField(max_length=63)
    with pytest.raises(NotSupportedError, match="PostgreSQL"):
        field.db_type(SimpleNamespace(vendor="sqlite"))
    assert field.db_type(SimpleNamespace(vendor="postgresql")) == "temporal_value"


def test_temporal_field_converts_and_prepares_only_canonical_scalars():
    field = TemporalValueField()
    value = TemporalValue.parse("2024-02")

    assert field.to_python(value) is value
    assert field.to_python("2024-02") == value
    assert field.to_python(None) is None
    assert field.to_python(TemporalValue.unknown()) is None
    assert field.get_prep_value(value) == "2024-02"
    assert field.get_prep_value("2024-02") == "2024-02"
    assert field.get_prep_value(None) is None
    assert field.get_prep_value(TemporalValue.unknown()) is None

    with pytest.raises(ValidationError) as caught:
        field.to_python("2024??")
    assert caught.value.code == "invalid_qualifier"
    assert "%" in caught.value.messages[0]


@pytest.mark.parametrize(
    ("helper", "precisions"),
    [
        (temporal_has_known_year_q, ("day", "month", "year")),
        (temporal_has_known_month_q, ("day", "month")),
        (temporal_has_known_day_q, ("day",)),
    ],
)
def test_temporal_component_query_helpers_own_precision_semantics(helper, precisions):
    assert helper("released") == models.Q(
        released_kind="atomic", released_precision__in=precisions
    )
    assert helper("released", endpoint="start") == models.Q(
        released_start_kind="known", released_start_precision__in=precisions
    )
    assert helper("released", endpoint="end") == models.Q(
        released_end_kind="known", released_end_precision__in=precisions
    )


def test_temporal_query_helpers_reject_ambiguous_requests():
    assert temporal_exact_day_q("released") == models.Q(
        released_kind="atomic", released_precision="day"
    )
    with pytest.raises(ValueError, match="start.*end"):
        temporal_has_known_year_q("released", endpoint="middle")
    with pytest.raises(ValueError, match="field name"):
        temporal_has_known_year_q("")
    with pytest.raises(TypeError):
        temporal_exact_day_q("released", endpoint="start")


@pytest.mark.django_db(transaction=True)
@isolate_apps("games")
def test_temporal_field_round_trips_generated_projections_and_query_helpers():
    class Probe(models.Model):
        value = TemporalValueField()
        value_lower = models.GeneratedField(
            expression=TemporalLowerBound("value"),
            output_field=models.DateField(null=True),
            db_persist=True,
        )
        value_upper = models.GeneratedField(
            expression=TemporalUpperBound("value"),
            output_field=models.DateField(null=True),
            db_persist=True,
        )
        value_kind = models.GeneratedField(
            expression=TemporalKind("value"),
            output_field=models.CharField(max_length=7),
            db_persist=True,
        )
        value_precision = models.GeneratedField(
            expression=TemporalPrecisionValue("value"),
            output_field=models.CharField(max_length=7, null=True),
            db_persist=True,
        )
        value_start_kind = models.GeneratedField(
            expression=TemporalStartKind("value"),
            output_field=models.CharField(max_length=7, null=True),
            db_persist=True,
        )
        value_end_kind = models.GeneratedField(
            expression=TemporalEndKind("value"),
            output_field=models.CharField(max_length=7, null=True),
            db_persist=True,
        )
        value_start_precision = models.GeneratedField(
            expression=TemporalStartPrecision("value"),
            output_field=models.CharField(max_length=7, null=True),
            db_persist=True,
        )
        value_end_precision = models.GeneratedField(
            expression=TemporalEndPrecision("value"),
            output_field=models.CharField(max_length=7, null=True),
            db_persist=True,
        )

        class Meta:
            app_label = "games"
            db_table = "test_temporal_probe"

    with connection.schema_editor() as schema_editor:
        schema_editor.create_model(Probe)

    try:
        fresh = Probe()
        assert fresh.value is None
        fresh.full_clean()

        direct = Probe(value="2024-02")
        direct.full_clean()
        assert direct.value == TemporalValue.parse("2024-02")

        with pytest.raises(ValidationError) as caught:
            Probe(value="").full_clean()
        assert caught.value.error_dict["value"][0].code == "invalid_syntax"

        created = Probe.objects.create(value="2000")
        created.refresh_from_db()
        assert created.value == TemporalValue.parse("2000")
        created.value = TemporalValue.parse("2001")
        created.save(update_fields=["value"])
        created.refresh_from_db()
        assert created.value == TemporalValue.parse("2001")
        created.delete()

        rows = Probe.objects.bulk_create(
            [
                Probe(value="2024-02-29"),
                Probe(value="2024-02"),
                Probe(value="2024"),
                Probe(value="199X"),
                Probe(value="../2001-03"),
                Probe(value="/2001-03"),
                Probe(value="1999/.."),
                Probe(value=None),
            ]
        )
        loaded = list(Probe.objects.order_by("pk"))
        assert [row.value.serialize() if row.value else None for row in loaded] == [
            "2024-02-29",
            "2024-02",
            "2024",
            "199X",
            "../2001-03",
            "/2001-03",
            "1999/..",
            None,
        ]
        assert (
            loaded[0].value_lower,
            loaded[0].value_upper,
            loaded[0].value_kind,
            loaded[0].value_precision,
        ) == (date(2024, 2, 29), date(2024, 2, 29), "atomic", "day")
        assert (
            loaded[4].value_lower,
            loaded[4].value_upper,
            loaded[4].value_start_kind,
            loaded[4].value_end_kind,
            loaded[4].value_end_precision,
        ) == (None, date(2001, 3, 31), "open", "known", "month")
        assert loaded[5].value_start_kind == "unknown"
        assert loaded[7].value_kind == "unknown"

        assert Probe.objects.filter(value=TemporalValue.parse("2024-02")).count() == 1
        assert Probe.objects.filter(value=TemporalValue.unknown()).count() == 1
        assert Probe.objects.filter(value=None).count() == 1
        assert Probe.objects.filter(temporal_has_known_year_q("value")).count() == 3
        assert Probe.objects.filter(temporal_has_known_month_q("value")).count() == 2
        assert Probe.objects.filter(temporal_has_known_day_q("value")).count() == 1
        assert Probe.objects.filter(temporal_exact_day_q("value")).count() == 1
        assert (
            Probe.objects.filter(
                temporal_has_known_month_q("value", endpoint="end")
            ).count()
            == 2
        )

        helper_sql = str(
            Probe.objects.filter(temporal_has_known_month_q("value")).query
        )
        assert "value_kind" in helper_sql
        assert "value_precision" in helper_sql
        assert "timetracker_temporal_" not in helper_sql

        rows[1].value = TemporalValue.parse("2025-03-01")
        Probe.objects.bulk_update([rows[1]], ["value"])
        Probe.objects.filter(pk=rows[2].pk).update(value="2026-04")
        assert Probe.objects.get(pk=rows[1].pk).value == TemporalValue.parse(
            "2025-03-01"
        )
        assert Probe.objects.get(pk=rows[2].pk).value == TemporalValue.parse("2026-04")

        serialized = json.loads(serializers.serialize("json", [loaded[0], loaded[7]]))
        assert serialized[0]["fields"]["value"] == "2024-02-29"
        assert serialized[1]["fields"]["value"] is None

        with (
            pytest.raises(DatabaseError),
            transaction.atomic(),
            connection.cursor() as cursor,
        ):
            cursor.execute(
                'INSERT INTO "test_temporal_probe" ("value") VALUES (%s)',
                ["2024??"],
            )
    finally:
        with connection.schema_editor() as schema_editor:
            schema_editor.delete_model(Probe)


@pytest.mark.parametrize(
    ("helper", "qualifiers"),
    [
        (temporal_is_approximate_q, ("approximate", "both")),
        (temporal_is_uncertain_q, ("uncertain", "both")),
    ],
)
def test_temporal_qualifier_query_helpers_carry_the_kind_guard(helper, qualifiers):
    assert helper("released") == models.Q(
        released_kind="atomic", released_qualifier__in=qualifiers
    )
    assert helper("released", endpoint="start") == models.Q(
        released_start_kind="known", released_start_qualifier__in=qualifiers
    )
    assert helper("released", endpoint="end") == models.Q(
        released_end_kind="known", released_end_qualifier__in=qualifiers
    )

    with pytest.raises(ValueError, match="start.*end"):
        helper("released", endpoint="middle")
    with pytest.raises(ValueError, match="field name"):
        helper("")


@pytest.mark.django_db(transaction=True)
@isolate_apps("games")
def test_temporal_qualifier_helpers_select_the_rows_they_name():
    class QualifierProbe(models.Model):
        value = TemporalValueField()
        value_kind = models.GeneratedField(
            expression=TemporalKind("value"),
            output_field=models.CharField(max_length=7),
            db_persist=True,
        )
        value_start_kind = models.GeneratedField(
            expression=TemporalStartKind("value"),
            output_field=models.CharField(max_length=7, null=True),
            db_persist=True,
        )
        value_end_kind = models.GeneratedField(
            expression=TemporalEndKind("value"),
            output_field=models.CharField(max_length=7, null=True),
            db_persist=True,
        )
        value_qualifier = models.GeneratedField(
            expression=TemporalQualifierValue("value"),
            output_field=models.CharField(max_length=11, null=True),
            db_persist=True,
        )
        value_start_qualifier = models.GeneratedField(
            expression=TemporalStartQualifier("value"),
            output_field=models.CharField(max_length=11, null=True),
            db_persist=True,
        )
        value_end_qualifier = models.GeneratedField(
            expression=TemporalEndQualifier("value"),
            output_field=models.CharField(max_length=11, null=True),
            db_persist=True,
        )

        class Meta:
            app_label = "games"
            db_table = "test_temporal_qualifier_probe"

    with connection.schema_editor() as schema_editor:
        schema_editor.create_model(QualifierProbe)
    try:
        for canonical in ("1984", "1984~", "1984?", "1984%", "1984~/1986?", None):
            QualifierProbe.objects.create(value=TemporalValue.parse(canonical))

        def canonicals(condition):
            return sorted(
                row.value.canonical for row in QualifierProbe.objects.filter(condition)
            )

        assert canonicals(temporal_is_approximate_q("value")) == ["1984%", "1984~"]
        assert canonicals(temporal_is_uncertain_q("value")) == ["1984%", "1984?"]
        assert canonicals(temporal_is_approximate_q("value", endpoint="start")) == [
            "1984~/1986?"
        ]
        assert canonicals(temporal_is_uncertain_q("value", endpoint="end")) == [
            "1984~/1986?"
        ]
        assert canonicals(temporal_is_approximate_q("value", endpoint="end")) == []
    finally:
        with connection.schema_editor() as schema_editor:
            schema_editor.delete_model(QualifierProbe)
