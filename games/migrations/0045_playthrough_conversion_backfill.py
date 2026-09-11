import json
import sys

from django.db import migrations

MACHINE_PREFIX = "PLAYTHROUGH_CONVERSION_RECONCILIATION_JSON="
HUMAN_PREFIX = "Playthrough conversion reconciliation:"
SUMMARY_KEYS = (
    "libraries",
    "tracked",
    "tracked_on_removed_game",
    "rows_total",
    "rows_unreached",
    "live_rows",
    "rows_removed_converted",
    "clean_both",
    "clean_start_only",
    "clean_end_only",
    "no_known_endpoint",
    "reversed_endpoints",
    "runs_converted",
    "runs_default",
    "runs_default_present",
    "notes",
    "endpoints_paired",
    "endpoints_ambiguous",
    "endpoints_absent",
    "endpoints_dayless",
    "unclaimed_events",
    "status_events_undated",
    "events_appended",
    "mismatches",
)

#: Named in the exception, so a lost stdout still says what broke.
NAMED_IN_FAILURE = 3


def _emit(summary, mismatches):
    entries = sorted(
        (mismatch.as_dict() for mismatch in mismatches),
        key=lambda entry: (entry["code"], entry["subject"], entry["detail"]),
    )
    payload = {
        "schema_version": 1,
        "summary": summary,
        "mismatches": entries,
    }
    #: stderr, so the machine line travels with the traceback
    #: rather than on a stream a quiet migrate may discard.
    print(
        MACHINE_PREFIX + json.dumps(payload, sort_keys=True, separators=(",", ":")),
        file=sys.stderr,
    )
    print(
        HUMAN_PREFIX
        + " "
        + " ".join(f"{key}={summary.get(key, 0)}" for key in SUMMARY_KEYS)
    )
    for entry in entries:
        print(f"  {entry['code']} subject={entry['subject']} {entry['detail']}")
    return entries


def _fail_if_mismatched(mismatches, entries):
    if not mismatches:
        return
    #: The count alone would say nothing on the one occasion
    #: this message is read, and stdout may not have survived.
    named = "; ".join(
        f"{entry['code']} {entry['subject']}: {entry['detail']}"
        for entry in entries[:NAMED_IN_FAILURE]
    )
    remainder = len(entries) - NAMED_IN_FAILURE
    if remainder > 0:
        named += f"; and {remainder} more"
    raise RuntimeError(
        f"Playthrough conversion failed with {len(mismatches)} mismatch(es): {named}"
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
    try:
        for library in UserLibrary.objects.order_by("pk"):
            converted = conversion.convert_library(library)
            counts = counts + converted
            #: Check 5: a second pass appends nothing.
            repeat = conversion.convert_library(library)
            if repeat.events_appended:
                mismatches.append(
                    conversion.Mismatch(
                        code=conversion.MismatchCode.COUNT_DRIFT,
                        subject=str(library.pk),
                        detail=f"a second pass appended {repeat.events_appended} event(s)",
                    )
                )
            if converted.rows_unreached:
                mismatches.append(
                    conversion.Mismatch(
                        code=conversion.MismatchCode.ROWS_UNREACHED,
                        subject=str(library.pk),
                        detail=f"{converted.rows_unreached} legacy row(s) in scope "
                        "the walk did not convert",
                    )
                )
            mismatches.extend(conversion.reconcile(library))
        mismatches.extend(conversion.ordering_violations())
    except Exception:
        #: The walk carries a play_event_id into every event's
        #: metadata so a failure can be traced, and the rollback
        #: takes all of it. What is counted so far says how far
        #: the run got, which the traceback alone does not.
        _emit(
            counts.as_dict() | {"mismatches": len(mismatches), "aborted": 1}, mismatches
        )
        raise

    summary = counts.as_dict() | {"mismatches": len(mismatches)}
    entries = _emit(summary, mismatches)
    _fail_if_mismatched(mismatches, entries)


class Migration(migrations.Migration):
    dependencies = [("games", "0044_playthrough_endpoint_columns")]

    operations = [
        migrations.RunPython(
            migrations.RunPython.noop,
            migrations.RunPython.noop,
            elidable=True,
        )
    ]
