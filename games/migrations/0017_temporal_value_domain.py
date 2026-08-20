from django.db import migrations

CREATE_TEMPORAL_VALUE_DOMAIN = r"""
CREATE FUNCTION _timetracker_temporal_atom_precision(value text)
RETURNS text
LANGUAGE plpgsql
IMMUTABLE
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

CREATE FUNCTION _timetracker_temporal_atom_lower(value text)
RETURNS date
LANGUAGE plpgsql
IMMUTABLE
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

CREATE FUNCTION _timetracker_temporal_atom_upper(value text)
RETURNS date
LANGUAGE plpgsql
IMMUTABLE
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

CREATE FUNCTION timetracker_temporal_lower(value text)
RETURNS date
LANGUAGE plpgsql
IMMUTABLE
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

CREATE FUNCTION timetracker_temporal_upper(value text)
RETURNS date
LANGUAGE plpgsql
IMMUTABLE
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

CREATE FUNCTION timetracker_temporal_kind(value text)
RETURNS text
LANGUAGE plpgsql
IMMUTABLE
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

CREATE FUNCTION timetracker_temporal_precision(value text)
RETURNS text
LANGUAGE plpgsql
IMMUTABLE
AS $$
BEGIN
    PERFORM timetracker_temporal_lower(value);
    IF value IS NULL OR strpos(value, '/') > 0 THEN
        RETURN NULL;
    END IF;
    RETURN _timetracker_temporal_atom_precision(value);
END
$$;

CREATE FUNCTION timetracker_temporal_start_kind(value text)
RETURNS text
LANGUAGE plpgsql
IMMUTABLE
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

CREATE FUNCTION timetracker_temporal_end_kind(value text)
RETURNS text
LANGUAGE plpgsql
IMMUTABLE
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

CREATE FUNCTION timetracker_temporal_start_precision(value text)
RETURNS text
LANGUAGE plpgsql
IMMUTABLE
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

CREATE FUNCTION timetracker_temporal_end_precision(value text)
RETURNS text
LANGUAGE plpgsql
IMMUTABLE
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

CREATE FUNCTION timetracker_temporal_is_valid(value text)
RETURNS boolean
LANGUAGE plpgsql
IMMUTABLE
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
EXCEPTION WHEN OTHERS THEN
    RETURN false;
END
$$;

CREATE DOMAIN temporal_value AS varchar(64)
CONSTRAINT temporal_value_valid
CHECK (VALUE IS NULL OR timetracker_temporal_is_valid(VALUE));
""".strip()


DROP_TEMPORAL_VALUE_DOMAIN = """
DROP DOMAIN temporal_value;
DROP FUNCTION timetracker_temporal_is_valid(text);
DROP FUNCTION timetracker_temporal_end_precision(text);
DROP FUNCTION timetracker_temporal_start_precision(text);
DROP FUNCTION timetracker_temporal_end_kind(text);
DROP FUNCTION timetracker_temporal_start_kind(text);
DROP FUNCTION timetracker_temporal_precision(text);
DROP FUNCTION timetracker_temporal_kind(text);
DROP FUNCTION timetracker_temporal_upper(text);
DROP FUNCTION timetracker_temporal_lower(text);
DROP FUNCTION _timetracker_temporal_atom_upper(text);
DROP FUNCTION _timetracker_temporal_atom_lower(text);
DROP FUNCTION _timetracker_temporal_atom_precision(text);
""".strip()


class Migration(migrations.Migration):
    dependencies = [
        ("games", "0016_library_config_uuid_primary_key"),
    ]

    operations = [
        migrations.RunSQL(
            sql=CREATE_TEMPORAL_VALUE_DOMAIN,
            reverse_sql=DROP_TEMPORAL_VALUE_DOMAIN,
        ),
    ]
