"""The schema this app builds from nothing.

Every migration before this one had already run, in full, on every database
that exists, so their operations were replaced by the end state they produced.
Four pieces of that state no model can declare, and they are carried here as
raw SQL, quoted from the schema itself rather than rewritten:

- the ``uuid_v7`` domain, which every primary key column is typed as;
- the ``temporal_value`` domain and the seventeen functions its constraint and
  the generated bound columns call. Both domains are created ahead of the
  tables whose columns name them;
- the two generated columns that carry a temporal kind, which are declared
  non-null and which ``CREATE TABLE`` would leave nullable anyway;
- the composite foreign key that holds an event's ``stream_id`` and
  ``library_id`` against one stream head row, which Django's field layer has no
  spelling for. It is added last, after the unique constraint it references.

What a database built from this file holds is compared against what the
migrated deployment holds by ``make verify-baseline``, which is the gate on
editing it.
"""

import datetime
import uuid

import django.db.models.deletion
import django.db.models.expressions
import django.db.models.fields
import django.db.models.functions.comparison
import django.db.models.functions.text
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

import timetracker.temporal
import timetracker.uuidv7

CREATE_UUID_V7_DOMAIN = r"""
CREATE DOMAIN public.uuid_v7 AS uuid
	CONSTRAINT uuid_v7_check CHECK (((VALUE IS NULL) OR (NOT (uuid_extract_version(VALUE) IS DISTINCT FROM 7))));
""".strip()

DROP_UUID_V7_DOMAIN = "DROP DOMAIN public.uuid_v7;"

CREATE_TEMPORAL_VALUE_DOMAIN = r"""
CREATE FUNCTION public._timetracker_temporal_atom_qualifier(value text) RETURNS text
    LANGUAGE plpgsql IMMUTABLE
    SET search_path TO 'pg_catalog', 'public'
    AS $$
DECLARE
    symbol text;
    atom text;
BEGIN
    IF value IS NULL THEN
        RETURN NULL;
    END IF;
    symbol := right(value, 1);
    IF symbol IN ('?', '~', '%') THEN
        atom := left(value, -1);
    ELSE
        symbol := NULL;
        atom := value;
    END IF;
    IF atom ~ '[?~%]' THEN
        RAISE EXCEPTION 'misplaced temporal qualifier symbol: %', value;
    END IF;
    IF symbol IS NULL THEN
        RETURN NULL;
    ELSIF symbol = '?' THEN
        RETURN 'uncertain';
    ELSIF symbol = '~' THEN
        RETURN 'approximate';
    END IF;
    RETURN 'both';
END
$$;

CREATE FUNCTION public._timetracker_temporal_atom_unqualified(value text) RETURNS text
    LANGUAGE plpgsql IMMUTABLE
    SET search_path TO 'pg_catalog', 'public'
    AS $$
BEGIN
    IF value IS NOT NULL AND right(value, 1) IN ('?', '~', '%') THEN
        RETURN left(value, -1);
    END IF;
    RETURN value;
END
$$;

CREATE FUNCTION public._timetracker_temporal_atom_precision(value text) RETURNS text
    LANGUAGE plpgsql IMMUTABLE
    SET search_path TO 'pg_catalog', 'public'
    AS $_$
DECLARE
    atom text;
    year_number integer;
    month_number integer;
    day_number integer;
BEGIN
    PERFORM _timetracker_temporal_atom_qualifier(value);
    atom := _timetracker_temporal_atom_unqualified(value);
    IF atom ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$' THEN
        year_number := substring(atom FROM 1 FOR 4)::integer;
        month_number := substring(atom FROM 6 FOR 2)::integer;
        day_number := substring(atom FROM 9 FOR 2)::integer;
        PERFORM make_date(year_number, month_number, day_number);
        RETURN 'day';
    ELSIF atom ~ '^[0-9]{4}-[0-9]{2}$' THEN
        year_number := substring(atom FROM 1 FOR 4)::integer;
        month_number := substring(atom FROM 6 FOR 2)::integer;
        PERFORM make_date(year_number, month_number, 1);
        RETURN 'month';
    ELSIF atom ~ '^[0-9]{4}$' THEN
        year_number := atom::integer;
        PERFORM make_date(year_number, 1, 1);
        RETURN 'year';
    ELSIF atom ~ '^[0-9]{3}X$' THEN
        year_number := substring(atom FROM 1 FOR 3)::integer * 10;
        PERFORM make_date(year_number, 1, 1);
        PERFORM make_date(year_number + 9, 12, 31);
        RETURN 'decade';
    END IF;

    RAISE EXCEPTION 'invalid temporal atom: %', value;
END
$_$;

CREATE FUNCTION public._timetracker_temporal_atom_lower(value text) RETURNS date
    LANGUAGE plpgsql IMMUTABLE
    SET search_path TO 'pg_catalog', 'public'
    AS $$
DECLARE
    precision_name text;
    atom text;
    year_number integer;
    month_number integer;
BEGIN
    precision_name := _timetracker_temporal_atom_precision(value);
    atom := _timetracker_temporal_atom_unqualified(value);
    IF precision_name = 'day' THEN
        RETURN make_date(
            substring(atom FROM 1 FOR 4)::integer,
            substring(atom FROM 6 FOR 2)::integer,
            substring(atom FROM 9 FOR 2)::integer
        );
    ELSIF precision_name = 'month' THEN
        year_number := substring(atom FROM 1 FOR 4)::integer;
        month_number := substring(atom FROM 6 FOR 2)::integer;
        RETURN make_date(year_number, month_number, 1);
    ELSIF precision_name = 'year' THEN
        RETURN make_date(atom::integer, 1, 1);
    END IF;

    year_number := substring(atom FROM 1 FOR 3)::integer * 10;
    RETURN make_date(year_number, 1, 1);
END
$$;

CREATE FUNCTION public._timetracker_temporal_atom_upper(value text) RETURNS date
    LANGUAGE plpgsql IMMUTABLE
    SET search_path TO 'pg_catalog', 'public'
    AS $$
DECLARE
    precision_name text;
    atom text;
    year_number integer;
    month_number integer;
BEGIN
    precision_name := _timetracker_temporal_atom_precision(value);
    atom := _timetracker_temporal_atom_unqualified(value);
    IF precision_name = 'day' THEN
        RETURN make_date(
            substring(atom FROM 1 FOR 4)::integer,
            substring(atom FROM 6 FOR 2)::integer,
            substring(atom FROM 9 FOR 2)::integer
        );
    ELSIF precision_name = 'month' THEN
        year_number := substring(atom FROM 1 FOR 4)::integer;
        month_number := substring(atom FROM 6 FOR 2)::integer;
        IF month_number = 12 THEN
            RETURN make_date(year_number, 12, 31);
        END IF;
        RETURN make_date(year_number, month_number + 1, 1) - 1;
    ELSIF precision_name = 'year' THEN
        RETURN make_date(atom::integer, 12, 31);
    END IF;

    year_number := substring(atom FROM 1 FOR 3)::integer * 10;
    RETURN make_date(year_number + 9, 12, 31);
END
$$;

CREATE FUNCTION public.timetracker_temporal_kind(value text) RETURNS text
    LANGUAGE plpgsql IMMUTABLE
    SET search_path TO 'pg_catalog', 'public'
    AS $$
BEGIN
    PERFORM timetracker_temporal_lower(value);
    IF value IS NULL THEN
        RETURN 'unknown';
    ELSIF strpos(value, '/') > 0 THEN
        RETURN 'range';
    END IF;
    RETURN 'atomic';
END
$$;

CREATE FUNCTION public.timetracker_temporal_precision(value text) RETURNS text
    LANGUAGE plpgsql IMMUTABLE
    SET search_path TO 'pg_catalog', 'public'
    AS $$
BEGIN
    PERFORM timetracker_temporal_lower(value);
    IF value IS NULL OR strpos(value, '/') > 0 THEN
        RETURN NULL;
    END IF;
    RETURN _timetracker_temporal_atom_precision(value);
END
$$;

CREATE FUNCTION public.timetracker_temporal_qualifier(value text) RETURNS text
    LANGUAGE plpgsql IMMUTABLE
    SET search_path TO 'pg_catalog', 'public'
    AS $$
BEGIN
    PERFORM timetracker_temporal_lower(value);
    IF value IS NULL OR strpos(value, '/') > 0 THEN
        RETURN NULL;
    END IF;
    RETURN _timetracker_temporal_atom_qualifier(value);
END
$$;

CREATE FUNCTION public.timetracker_temporal_start_kind(value text) RETURNS text
    LANGUAGE plpgsql IMMUTABLE
    SET search_path TO 'pg_catalog', 'public'
    AS $$
DECLARE
    slash_position integer;
    endpoint_value text;
BEGIN
    PERFORM timetracker_temporal_lower(value);
    IF value IS NULL THEN
        RETURN NULL;
    END IF;
    slash_position := strpos(value, '/');
    IF slash_position = 0 THEN
        RETURN NULL;
    END IF;
    endpoint_value := substring(value FROM 1 FOR slash_position - 1);
    IF endpoint_value = '' THEN
        RETURN 'unknown';
    ELSIF endpoint_value = '..' THEN
        RETURN 'open';
    END IF;
    RETURN 'known';
END
$$;

CREATE FUNCTION public.timetracker_temporal_end_kind(value text) RETURNS text
    LANGUAGE plpgsql IMMUTABLE
    SET search_path TO 'pg_catalog', 'public'
    AS $$
DECLARE
    slash_position integer;
    endpoint_value text;
BEGIN
    PERFORM timetracker_temporal_lower(value);
    IF value IS NULL THEN
        RETURN NULL;
    END IF;
    slash_position := strpos(value, '/');
    IF slash_position = 0 THEN
        RETURN NULL;
    END IF;
    endpoint_value := substring(value FROM slash_position + 1);
    IF endpoint_value = '' THEN
        RETURN 'unknown';
    ELSIF endpoint_value = '..' THEN
        RETURN 'open';
    END IF;
    RETURN 'known';
END
$$;

CREATE FUNCTION public.timetracker_temporal_start_precision(value text) RETURNS text
    LANGUAGE plpgsql IMMUTABLE
    SET search_path TO 'pg_catalog', 'public'
    AS $$
DECLARE
    slash_position integer;
    endpoint_value text;
BEGIN
    PERFORM timetracker_temporal_lower(value);
    IF value IS NULL THEN
        RETURN NULL;
    END IF;
    slash_position := strpos(value, '/');
    IF slash_position = 0 THEN
        RETURN NULL;
    END IF;
    endpoint_value := substring(value FROM 1 FOR slash_position - 1);
    IF endpoint_value IN ('', '..') THEN
        RETURN NULL;
    END IF;
    RETURN _timetracker_temporal_atom_precision(endpoint_value);
END
$$;

CREATE FUNCTION public.timetracker_temporal_end_precision(value text) RETURNS text
    LANGUAGE plpgsql IMMUTABLE
    SET search_path TO 'pg_catalog', 'public'
    AS $$
DECLARE
    slash_position integer;
    endpoint_value text;
BEGIN
    PERFORM timetracker_temporal_lower(value);
    IF value IS NULL THEN
        RETURN NULL;
    END IF;
    slash_position := strpos(value, '/');
    IF slash_position = 0 THEN
        RETURN NULL;
    END IF;
    endpoint_value := substring(value FROM slash_position + 1);
    IF endpoint_value IN ('', '..') THEN
        RETURN NULL;
    END IF;
    RETURN _timetracker_temporal_atom_precision(endpoint_value);
END
$$;

CREATE FUNCTION public.timetracker_temporal_start_qualifier(value text) RETURNS text
    LANGUAGE plpgsql IMMUTABLE
    SET search_path TO 'pg_catalog', 'public'
    AS $$
DECLARE
    slash_position integer;
    endpoint_value text;
BEGIN
    PERFORM timetracker_temporal_lower(value);
    IF value IS NULL THEN
        RETURN NULL;
    END IF;
    slash_position := strpos(value, '/');
    IF slash_position = 0 THEN
        RETURN NULL;
    END IF;
    endpoint_value := substring(value FROM 1 FOR slash_position - 1);
    IF endpoint_value IN ('', '..') THEN
        RETURN NULL;
    END IF;
    RETURN _timetracker_temporal_atom_qualifier(endpoint_value);
END
$$;

CREATE FUNCTION public.timetracker_temporal_end_qualifier(value text) RETURNS text
    LANGUAGE plpgsql IMMUTABLE
    SET search_path TO 'pg_catalog', 'public'
    AS $$
DECLARE
    slash_position integer;
    endpoint_value text;
BEGIN
    PERFORM timetracker_temporal_lower(value);
    IF value IS NULL THEN
        RETURN NULL;
    END IF;
    slash_position := strpos(value, '/');
    IF slash_position = 0 THEN
        RETURN NULL;
    END IF;
    endpoint_value := substring(value FROM slash_position + 1);
    IF endpoint_value IN ('', '..') THEN
        RETURN NULL;
    END IF;
    RETURN _timetracker_temporal_atom_qualifier(endpoint_value);
END
$$;

CREATE FUNCTION public.timetracker_temporal_lower(value text) RETURNS date
    LANGUAGE plpgsql IMMUTABLE
    SET search_path TO 'pg_catalog', 'public'
    AS $$
DECLARE
    slash_position integer;
    start_value text;
    end_value text;
    start_known boolean;
    end_known boolean;
BEGIN
    IF value IS NULL THEN
        RETURN NULL;
    END IF;
    IF length(value) > 64 THEN
        RAISE EXCEPTION 'temporal value exceeds 64 characters';
    END IF;
    slash_position := strpos(value, '/');
    IF slash_position = 0 THEN
        RETURN _timetracker_temporal_atom_lower(value);
    END IF;
    IF strpos(substring(value FROM slash_position + 1), '/') > 0 THEN
        RAISE EXCEPTION 'temporal range must contain exactly one slash';
    END IF;

    start_value := substring(value FROM 1 FOR slash_position - 1);
    end_value := substring(value FROM slash_position + 1);
    start_known := start_value NOT IN ('', '..');
    end_known := end_value NOT IN ('', '..');
    IF NOT start_known AND NOT end_known THEN
        RAISE EXCEPTION 'temporal range requires at least one known endpoint';
    END IF;
    IF start_known THEN
        PERFORM _timetracker_temporal_atom_precision(start_value);
    END IF;
    IF end_known THEN
        PERFORM _timetracker_temporal_atom_precision(end_value);
    END IF;
    IF start_known AND end_known
       AND _timetracker_temporal_atom_lower(start_value)
           > _timetracker_temporal_atom_upper(end_value) THEN
        RAISE EXCEPTION 'temporal range starts after it ends';
    END IF;
    IF NOT start_known THEN
        RETURN NULL;
    END IF;
    RETURN _timetracker_temporal_atom_lower(start_value);
END
$$;

CREATE FUNCTION public.timetracker_temporal_upper(value text) RETURNS date
    LANGUAGE plpgsql IMMUTABLE
    SET search_path TO 'pg_catalog', 'public'
    AS $$
DECLARE
    slash_position integer;
    end_value text;
BEGIN
    PERFORM timetracker_temporal_lower(value);
    IF value IS NULL THEN
        RETURN NULL;
    END IF;
    slash_position := strpos(value, '/');
    IF slash_position = 0 THEN
        RETURN _timetracker_temporal_atom_upper(value);
    END IF;
    end_value := substring(value FROM slash_position + 1);
    IF end_value IN ('', '..') THEN
        RETURN NULL;
    END IF;
    RETURN _timetracker_temporal_atom_upper(end_value);
END
$$;


SET default_tablespace = '';

SET default_table_access_method = heap;

CREATE FUNCTION public.timetracker_temporal_is_valid(value text) RETURNS boolean
    LANGUAGE plpgsql IMMUTABLE
    SET search_path TO 'pg_catalog', 'public'
    AS $$
BEGIN
    PERFORM timetracker_temporal_lower(value);
    PERFORM timetracker_temporal_upper(value);
    PERFORM timetracker_temporal_kind(value);
    PERFORM timetracker_temporal_precision(value);
    PERFORM timetracker_temporal_start_kind(value);
    PERFORM timetracker_temporal_end_kind(value);
    PERFORM timetracker_temporal_start_precision(value);
    PERFORM timetracker_temporal_end_precision(value);
    PERFORM timetracker_temporal_qualifier(value);
    PERFORM timetracker_temporal_start_qualifier(value);
    PERFORM timetracker_temporal_end_qualifier(value);
    RETURN true;
EXCEPTION WHEN raise_exception OR data_exception THEN
    RETURN false;
END
$$;

CREATE DOMAIN public.temporal_value AS character varying(64)
	CONSTRAINT temporal_value_valid CHECK (((VALUE IS NULL) OR public.timetracker_temporal_is_valid((VALUE)::text)));
""".strip()

DROP_TEMPORAL_VALUE_DOMAIN = r"""
DROP DOMAIN public.temporal_value;
DROP FUNCTION public.timetracker_temporal_is_valid(text);
DROP FUNCTION public.timetracker_temporal_upper(text);
DROP FUNCTION public.timetracker_temporal_lower(text);
DROP FUNCTION public.timetracker_temporal_end_qualifier(text);
DROP FUNCTION public.timetracker_temporal_start_qualifier(text);
DROP FUNCTION public.timetracker_temporal_end_precision(text);
DROP FUNCTION public.timetracker_temporal_start_precision(text);
DROP FUNCTION public.timetracker_temporal_end_kind(text);
DROP FUNCTION public.timetracker_temporal_start_kind(text);
DROP FUNCTION public.timetracker_temporal_qualifier(text);
DROP FUNCTION public.timetracker_temporal_precision(text);
DROP FUNCTION public.timetracker_temporal_kind(text);
DROP FUNCTION public._timetracker_temporal_atom_upper(text);
DROP FUNCTION public._timetracker_temporal_atom_lower(text);
DROP FUNCTION public._timetracker_temporal_atom_precision(text);
DROP FUNCTION public._timetracker_temporal_atom_unqualified(text);
DROP FUNCTION public._timetracker_temporal_atom_qualifier(text);
""".strip()


#: Django writes no nullability at all into a generated column's definition, so
#: `CREATE TABLE` leaves one nullable however the field is declared. Every other
#: generated column here is declared nullable and means it; these two are not,
#: and reached their state through an `AlterField` this migration replaces. The
#: names below are the ones PostgreSQL derives on its own, so a database that
#: applied that history names the same constraints.
REQUIRE_A_TEMPORAL_KIND = """
ALTER TABLE games_game
    ALTER COLUMN original_release_date_kind SET NOT NULL;
ALTER TABLE games_release
    ALTER COLUMN release_date_kind SET NOT NULL;
""".strip()

ALLOW_A_MISSING_TEMPORAL_KIND = """
ALTER TABLE games_game
    ALTER COLUMN original_release_date_kind DROP NOT NULL;
ALTER TABLE games_release
    ALTER COLUMN release_date_kind DROP NOT NULL;
""".strip()

ADD_STREAM_OWNERSHIP_FOREIGN_KEY = """
ALTER TABLE games_libraryevent
    ADD CONSTRAINT library_event_stream_matches_library
    FOREIGN KEY (stream_id, library_id)
    REFERENCES games_libraryeventstreamhead (id, library_id);
""".strip()

DROP_STREAM_OWNERSHIP_FOREIGN_KEY = """
ALTER TABLE games_libraryevent
    DROP CONSTRAINT library_event_stream_matches_library;
""".strip()


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RunSQL(
            sql=CREATE_UUID_V7_DOMAIN,
            reverse_sql=DROP_UUID_V7_DOMAIN,
        ),
        migrations.RunSQL(
            sql=CREATE_TEMPORAL_VALUE_DOMAIN,
            reverse_sql=DROP_TEMPORAL_VALUE_DOMAIN,
        ),
        migrations.CreateModel(
            name="Game",
            fields=[
                (
                    "id",
                    timetracker.uuidv7.UUIDv7Field(
                        db_default=timetracker.uuidv7.PostgreSQLUUIDv7(),
                        default=uuid.uuid7,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("name", models.CharField(max_length=255)),
                ("sort_name", models.CharField(blank=True, default="", max_length=255)),
                (
                    "year_released",
                    models.IntegerField(blank=True, default=None, null=True),
                ),
                (
                    "original_year_released",
                    models.IntegerField(blank=True, default=None, null=True),
                ),
                (
                    "original_release_date",
                    timetracker.temporal.TemporalValueField(
                        blank=False,
                        default=None,
                        editable=False,
                        max_length=64,
                        null=True,
                    ),
                ),
                (
                    "original_release_date_lower",
                    models.GeneratedField(
                        db_persist=True,
                        expression=timetracker.temporal.TemporalLowerBound(
                            "original_release_date"
                        ),
                        null=True,
                        output_field=models.DateField(null=True),
                        serialize=False,
                    ),
                ),
                (
                    "original_release_date_upper",
                    models.GeneratedField(
                        db_persist=True,
                        expression=timetracker.temporal.TemporalUpperBound(
                            "original_release_date"
                        ),
                        null=True,
                        output_field=models.DateField(null=True),
                        serialize=False,
                    ),
                ),
                (
                    "original_release_date_kind",
                    models.GeneratedField(
                        db_persist=True,
                        expression=timetracker.temporal.TemporalKind(
                            "original_release_date"
                        ),
                        output_field=models.CharField(max_length=7),
                        serialize=False,
                    ),
                ),
                (
                    "original_release_date_precision",
                    models.GeneratedField(
                        db_persist=True,
                        expression=timetracker.temporal.TemporalPrecisionValue(
                            "original_release_date"
                        ),
                        null=True,
                        output_field=models.CharField(max_length=7, null=True),
                        serialize=False,
                    ),
                ),
                (
                    "original_release_date_start_kind",
                    models.GeneratedField(
                        db_persist=True,
                        expression=timetracker.temporal.TemporalStartKind(
                            "original_release_date"
                        ),
                        null=True,
                        output_field=models.CharField(max_length=7, null=True),
                        serialize=False,
                    ),
                ),
                (
                    "original_release_date_end_kind",
                    models.GeneratedField(
                        db_persist=True,
                        expression=timetracker.temporal.TemporalEndKind(
                            "original_release_date"
                        ),
                        null=True,
                        output_field=models.CharField(max_length=7, null=True),
                        serialize=False,
                    ),
                ),
                (
                    "original_release_date_start_precision",
                    models.GeneratedField(
                        db_persist=True,
                        expression=timetracker.temporal.TemporalStartPrecision(
                            "original_release_date"
                        ),
                        null=True,
                        output_field=models.CharField(max_length=7, null=True),
                        serialize=False,
                    ),
                ),
                (
                    "original_release_date_end_precision",
                    models.GeneratedField(
                        db_persist=True,
                        expression=timetracker.temporal.TemporalEndPrecision(
                            "original_release_date"
                        ),
                        null=True,
                        output_field=models.CharField(max_length=7, null=True),
                        serialize=False,
                    ),
                ),
                (
                    "original_release_date_qualifier",
                    models.GeneratedField(
                        db_persist=True,
                        expression=timetracker.temporal.TemporalQualifierValue(
                            "original_release_date"
                        ),
                        null=True,
                        output_field=models.CharField(max_length=11, null=True),
                        serialize=False,
                    ),
                ),
                (
                    "original_release_date_start_qualifier",
                    models.GeneratedField(
                        db_persist=True,
                        expression=timetracker.temporal.TemporalStartQualifier(
                            "original_release_date"
                        ),
                        null=True,
                        output_field=models.CharField(max_length=11, null=True),
                        serialize=False,
                    ),
                ),
                (
                    "original_release_date_end_qualifier",
                    models.GeneratedField(
                        db_persist=True,
                        expression=timetracker.temporal.TemporalEndQualifier(
                            "original_release_date"
                        ),
                        null=True,
                        output_field=models.CharField(max_length=11, null=True),
                        serialize=False,
                    ),
                ),
                ("wikidata", models.CharField(blank=True, default="", max_length=50)),
                (
                    "playtime",
                    models.DurationField(
                        blank=True, default=datetime.timedelta(0), editable=False
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "removed_at",
                    models.DateTimeField(
                        blank=True, default=None, editable=False, null=True
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("u", "Unplayed"),
                            ("p", "Played"),
                            ("f", "Finished"),
                            ("r", "Retired"),
                            ("a", "Abandoned"),
                        ],
                        default="u",
                        max_length=1,
                    ),
                ),
                ("mastered", models.BooleanField(default=False)),
            ],
        ),
        migrations.CreateModel(
            name="LibraryEventStreamHead",
            fields=[
                (
                    "id",
                    timetracker.uuidv7.UUIDv7Field(
                        db_default=timetracker.uuidv7.PostgreSQLUUIDv7(),
                        default=uuid.uuid7,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("current_sequence", models.PositiveBigIntegerField(default=0)),
            ],
        ),
        migrations.CreateModel(
            name="Platform",
            fields=[
                (
                    "id",
                    timetracker.uuidv7.UUIDv7Field(
                        db_default=timetracker.uuidv7.PostgreSQLUUIDv7(),
                        default=uuid.uuid7,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("name", models.CharField(max_length=255)),
                ("group", models.CharField(blank=True, default="", max_length=255)),
                ("icon", models.SlugField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "removed_at",
                    models.DateTimeField(
                        blank=True, default=None, editable=False, null=True
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="UserLibrary",
            fields=[
                (
                    "id",
                    timetracker.uuidv7.UUIDv7Field(
                        db_default=timetracker.uuidv7.PostgreSQLUUIDv7(),
                        default=uuid.uuid7,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "created_at",
                    models.DateTimeField(
                        default=django.utils.timezone.now, editable=False
                    ),
                ),
                (
                    "user",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="library",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="SiteSetting",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("key", models.CharField(max_length=100, unique=True)),
                ("value", models.JSONField()),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ["key"],
            },
        ),
        migrations.CreateModel(
            name="ExchangeRate",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("currency_from", models.CharField(max_length=255)),
                ("currency_to", models.CharField(max_length=255)),
                ("year", models.PositiveIntegerField()),
                ("rate", models.FloatField()),
            ],
            options={
                "unique_together": {("currency_from", "currency_to", "year")},
            },
        ),
        migrations.CreateModel(
            name="Edition",
            fields=[
                (
                    "id",
                    timetracker.uuidv7.UUIDv7Field(
                        db_default=timetracker.uuidv7.PostgreSQLUUIDv7(),
                        default=uuid.uuid7,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("name", models.CharField(blank=True, default="", max_length=255)),
                ("is_default", models.BooleanField(default=False, editable=False)),
                (
                    "removed_at",
                    models.DateTimeField(
                        blank=True, default=None, editable=False, null=True
                    ),
                ),
                (
                    "game",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="editions",
                        to="games.game",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="LibraryEvent",
            fields=[
                (
                    "id",
                    timetracker.uuidv7.UUIDv7Field(
                        db_default=timetracker.uuidv7.PostgreSQLUUIDv7(),
                        default=uuid.uuid7,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("sequence", models.PositiveBigIntegerField()),
                ("event_type", models.CharField(max_length=255)),
                (
                    "aggregate_id",
                    timetracker.uuidv7.UUIDv7Field(
                        db_default=django.db.models.fields.NOT_PROVIDED, default=None
                    ),
                ),
                ("payload_schema_version", models.PositiveIntegerField(default=1)),
                (
                    "recorded_at",
                    models.DateTimeField(
                        default=django.utils.timezone.now, editable=False
                    ),
                ),
                (
                    "effective_time",
                    timetracker.temporal.TemporalValueField(
                        blank=False,
                        default=None,
                        editable=False,
                        max_length=64,
                        null=True,
                    ),
                ),
                (
                    "correlation_id",
                    timetracker.uuidv7.UUIDv7Field(
                        db_default=django.db.models.fields.NOT_PROVIDED, default=None
                    ),
                ),
                (
                    "causation_id",
                    timetracker.uuidv7.UUIDv7Field(
                        blank=True,
                        db_default=django.db.models.fields.NOT_PROVIDED,
                        default=None,
                        null=True,
                    ),
                ),
                ("source_metadata", models.JSONField(blank=True, default=dict)),
                ("idempotency_key", models.CharField(max_length=255)),
                ("payload", models.JSONField()),
                (
                    "actor",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "stream",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.RESTRICT,
                        related_name="events",
                        to="games.libraryeventstreamhead",
                    ),
                ),
                (
                    "library",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="events",
                        to="games.userlibrary",
                    ),
                ),
            ],
        ),
        migrations.AddField(
            model_name="game",
            name="platform",
            field=models.ForeignKey(
                blank=True,
                default=None,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                to="games.platform",
            ),
        ),
        migrations.CreateModel(
            name="PlayerGame",
            fields=[
                (
                    "id",
                    timetracker.uuidv7.UUIDv7Field(
                        db_default=django.db.models.fields.NOT_PROVIDED,
                        default=django.db.models.fields.NOT_PROVIDED,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("tracked_at", models.DateTimeField(editable=False)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("unplayed", "Unplayed"),
                            ("played", "Played"),
                            ("completed", "Completed"),
                            ("retired", "Retired"),
                            ("shelved", "Shelved"),
                            ("abandoned", "Abandoned"),
                        ],
                        default="unplayed",
                        max_length=9,
                    ),
                ),
                ("mastered", models.BooleanField(default=False)),
                ("excluded_from_unfinished", models.BooleanField(default=False)),
                (
                    "removed_at",
                    models.DateTimeField(default=None, editable=False, null=True),
                ),
                (
                    "game",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.RESTRICT,
                        related_name="player_games",
                        to="games.game",
                    ),
                ),
                (
                    "library",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to="games.userlibrary",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="PurchaseConversionState",
            fields=[
                (
                    "library",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        primary_key=True,
                        related_name="purchase_conversion_state",
                        serialize=False,
                        to="games.userlibrary",
                    ),
                ),
                ("requested_version", models.PositiveBigIntegerField(default=0)),
                (
                    "requested_currency",
                    models.CharField(blank=True, default="", max_length=3),
                ),
                ("published_version", models.PositiveBigIntegerField(default=0)),
                (
                    "published_currency",
                    models.CharField(blank=True, default="", max_length=3),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("running", "Running"),
                            ("failed", "Failed"),
                            ("complete", "Complete"),
                        ],
                        default="complete",
                        max_length=10,
                    ),
                ),
                ("retry_at", models.DateTimeField(blank=True, default=None, null=True)),
                ("last_error", models.TextField(blank=True, default="")),
            ],
        ),
        migrations.CreateModel(
            name="UserLibraryPreferences",
            fields=[
                (
                    "library",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        primary_key=True,
                        related_name="preferences",
                        serialize=False,
                        to="games.userlibrary",
                    ),
                ),
                ("updated_at", models.DateTimeField(default=django.utils.timezone.now)),
            ],
        ),
        migrations.CreateModel(
            name="Purchase",
            fields=[
                (
                    "id",
                    timetracker.uuidv7.UUIDv7Field(
                        db_default=timetracker.uuidv7.PostgreSQLUUIDv7(),
                        default=uuid.uuid7,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("date_purchased", models.DateField(verbose_name="Purchased")),
                (
                    "date_refunded",
                    models.DateField(blank=True, null=True, verbose_name="Refunded"),
                ),
                ("infinite", models.BooleanField(default=False)),
                ("price", models.FloatField(default=0)),
                (
                    "price_currency",
                    models.CharField(blank=True, default="", max_length=3),
                ),
                ("converted_price", models.FloatField(null=True)),
                (
                    "converted_currency",
                    models.CharField(blank=True, default="", max_length=3),
                ),
                (
                    "needs_price_update",
                    models.BooleanField(db_index=True, default=True),
                ),
                (
                    "price_per_game",
                    models.GeneratedField(
                        db_persist=True,
                        expression=django.db.models.expressions.CombinedExpression(
                            django.db.models.functions.comparison.Coalesce(
                                models.F("converted_price"), models.F("price"), 0
                            ),
                            "/",
                            django.db.models.functions.comparison.NullIf(
                                models.F("num_purchases"), 0
                            ),
                        ),
                        output_field=models.FloatField(),
                    ),
                ),
                ("num_purchases", models.IntegerField(default=0)),
                (
                    "ownership_type",
                    models.CharField(
                        choices=[
                            ("ph", "Physical"),
                            ("di", "Digital"),
                            ("du", "Digital Upgrade"),
                            ("re", "Rented"),
                            ("bo", "Borrowed"),
                            ("tr", "Trial"),
                            ("de", "Demo"),
                            ("pi", "Pirated"),
                        ],
                        default="di",
                        max_length=2,
                    ),
                ),
                (
                    "type",
                    models.CharField(
                        choices=[
                            ("game", "Game"),
                            ("dlc", "DLC"),
                            ("season_pass", "Season Pass"),
                            ("battle_pass", "Battle Pass"),
                        ],
                        default="game",
                        max_length=255,
                    ),
                ),
                ("name", models.CharField(blank=True, default="", max_length=255)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "removed_at",
                    models.DateTimeField(
                        blank=True, default=None, editable=False, null=True
                    ),
                ),
                (
                    "games",
                    models.ManyToManyField(related_name="purchases", to="games.game"),
                ),
                (
                    "platform",
                    models.ForeignKey(
                        blank=True,
                        default=None,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to="games.platform",
                    ),
                ),
                (
                    "related_game",
                    models.ForeignKey(
                        blank=True,
                        default=None,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="addon_purchases",
                        to="games.game",
                        verbose_name="Base game",
                    ),
                ),
                (
                    "library",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="purchases",
                        to="games.userlibrary",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="Playthrough",
            fields=[
                (
                    "id",
                    timetracker.uuidv7.UUIDv7Field(
                        db_default=django.db.models.fields.NOT_PROVIDED,
                        default=django.db.models.fields.NOT_PROVIDED,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "kind",
                    models.CharField(
                        choices=[
                            ("ordinary", "Ordinary"),
                            ("imported_history", "Imported history"),
                        ],
                        max_length=16,
                    ),
                ),
                ("name", models.CharField(blank=True, default="", max_length=255)),
                ("note", models.TextField(blank=True, default="")),
                (
                    "started",
                    timetracker.temporal.TemporalValueField(
                        blank=False,
                        default=None,
                        editable=False,
                        max_length=64,
                        null=True,
                    ),
                ),
                (
                    "started_lower",
                    models.GeneratedField(
                        db_persist=True,
                        expression=timetracker.temporal.TemporalLowerBound("started"),
                        null=True,
                        output_field=models.DateField(null=True),
                        serialize=False,
                    ),
                ),
                (
                    "started_upper",
                    models.GeneratedField(
                        db_persist=True,
                        expression=timetracker.temporal.TemporalUpperBound("started"),
                        null=True,
                        output_field=models.DateField(null=True),
                        serialize=False,
                    ),
                ),
                (
                    "start_recorded_at",
                    models.DateTimeField(default=None, editable=False, null=True),
                ),
                ("start_note", models.TextField(blank=True, default="")),
                (
                    "completed",
                    timetracker.temporal.TemporalValueField(
                        blank=False,
                        default=None,
                        editable=False,
                        max_length=64,
                        null=True,
                    ),
                ),
                (
                    "completed_lower",
                    models.GeneratedField(
                        db_persist=True,
                        expression=timetracker.temporal.TemporalLowerBound("completed"),
                        null=True,
                        output_field=models.DateField(null=True),
                        serialize=False,
                    ),
                ),
                (
                    "completed_upper",
                    models.GeneratedField(
                        db_persist=True,
                        expression=timetracker.temporal.TemporalUpperBound("completed"),
                        null=True,
                        output_field=models.DateField(null=True),
                        serialize=False,
                    ),
                ),
                (
                    "completion_recorded_at",
                    models.DateTimeField(default=None, editable=False, null=True),
                ),
                ("completion_note", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(editable=False)),
                (
                    "removed_at",
                    models.DateTimeField(default=None, editable=False, null=True),
                ),
                (
                    "player_game",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.RESTRICT,
                        related_name="playthroughs",
                        to="games.playergame",
                    ),
                ),
                (
                    "library",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to="games.userlibrary",
                    ),
                ),
            ],
        ),
        migrations.AddField(
            model_name="platform",
            name="library",
            field=models.ForeignKey(
                blank=True,
                default=None,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="platforms",
                to="games.userlibrary",
            ),
        ),
        migrations.CreateModel(
            name="LibraryIdempotencyRecord",
            fields=[
                (
                    "id",
                    timetracker.uuidv7.UUIDv7Field(
                        db_default=timetracker.uuidv7.PostgreSQLUUIDv7(),
                        default=uuid.uuid7,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("idempotency_key", models.CharField(max_length=255)),
                ("request_fingerprint", models.CharField(max_length=64)),
                ("fingerprint_version", models.PositiveSmallIntegerField()),
                ("first_sequence", models.PositiveBigIntegerField(null=True)),
                ("last_sequence", models.PositiveBigIntegerField(null=True)),
                (
                    "created_at",
                    models.DateTimeField(
                        default=django.utils.timezone.now, editable=False
                    ),
                ),
                (
                    "library",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="idempotency_records",
                        to="games.userlibrary",
                    ),
                ),
            ],
        ),
        migrations.AddField(
            model_name="libraryeventstreamhead",
            name="library",
            field=models.OneToOneField(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="event_stream_head",
                to="games.userlibrary",
            ),
        ),
        migrations.CreateModel(
            name="LibraryEventReference",
            fields=[
                (
                    "id",
                    timetracker.uuidv7.UUIDv7Field(
                        db_default=timetracker.uuidv7.PostgreSQLUUIDv7(),
                        default=uuid.uuid7,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("kind", models.CharField(max_length=255)),
                (
                    "referenced_id",
                    timetracker.uuidv7.UUIDv7Field(
                        db_default=django.db.models.fields.NOT_PROVIDED, default=None
                    ),
                ),
                ("payload_key", models.CharField(max_length=255)),
                (
                    "event",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="references",
                        to="games.libraryevent",
                    ),
                ),
                (
                    "library",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="event_references",
                        to="games.userlibrary",
                    ),
                ),
            ],
        ),
        migrations.AddField(
            model_name="game",
            name="library",
            field=models.ForeignKey(
                blank=True,
                default=None,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="games",
                to="games.userlibrary",
            ),
        ),
        migrations.CreateModel(
            name="FilterPreset",
            fields=[
                (
                    "id",
                    timetracker.uuidv7.UUIDv7Field(
                        db_default=timetracker.uuidv7.PostgreSQLUUIDv7(),
                        default=uuid.uuid7,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("name", models.CharField(max_length=255)),
                (
                    "mode",
                    models.CharField(
                        choices=[
                            ("games", "Games"),
                            ("sessions", "Sessions"),
                            ("purchases", "Purchases"),
                            ("playthroughs", "Playthroughs"),
                            ("devices", "Devices"),
                            ("platforms", "Platforms"),
                        ],
                        default="games",
                        max_length=50,
                    ),
                ),
                ("find_filter", models.JSONField(blank=True, default=dict)),
                ("object_filter", models.JSONField(blank=True, default=dict)),
                ("ui_options", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "removed_at",
                    models.DateTimeField(
                        blank=True, default=None, editable=False, null=True
                    ),
                ),
                (
                    "library",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="filter_presets",
                        to="games.userlibrary",
                    ),
                ),
            ],
            options={
                "ordering": ["name"],
            },
        ),
        migrations.CreateModel(
            name="Device",
            fields=[
                (
                    "id",
                    timetracker.uuidv7.UUIDv7Field(
                        db_default=timetracker.uuidv7.PostgreSQLUUIDv7(),
                        default=uuid.uuid7,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("name", models.CharField(max_length=255)),
                (
                    "type",
                    models.CharField(
                        choices=[
                            ("PC", "PC"),
                            ("Console", "Console"),
                            ("Handheld", "Handheld"),
                            ("Mobile", "Mobile"),
                            ("Single-board computer", "Single-board computer"),
                            ("Unknown", "Unknown"),
                        ],
                        default="Unknown",
                        max_length=255,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "removed_at",
                    models.DateTimeField(
                        blank=True, default=None, editable=False, null=True
                    ),
                ),
                (
                    "library",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="devices",
                        to="games.userlibrary",
                    ),
                ),
            ],
            options={
                "abstract": False,
            },
        ),
        migrations.CreateModel(
            name="Release",
            fields=[
                (
                    "id",
                    timetracker.uuidv7.UUIDv7Field(
                        db_default=timetracker.uuidv7.PostgreSQLUUIDv7(),
                        default=uuid.uuid7,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("is_default", models.BooleanField(default=False, editable=False)),
                (
                    "release_date",
                    timetracker.temporal.TemporalValueField(
                        blank=False,
                        default=None,
                        editable=False,
                        max_length=64,
                        null=True,
                    ),
                ),
                (
                    "release_date_lower",
                    models.GeneratedField(
                        db_persist=True,
                        expression=timetracker.temporal.TemporalLowerBound(
                            "release_date"
                        ),
                        null=True,
                        output_field=models.DateField(null=True),
                        serialize=False,
                    ),
                ),
                (
                    "release_date_upper",
                    models.GeneratedField(
                        db_persist=True,
                        expression=timetracker.temporal.TemporalUpperBound(
                            "release_date"
                        ),
                        null=True,
                        output_field=models.DateField(null=True),
                        serialize=False,
                    ),
                ),
                (
                    "release_date_kind",
                    models.GeneratedField(
                        db_persist=True,
                        expression=timetracker.temporal.TemporalKind("release_date"),
                        output_field=models.CharField(max_length=7),
                        serialize=False,
                    ),
                ),
                (
                    "release_date_precision",
                    models.GeneratedField(
                        db_persist=True,
                        expression=timetracker.temporal.TemporalPrecisionValue(
                            "release_date"
                        ),
                        null=True,
                        output_field=models.CharField(max_length=7, null=True),
                        serialize=False,
                    ),
                ),
                (
                    "release_date_start_kind",
                    models.GeneratedField(
                        db_persist=True,
                        expression=timetracker.temporal.TemporalStartKind(
                            "release_date"
                        ),
                        null=True,
                        output_field=models.CharField(max_length=7, null=True),
                        serialize=False,
                    ),
                ),
                (
                    "release_date_end_kind",
                    models.GeneratedField(
                        db_persist=True,
                        expression=timetracker.temporal.TemporalEndKind("release_date"),
                        null=True,
                        output_field=models.CharField(max_length=7, null=True),
                        serialize=False,
                    ),
                ),
                (
                    "release_date_start_precision",
                    models.GeneratedField(
                        db_persist=True,
                        expression=timetracker.temporal.TemporalStartPrecision(
                            "release_date"
                        ),
                        null=True,
                        output_field=models.CharField(max_length=7, null=True),
                        serialize=False,
                    ),
                ),
                (
                    "release_date_end_precision",
                    models.GeneratedField(
                        db_persist=True,
                        expression=timetracker.temporal.TemporalEndPrecision(
                            "release_date"
                        ),
                        null=True,
                        output_field=models.CharField(max_length=7, null=True),
                        serialize=False,
                    ),
                ),
                (
                    "release_date_qualifier",
                    models.GeneratedField(
                        db_persist=True,
                        expression=timetracker.temporal.TemporalQualifierValue(
                            "release_date"
                        ),
                        null=True,
                        output_field=models.CharField(max_length=11, null=True),
                        serialize=False,
                    ),
                ),
                (
                    "release_date_start_qualifier",
                    models.GeneratedField(
                        db_persist=True,
                        expression=timetracker.temporal.TemporalStartQualifier(
                            "release_date"
                        ),
                        null=True,
                        output_field=models.CharField(max_length=11, null=True),
                        serialize=False,
                    ),
                ),
                (
                    "release_date_end_qualifier",
                    models.GeneratedField(
                        db_persist=True,
                        expression=timetracker.temporal.TemporalEndQualifier(
                            "release_date"
                        ),
                        null=True,
                        output_field=models.CharField(max_length=11, null=True),
                        serialize=False,
                    ),
                ),
                (
                    "removed_at",
                    models.DateTimeField(
                        blank=True, default=None, editable=False, null=True
                    ),
                ),
                (
                    "edition",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="releases",
                        to="games.edition",
                    ),
                ),
                (
                    "platform",
                    models.ForeignKey(
                        blank=True,
                        default=None,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to="games.platform",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="ExternalReference",
            fields=[
                (
                    "id",
                    timetracker.uuidv7.UUIDv7Field(
                        db_default=timetracker.uuidv7.PostgreSQLUUIDv7(),
                        default=uuid.uuid7,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "provider",
                    models.CharField(choices=[("wikidata", "Wikidata")], max_length=50),
                ),
                (
                    "entity_kind",
                    models.CharField(
                        choices=[
                            ("game", "Game"),
                            ("edition", "Edition"),
                            ("release", "Release"),
                            ("platform", "Platform"),
                        ],
                        max_length=20,
                    ),
                ),
                ("provider_key", models.CharField(max_length=255)),
                (
                    "removed_at",
                    models.DateTimeField(
                        blank=True, default=None, editable=False, null=True
                    ),
                ),
                (
                    "edition",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="external_references",
                        to="games.edition",
                    ),
                ),
                (
                    "game",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="external_references",
                        to="games.game",
                    ),
                ),
                (
                    "platform",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="external_references",
                        to="games.platform",
                    ),
                ),
                (
                    "release",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="external_references",
                        to="games.release",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="Session",
            fields=[
                (
                    "id",
                    timetracker.uuidv7.UUIDv7Field(
                        db_default=timetracker.uuidv7.PostgreSQLUUIDv7(),
                        default=uuid.uuid7,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "timestamp_start",
                    models.DateTimeField(db_index=True, verbose_name="Session start"),
                ),
                (
                    "timestamp_end",
                    models.DateTimeField(
                        blank=True, null=True, verbose_name="Session end"
                    ),
                ),
                (
                    "timestamp_start_timezone",
                    models.CharField(
                        blank=True, default=None, max_length=64, null=True
                    ),
                ),
                (
                    "timestamp_end_timezone",
                    models.CharField(
                        blank=True, default=None, max_length=64, null=True
                    ),
                ),
                (
                    "duration_manual",
                    models.DurationField(
                        blank=True,
                        default=datetime.timedelta(0),
                        null=True,
                        verbose_name="Manual duration",
                    ),
                ),
                (
                    "duration_calculated",
                    models.GeneratedField(
                        db_persist=True,
                        expression=django.db.models.functions.comparison.Coalesce(
                            django.db.models.expressions.CombinedExpression(
                                models.F("timestamp_end"),
                                "-",
                                models.F("timestamp_start"),
                            ),
                            datetime.timedelta(0),
                        ),
                        output_field=models.DurationField(),
                    ),
                ),
                (
                    "duration_total",
                    models.GeneratedField(
                        db_persist=True,
                        expression=models.ExpressionWrapper(
                            django.db.models.expressions.CombinedExpression(
                                django.db.models.functions.comparison.Coalesce(
                                    django.db.models.expressions.CombinedExpression(
                                        models.F("timestamp_end"),
                                        "-",
                                        models.F("timestamp_start"),
                                    ),
                                    datetime.timedelta(0),
                                ),
                                "+",
                                models.F("duration_manual"),
                            ),
                            output_field=models.DurationField(),
                        ),
                        output_field=models.DurationField(),
                    ),
                ),
                ("note", models.TextField(blank=True, default="")),
                ("emulated", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("modified_at", models.DateTimeField(auto_now=True)),
                (
                    "removed_at",
                    models.DateTimeField(
                        blank=True, default=None, editable=False, null=True
                    ),
                ),
                (
                    "device",
                    models.ForeignKey(
                        blank=True,
                        default=None,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to="games.device",
                    ),
                ),
                (
                    "game",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="sessions",
                        to="games.game",
                    ),
                ),
            ],
            options={
                "get_latest_by": "timestamp_start",
            },
        ),
        migrations.CreateModel(
            name="UserPreferences",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "default_purchase_currency",
                    models.CharField(blank=True, default=None, max_length=3, null=True),
                ),
                (
                    "default_display_currency",
                    models.CharField(blank=True, default=None, max_length=3, null=True),
                ),
                (
                    "default_landing_page",
                    models.CharField(
                        blank=True, default=None, max_length=100, null=True
                    ),
                ),
                (
                    "theme",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("system", "System"),
                            ("light", "Light"),
                            ("dark", "Dark"),
                        ],
                        default=None,
                        max_length=6,
                        null=True,
                    ),
                ),
                (
                    "display_time_zone",
                    models.CharField(
                        blank=True, default=None, max_length=100, null=True
                    ),
                ),
                (
                    "date_format_locale",
                    models.CharField(
                        blank=True, default=None, max_length=20, null=True
                    ),
                ),
                (
                    "datetime_format",
                    models.CharField(
                        blank=True, default=None, max_length=20, null=True
                    ),
                ),
                ("extra_preferences", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "user",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="preferences",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "user preferences",
                "verbose_name_plural": "user preferences",
            },
        ),
        migrations.AddIndex(
            model_name="edition",
            index=models.Index(
                condition=models.Q(("removed_at__isnull", True)),
                fields=["game"],
                name="live_edition_per_game_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="edition",
            constraint=models.UniqueConstraint(
                condition=models.Q(("is_default", True), ("removed_at__isnull", True)),
                fields=("game",),
                name="unique_default_edition_per_game",
            ),
        ),
        migrations.AddConstraint(
            model_name="edition",
            constraint=models.UniqueConstraint(
                models.F("game"),
                django.db.models.functions.text.Lower(
                    django.db.models.functions.text.Trim("name")
                ),
                condition=models.Q(
                    ("removed_at__isnull", True), models.Q(("name", ""), _negated=True)
                ),
                name="unique_live_edition_name_per_game",
            ),
        ),
        migrations.AddField(
            model_name="userlibrarypreferences",
            name="default_device",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="games.device",
            ),
        ),
        migrations.AddIndex(
            model_name="playthrough",
            index=models.Index(
                fields=[
                    "player_game",
                    "started_lower",
                    "completed_lower",
                    "created_at",
                    "id",
                ],
                name="playthrough_display_order",
            ),
        ),
        migrations.AddConstraint(
            model_name="playergame",
            constraint=models.UniqueConstraint(
                fields=("library", "game"), name="unique_library_player_game"
            ),
        ),
        migrations.AddConstraint(
            model_name="platform",
            constraint=models.UniqueConstraint(
                django.db.models.functions.text.Lower(
                    django.db.models.functions.text.Trim("name")
                ),
                django.db.models.functions.text.Lower(
                    django.db.models.functions.text.Trim("group")
                ),
                condition=models.Q(
                    ("library__isnull", True), ("removed_at__isnull", True)
                ),
                name="unique_shared_platform_normalized_name_group",
            ),
        ),
        migrations.AddConstraint(
            model_name="platform",
            constraint=models.UniqueConstraint(
                models.F("library"),
                django.db.models.functions.text.Lower(
                    django.db.models.functions.text.Trim("name")
                ),
                django.db.models.functions.text.Lower(
                    django.db.models.functions.text.Trim("group")
                ),
                condition=models.Q(
                    ("library__isnull", False), ("removed_at__isnull", True)
                ),
                name="unique_private_platform_normalized_name_group",
            ),
        ),
        migrations.AddConstraint(
            model_name="libraryidempotencyrecord",
            constraint=models.UniqueConstraint(
                fields=("library", "idempotency_key"),
                name="unique_library_idempotency_key",
            ),
        ),
        migrations.AddConstraint(
            model_name="libraryidempotencyrecord",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(
                        ("first_sequence__isnull", True),
                        ("last_sequence__isnull", True),
                    ),
                    models.Q(
                        ("first_sequence__gte", 1),
                        ("first_sequence__isnull", False),
                        ("last_sequence__gte", models.F("first_sequence")),
                        ("last_sequence__isnull", False),
                    ),
                    _connector="OR",
                ),
                name="library_idempotency_range_whole",
            ),
        ),
        migrations.AddConstraint(
            model_name="libraryidempotencyrecord",
            constraint=models.CheckConstraint(
                condition=models.Q(("idempotency_key", ""), _negated=True),
                name="library_idempotency_key_not_empty",
            ),
        ),
        migrations.AddConstraint(
            model_name="libraryidempotencyrecord",
            constraint=models.CheckConstraint(
                condition=models.Q(("request_fingerprint", ""), _negated=True),
                name="library_idempotency_request_fingerprint_not_empty",
            ),
        ),
        migrations.AddConstraint(
            model_name="libraryidempotencyrecord",
            constraint=models.CheckConstraint(
                condition=models.Q(("fingerprint_version__gte", 1)),
                name="library_idempotency_fingerprint_version_positive",
            ),
        ),
        migrations.AddConstraint(
            model_name="libraryeventstreamhead",
            constraint=models.UniqueConstraint(
                fields=("id", "library"),
                name="unique_library_event_stream_head_library_identity",
            ),
        ),
        migrations.AddIndex(
            model_name="libraryeventreference",
            index=models.Index(
                fields=["kind", "referenced_id"], name="games_libra_kind_d63eba_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="libraryeventreference",
            index=models.Index(
                fields=["library", "kind"], name="games_libra_library_8b9f77_idx"
            ),
        ),
        migrations.AddConstraint(
            model_name="libraryeventreference",
            constraint=models.CheckConstraint(
                condition=models.Q(("kind", ""), _negated=True),
                name="library_event_reference_kind_not_empty",
            ),
        ),
        migrations.AddConstraint(
            model_name="libraryeventreference",
            constraint=models.CheckConstraint(
                condition=models.Q(("payload_key", ""), _negated=True),
                name="library_event_reference_payload_key_not_empty",
            ),
        ),
        migrations.AddConstraint(
            model_name="libraryevent",
            constraint=models.UniqueConstraint(
                fields=("stream", "sequence"),
                name="unique_library_event_stream_sequence",
            ),
        ),
        migrations.AddConstraint(
            model_name="libraryevent",
            constraint=models.CheckConstraint(
                condition=models.Q(("sequence__gte", 1)),
                name="library_event_sequence_positive",
            ),
        ),
        migrations.AddConstraint(
            model_name="libraryevent",
            constraint=models.CheckConstraint(
                condition=models.Q(("payload_schema_version__gte", 1)),
                name="library_event_payload_schema_version_positive",
            ),
        ),
        migrations.AddConstraint(
            model_name="libraryevent",
            constraint=models.CheckConstraint(
                condition=models.Q(("event_type", ""), _negated=True),
                name="library_event_type_not_empty",
            ),
        ),
        migrations.AddConstraint(
            model_name="libraryevent",
            constraint=models.CheckConstraint(
                condition=models.Q(("idempotency_key", ""), _negated=True),
                name="library_event_idempotency_key_not_empty",
            ),
        ),
        migrations.AddConstraint(
            model_name="game",
            constraint=models.UniqueConstraint(
                condition=models.Q(("removed_at__isnull", True)),
                fields=("library", "name", "platform", "year_released"),
                name="unique_library_game_name_platform_year",
            ),
        ),
        migrations.AddConstraint(
            model_name="game",
            constraint=models.UniqueConstraint(
                condition=models.Q(
                    ("platform__isnull", True), ("removed_at__isnull", True)
                ),
                fields=("library", "name", "year_released"),
                name="unique_library_platformless_game_name_year",
            ),
        ),
        migrations.AddConstraint(
            model_name="filterpreset",
            constraint=models.UniqueConstraint(
                condition=models.Q(("removed_at__isnull", True)),
                fields=("library", "mode", "name"),
                name="unique_library_mode_name_preset",
            ),
        ),
        migrations.AddIndex(
            model_name="release",
            index=models.Index(
                condition=models.Q(("removed_at__isnull", True)),
                fields=["edition"],
                name="live_release_per_edition_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="release",
            constraint=models.UniqueConstraint(
                condition=models.Q(("is_default", True), ("removed_at__isnull", True)),
                fields=("edition",),
                name="unique_default_release_per_edition",
            ),
        ),
        migrations.AddConstraint(
            model_name="externalreference",
            constraint=models.UniqueConstraint(
                condition=models.Q(("removed_at__isnull", True)),
                fields=("provider", "entity_kind", "provider_key"),
                name="unique_external_reference_provider_kind_key",
            ),
        ),
        migrations.AddConstraint(
            model_name="externalreference",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(
                        ("edition__isnull", True),
                        ("entity_kind", "game"),
                        ("game__isnull", False),
                        ("platform__isnull", True),
                        ("release__isnull", True),
                    ),
                    models.Q(
                        ("edition__isnull", False),
                        ("entity_kind", "edition"),
                        ("game__isnull", True),
                        ("platform__isnull", True),
                        ("release__isnull", True),
                    ),
                    models.Q(
                        ("edition__isnull", True),
                        ("entity_kind", "release"),
                        ("game__isnull", True),
                        ("platform__isnull", True),
                        ("release__isnull", False),
                    ),
                    models.Q(
                        ("edition__isnull", True),
                        ("entity_kind", "platform"),
                        ("game__isnull", True),
                        ("platform__isnull", False),
                        ("release__isnull", True),
                    ),
                    _connector="OR",
                ),
                name="external_reference_kind_matches_target",
            ),
        ),
        migrations.AddConstraint(
            model_name="externalreference",
            constraint=models.CheckConstraint(
                condition=models.Q(("provider", "wikidata")),
                name="external_reference_supported_provider",
            ),
        ),
        migrations.AddConstraint(
            model_name="externalreference",
            constraint=models.CheckConstraint(
                condition=models.Q(("provider_key__regex", "^Q[1-9][0-9]*$")),
                name="external_reference_canonical_provider_key",
            ),
        ),
        migrations.AddConstraint(
            model_name="externalreference",
            constraint=models.UniqueConstraint(
                condition=models.Q(
                    ("game__isnull", False), ("removed_at__isnull", True)
                ),
                fields=("provider", "game"),
                name="unique_live_game_reference_per_provider",
            ),
        ),
        migrations.AddConstraint(
            model_name="externalreference",
            constraint=models.UniqueConstraint(
                condition=models.Q(
                    ("edition__isnull", False), ("removed_at__isnull", True)
                ),
                fields=("provider", "edition"),
                name="unique_live_edition_reference_per_provider",
            ),
        ),
        migrations.AddConstraint(
            model_name="externalreference",
            constraint=models.UniqueConstraint(
                condition=models.Q(
                    ("release__isnull", False), ("removed_at__isnull", True)
                ),
                fields=("provider", "release"),
                name="unique_live_release_reference_per_provider",
            ),
        ),
        migrations.AddConstraint(
            model_name="externalreference",
            constraint=models.UniqueConstraint(
                condition=models.Q(
                    ("platform__isnull", False), ("removed_at__isnull", True)
                ),
                fields=("provider", "platform"),
                name="unique_live_platform_reference_per_provider",
            ),
        ),
        migrations.AddIndex(
            model_name="session",
            index=models.Index(
                fields=["timestamp_start", "id"], name="session_start_id_idx"
            ),
        ),
        migrations.RunSQL(
            sql=REQUIRE_A_TEMPORAL_KIND,
            reverse_sql=ALLOW_A_MISSING_TEMPORAL_KIND,
        ),
        migrations.RunSQL(
            sql=ADD_STREAM_OWNERSHIP_FOREIGN_KEY,
            reverse_sql=DROP_STREAM_OWNERSHIP_FOREIGN_KEY,
        ),
    ]
