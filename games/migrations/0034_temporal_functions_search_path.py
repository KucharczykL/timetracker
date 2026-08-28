from django.db import migrations

# 0017 created these functions without a search_path of their own, and every
# body calls its helpers by bare name. `pg_dump` opens each dump it writes with
# an empty search_path, so during a restore those calls found nothing, and the
# handler below read the failure as invalid data: the domain rejected every
# value the dump carried. No dump of this schema could be restored.
#
# Fixing the reach is one setting per function. Fixing the silence is narrowing
# the handler to the two classes invalid data actually raises - a helper out of
# reach now stops the statement instead of answering for it.
#
# This changes no verdict a working search_path produces, so neither the stored
# values nor the generated columns over them need rebuilding: what they hold is
# what these functions still answer.

FUNCTION_NAMES = (
    "_timetracker_temporal_atom_precision",
    "_timetracker_temporal_atom_lower",
    "_timetracker_temporal_atom_upper",
    "timetracker_temporal_lower",
    "timetracker_temporal_upper",
    "timetracker_temporal_kind",
    "timetracker_temporal_precision",
    "timetracker_temporal_start_kind",
    "timetracker_temporal_end_kind",
    "timetracker_temporal_start_precision",
    "timetracker_temporal_end_precision",
    "timetracker_temporal_is_valid",
)
SEARCH_PATH = "pg_catalog, public"


def _is_valid_function(handler: str, search_path: str | None) -> str:
    setting = "" if search_path is None else f"SET search_path = {search_path}\n"
    return f"""
CREATE OR REPLACE FUNCTION timetracker_temporal_is_valid(value text)
RETURNS boolean
LANGUAGE plpgsql
IMMUTABLE
{setting}AS $$
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
EXCEPTION WHEN {handler} THEN
    RETURN false;
END
$$;
""".strip()


# A CREATE OR REPLACE carries every property of the function it writes, so the
# statement above sets its own search_path and the loop below sets the rest.
def _statements(is_valid: str, setting: str) -> str:
    return "\n".join(
        [
            is_valid,
            *(f"ALTER FUNCTION {name}(text) {setting};" for name in FUNCTION_NAMES),
        ]
    )


REACH_THE_HELPERS = _statements(
    _is_valid_function("raise_exception OR data_exception", SEARCH_PATH),
    f"SET search_path = {SEARCH_PATH}",
)
LEAVE_THE_HELPERS_UNREACHED = _statements(
    _is_valid_function("OTHERS", None),
    "RESET search_path",
)


class Migration(migrations.Migration):
    dependencies = [
        ("games", "0033_playergame_baseline_backfill"),
    ]

    operations = [
        migrations.RunSQL(
            sql=REACH_THE_HELPERS,
            reverse_sql=LEAVE_THE_HELPERS_UNREACHED,
        ),
    ]
