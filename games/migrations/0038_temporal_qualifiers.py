from django.db import migrations

# A qualifier says how sure the writer is of a date. It does not say which days
# the value covers, so `1984~` projects the bounds and the precision of `1984`.
#
# This widens the grammar. No stored string can carry a symbol -- the domain
# refused one until now -- so every value the schema holds still parses to the
# verdict it parsed to before. The domain constraint therefore stays and the
# persisted generated columns are not rebuilt, on the same reasoning 0034
# recorded for the same shape of change.
#
# The reverse below exists for the test suite, which drives the executor down
# past this node in twenty modules. No deployment reverses it.
#
# A reverse does not revalidate what the schema already holds, on the same
# reasoning as above. A row written as `1984~` therefore survives the reverse,
# and its stored projections with it, but the domain no longer accepts the
# string: the next UPDATE of that row raises `invalid temporal atom: 1984~`,
# and the column cannot be retyped out of the way while a generated column
# reads it. Restate the value before reversing, or do not reverse.

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


# The four bodies below are the 0017 forms carrying the 0034 search_path and the
# 0034 exception handler. Restore them before dropping what they would call.
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
    ]
