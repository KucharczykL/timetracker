import json
import sys

from django.db import migrations

MACHINE_PREFIX = "PLAYTHROUGH_START_REPAIR_JSON="
HUMAN_PREFIX = "Playthrough start repair:"
SUMMARY_KEYS = (
    "libraries",
    "runs_in_scope",
    "no_evidence",
    "status_only",
    "session_only",
    "both",
    "both_agree",
    "from_status",
    "from_session",
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
        f"Playthrough start repair failed with {len(mismatches)} mismatch(es): {named}"
    )


def repair_playthrough_starts(apps, schema_editor):
    """State a start for the runs #684 left empty.

    The live models and machinery, for the reason 0033 records:
    historical models cannot run a projector or validate a
    payload, so writing events and rows by hand is a second event
    writer. This migration is therefore pinned to the application
    as it stands, and the gate keeps that loud.
    """
    del apps, schema_editor
    from games.backfill import playthrough as conversion
    from games.backfill import playthrough_start as repair
    from games.models import UserLibrary

    counts = repair.NO_START_COUNTS
    mismatches = []
    try:
        for library in UserLibrary.objects.order_by("pk"):
            before = repair.snapshot(library)
            result = repair.repair_library(library)
            counts = counts + result.counts
            mismatches.extend(repair.gate(library, before, result))
            #: Check 5: a second pass appends nothing.
            again = repair.repair_library(library)
            if again.counts.events_appended:
                mismatches.append(
                    repair.Mismatch(
                        code=repair.StartMismatchCode.COUNT_DRIFT,
                        subject=str(library.pk),
                        detail=f"a second pass appended "
                        f"{again.counts.events_appended} event(s)",
                    )
                )
            #: Check 7: #684's own gate still answers clean.
            mismatches.extend(conversion.reconcile(library))
        mismatches.extend(conversion.ordering_violations())
    except Exception:
        #: The rollback takes every event. What is counted so far
        #: says how far the run got, which a traceback does not.
        _emit(
            counts.as_dict() | {"mismatches": len(mismatches), "aborted": 1},
            mismatches,
        )
        raise

    summary = counts.as_dict() | {"mismatches": len(mismatches)}
    entries = _emit(summary, mismatches)
    _fail_if_mismatched(mismatches, entries)


class Migration(migrations.Migration):
    dependencies = [("games", "0047_playthrough_preset_completed")]

    operations = [
        migrations.RunPython(
            repair_playthrough_starts,
            #: Append-only: a rollback cannot take an event back.
            migrations.RunPython.noop,
            elidable=True,
        )
    ]
