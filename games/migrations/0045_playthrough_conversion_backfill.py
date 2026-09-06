import json

from django.db import migrations

MACHINE_PREFIX = "PLAYTHROUGH_CONVERSION_RECONCILIATION_JSON="
HUMAN_PREFIX = "Playthrough conversion reconciliation:"
SUMMARY_KEYS = (
    "libraries",
    "tracked",
    "tracked_on_removed_game",
    "live_rows",
    "rows_removed_converted",
    "runs_converted",
    "runs_default",
    "notes",
    "endpoints_paired",
    "endpoints_fresh",
    "endpoints_dayless",
    "events_appended",
    "mismatches",
)


def _emit(summary, mismatches):
    entries = sorted(
        (mismatch.as_dict() for mismatch in mismatches),
        key=lambda entry: (entry["code"], entry["game_id"], entry["detail"]),
    )
    payload = {
        "schema_version": 1,
        "summary": summary,
        "mismatches": entries,
    }
    print(MACHINE_PREFIX + json.dumps(payload, sort_keys=True, separators=(",", ":")))
    print(
        HUMAN_PREFIX + " " + " ".join(f"{key}={summary[key]}" for key in SUMMARY_KEYS)
    )
    for entry in entries:
        print(f"  {entry['code']} game={entry['game_id']} {entry['detail']}")


def _fail_if_mismatched(mismatches):
    if mismatches:
        raise RuntimeError(
            f"Playthrough conversion failed with {len(mismatches)} mismatch(es)."
        )


def convert_legacy_playevents(apps, schema_editor):
    """State every legacy row as Playthrough events.

    The live models and machinery, for the reason 0033 records:
    historical models cannot run a projector or validate a
    payload, so writing events and rows by hand is a second event
    writer. This migration is therefore pinned to the application
    as it stands, and the gate keeps that loud.
    """
    del apps, schema_editor
    from games.backfill import playthrough as conversion
    from games.models import UserLibrary

    counts = conversion.NO_COUNTS
    mismatches = []
    for library in UserLibrary.objects.order_by("pk"):
        counts = counts + conversion.convert_library(library)
        #: Check 5: a second pass appends nothing.
        repeat = conversion.convert_library(library)
        if repeat.events_appended:
            mismatches.append(
                conversion.Mismatch(
                    code="count_drift",
                    game_id=str(library.pk),
                    detail=f"a second pass appended {repeat.events_appended} event(s)",
                )
            )
        mismatches.extend(conversion.reconcile(library))
    mismatches.extend(conversion.ordering_violations())

    summary = counts.as_dict() | {"mismatches": len(mismatches)}
    _emit(summary, mismatches)
    _fail_if_mismatched(mismatches)


class Migration(migrations.Migration):
    dependencies = [("games", "0044_playthrough_endpoint_columns")]

    operations = [
        migrations.RunPython(
            convert_legacy_playevents,
            migrations.RunPython.noop,
            elidable=True,
        )
    ]
