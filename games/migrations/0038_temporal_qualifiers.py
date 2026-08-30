from django.db import migrations, models

import timetracker.temporal

# A qualifier states certainty, never bounds.
#
# This widens the grammar, and no stored string can carry a symbol, so every
# value the schema holds parses to the verdict it parsed to before. The domain
# constraint therefore stays and the generated columns are not rebuilt, on the
# reasoning 0034 recorded for the same shape of change.
#
# The reverse serves the test suite, which drives the executor below this node
# in twenty modules. A reverse revalidates nothing, so a row written as `1984~`
# survives it, and the next UPDATE of that row then raises `invalid temporal
# atom: 1984~`. Restate such a value before reversing, or do not reverse.

ADD_QUALIFIER_SUPPORT = r"""
CREATE FUNCTION _timetracker_temporal_atom_unqualified(value text)
RETURNS text
LANGUAGE plpgsql
IMMUTABLE
SET search_path = pg_catalog, public
AS $$
BEGIN
    IF value IS NOT NULL AND right(value, 1) IN ('?', '~', '%') THEN
        RETURN left(value, -1);
    END IF;
    RETURN value;
END
$$;

CREATE FUNCTION _timetracker_temporal_atom_qualifier(value text)
RETURNS text
LANGUAGE plpgsql
IMMUTABLE
SET search_path = pg_catalog, public
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

CREATE OR REPLACE FUNCTION _timetracker_temporal_atom_precision(value text)
RETURNS text
LANGUAGE plpgsql
IMMUTABLE
SET search_path = pg_catalog, public
AS $$
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
$$;

CREATE OR REPLACE FUNCTION _timetracker_temporal_atom_lower(value text)
RETURNS date
LANGUAGE plpgsql
IMMUTABLE
SET search_path = pg_catalog, public
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

CREATE OR REPLACE FUNCTION _timetracker_temporal_atom_upper(value text)
RETURNS date
LANGUAGE plpgsql
IMMUTABLE
SET search_path = pg_catalog, public
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

CREATE FUNCTION timetracker_temporal_qualifier(value text)
RETURNS text
LANGUAGE plpgsql
IMMUTABLE
SET search_path = pg_catalog, public
AS $$
BEGIN
    PERFORM timetracker_temporal_lower(value);
    IF value IS NULL OR strpos(value, '/') > 0 THEN
        RETURN NULL;
    END IF;
    RETURN _timetracker_temporal_atom_qualifier(value);
END
$$;

CREATE FUNCTION timetracker_temporal_start_qualifier(value text)
RETURNS text
LANGUAGE plpgsql
IMMUTABLE
SET search_path = pg_catalog, public
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

CREATE FUNCTION timetracker_temporal_end_qualifier(value text)
RETURNS text
LANGUAGE plpgsql
IMMUTABLE
SET search_path = pg_catalog, public
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

CREATE OR REPLACE FUNCTION timetracker_temporal_is_valid(value text)
RETURNS boolean
LANGUAGE plpgsql
IMMUTABLE
SET search_path = pg_catalog, public
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
""".strip()


# Restore these before dropping what they call.
REMOVE_QUALIFIER_SUPPORT = r"""
CREATE OR REPLACE FUNCTION _timetracker_temporal_atom_precision(value text)
RETURNS text
LANGUAGE plpgsql
IMMUTABLE
SET search_path = pg_catalog, public
AS $$
DECLARE
    year_number integer;
    month_number integer;
    day_number integer;
BEGIN
    IF value ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$' THEN
        year_number := substring(value FROM 1 FOR 4)::integer;
        month_number := substring(value FROM 6 FOR 2)::integer;
        day_number := substring(value FROM 9 FOR 2)::integer;
        PERFORM make_date(year_number, month_number, day_number);
        RETURN 'day';
    ELSIF value ~ '^[0-9]{4}-[0-9]{2}$' THEN
        year_number := substring(value FROM 1 FOR 4)::integer;
        month_number := substring(value FROM 6 FOR 2)::integer;
        PERFORM make_date(year_number, month_number, 1);
        RETURN 'month';
    ELSIF value ~ '^[0-9]{4}$' THEN
        year_number := value::integer;
        PERFORM make_date(year_number, 1, 1);
        RETURN 'year';
    ELSIF value ~ '^[0-9]{3}X$' THEN
        year_number := substring(value FROM 1 FOR 3)::integer * 10;
        PERFORM make_date(year_number, 1, 1);
        PERFORM make_date(year_number + 9, 12, 31);
        RETURN 'decade';
    END IF;

    RAISE EXCEPTION 'invalid temporal atom: %', value;
END
$$;

CREATE OR REPLACE FUNCTION _timetracker_temporal_atom_lower(value text)
RETURNS date
LANGUAGE plpgsql
IMMUTABLE
SET search_path = pg_catalog, public
AS $$
DECLARE
    precision_name text;
    year_number integer;
    month_number integer;
BEGIN
    precision_name := _timetracker_temporal_atom_precision(value);
    IF precision_name = 'day' THEN
        RETURN make_date(
            substring(value FROM 1 FOR 4)::integer,
            substring(value FROM 6 FOR 2)::integer,
            substring(value FROM 9 FOR 2)::integer
        );
    ELSIF precision_name = 'month' THEN
        year_number := substring(value FROM 1 FOR 4)::integer;
        month_number := substring(value FROM 6 FOR 2)::integer;
        RETURN make_date(year_number, month_number, 1);
    ELSIF precision_name = 'year' THEN
        RETURN make_date(value::integer, 1, 1);
    END IF;

    year_number := substring(value FROM 1 FOR 3)::integer * 10;
    RETURN make_date(year_number, 1, 1);
END
$$;

CREATE OR REPLACE FUNCTION _timetracker_temporal_atom_upper(value text)
RETURNS date
LANGUAGE plpgsql
IMMUTABLE
SET search_path = pg_catalog, public
AS $$
DECLARE
    precision_name text;
    year_number integer;
    month_number integer;
BEGIN
    precision_name := _timetracker_temporal_atom_precision(value);
    IF precision_name = 'day' THEN
        RETURN make_date(
            substring(value FROM 1 FOR 4)::integer,
            substring(value FROM 6 FOR 2)::integer,
            substring(value FROM 9 FOR 2)::integer
        );
    ELSIF precision_name = 'month' THEN
        year_number := substring(value FROM 1 FOR 4)::integer;
        month_number := substring(value FROM 6 FOR 2)::integer;
        IF month_number = 12 THEN
            RETURN make_date(year_number, 12, 31);
        END IF;
        RETURN make_date(year_number, month_number + 1, 1) - 1;
    ELSIF precision_name = 'year' THEN
        RETURN make_date(value::integer, 12, 31);
    END IF;

    year_number := substring(value FROM 1 FOR 3)::integer * 10;
    RETURN make_date(year_number + 9, 12, 31);
END
$$;

CREATE OR REPLACE FUNCTION timetracker_temporal_is_valid(value text)
RETURNS boolean
LANGUAGE plpgsql
IMMUTABLE
SET search_path = pg_catalog, public
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
    RETURN true;
EXCEPTION WHEN raise_exception OR data_exception THEN
    RETURN false;
END
$$;

DROP FUNCTION timetracker_temporal_end_qualifier(text);
DROP FUNCTION timetracker_temporal_start_qualifier(text);
DROP FUNCTION timetracker_temporal_qualifier(text);
DROP FUNCTION _timetracker_temporal_atom_qualifier(text);
DROP FUNCTION _timetracker_temporal_atom_unqualified(text);
""".strip()


class Migration(migrations.Migration):
    dependencies = [
        ("games", "0037_session_start_id_index"),
    ]

    operations = [
        migrations.RunSQL(
            sql=ADD_QUALIFIER_SUPPORT,
            reverse_sql=REMOVE_QUALIFIER_SUPPORT,
        ),
        migrations.AddField(
            model_name="game",
            name="original_release_date_end_qualifier",
            field=models.GeneratedField(
                db_persist=True,
                expression=timetracker.temporal.TemporalEndQualifier(
                    "original_release_date"
                ),
                null=True,
                output_field=models.CharField(max_length=11, null=True),
                serialize=False,
            ),
        ),
        migrations.AddField(
            model_name="game",
            name="original_release_date_qualifier",
            field=models.GeneratedField(
                db_persist=True,
                expression=timetracker.temporal.TemporalQualifierValue(
                    "original_release_date"
                ),
                null=True,
                output_field=models.CharField(max_length=11, null=True),
                serialize=False,
            ),
        ),
        migrations.AddField(
            model_name="game",
            name="original_release_date_start_qualifier",
            field=models.GeneratedField(
                db_persist=True,
                expression=timetracker.temporal.TemporalStartQualifier(
                    "original_release_date"
                ),
                null=True,
                output_field=models.CharField(max_length=11, null=True),
                serialize=False,
            ),
        ),
        migrations.AddField(
            model_name="release",
            name="release_date_end_qualifier",
            field=models.GeneratedField(
                db_persist=True,
                expression=timetracker.temporal.TemporalEndQualifier("release_date"),
                null=True,
                output_field=models.CharField(max_length=11, null=True),
                serialize=False,
            ),
        ),
        migrations.AddField(
            model_name="release",
            name="release_date_qualifier",
            field=models.GeneratedField(
                db_persist=True,
                expression=timetracker.temporal.TemporalQualifierValue("release_date"),
                null=True,
                output_field=models.CharField(max_length=11, null=True),
                serialize=False,
            ),
        ),
        migrations.AddField(
            model_name="release",
            name="release_date_start_qualifier",
            field=models.GeneratedField(
                db_persist=True,
                expression=timetracker.temporal.TemporalStartQualifier("release_date"),
                null=True,
                output_field=models.CharField(max_length=11, null=True),
                serialize=False,
            ),
        ),
    ]
