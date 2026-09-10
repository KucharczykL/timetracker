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
    "both_off_by_one",
    "from_status",
    "from_session",
    "events_appended",
    "preexisting",
    "mismatches",
    #: One only where the pass raised part way.
    "aborted",
)

#: Named in the exception, for a lost stdout.
NAMED_IN_FAILURE = 3


def _emit(summary, mismatches, standing=()):
    entries = sorted(
        (mismatch.as_dict() for mismatch in mismatches),
        key=lambda entry: (entry["code"], entry["subject"], entry["detail"]),
    )
    #: Named, not counted alone: a number says
    #: nothing about which mismatch already stood.
    standing_entries = [
        {"code": str(code), "subject": subject, "detail": detail}
        for code, subject, detail in sorted(standing)
    ]
    payload = {
        "schema_version": 1,
        "summary": summary,
        "mismatches": entries,
        "preexisting_named": standing_entries,
    }
    #: stderr, so it travels with the traceback.
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
    for entry in standing_entries[:NAMED_IN_FAILURE]:
        print(
            f"  standing {entry['code']} subject={entry['subject']} {entry['detail']}"
        )
    remainder = len(standing_entries) - NAMED_IN_FAILURE
    if remainder > 0:
        print(f"  and {remainder} more standing mismatch(es)")
    return entries


def _keys(mismatches):
    return {
        (mismatch.code, mismatch.subject, mismatch.detail) for mismatch in mismatches
    }


def _fail_if_mismatched(mismatches, entries):
    if not mismatches:
        return
    #: A count alone would say nothing here.
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
    """State a start for the empty runs.

    The live models, for the reason 0033 records: a
    historical model runs no projector and validates
    no payload, so writing rows by hand would be a
    second event writer.
    """
    del apps, schema_editor
    from games.backfill import playthrough as conversion
    from games.backfill import playthrough_start as repair
    from games.models import UserLibrary

    counts = repair.NO_START_COUNTS
    mismatches = []
    #: Only a mismatch this pass adds fails it.
    #: A start a person stated after the conversion
    #: reads to #684's gate as a run owing a legacy
    #: row it never had, which is #684's to answer.
    preexisting = 0
    standing_named = []
    try:
        standing_order = _keys(conversion.ordering_violations())
        preexisting += len(standing_order)
        standing_named.extend(sorted(standing_order))
        for library in UserLibrary.objects.order_by("pk"):
            standing = _keys(conversion.reconcile(library))
            preexisting += len(standing)
            standing_named.extend(sorted(standing))
            before = repair.snapshot(library)
            result = repair.repair_library(library)
            counts = counts + result.counts
            mismatches.extend(repair.gate(library, before, result))
            #: Check 7: #684's gate reports nothing new.
            mismatches.extend(
                mismatch
                for mismatch in conversion.reconcile(library)
                if (mismatch.code, mismatch.subject, mismatch.detail) not in standing
            )
        mismatches.extend(
            mismatch
            for mismatch in conversion.ordering_violations()
            if (mismatch.code, mismatch.subject, mismatch.detail) not in standing_order
        )
    except Exception:
        #: What is counted says how far it got. The
        #: library that raised counts nothing at all:
        #: repair_library answers counts or raises,
        #: so its part pass leaves no number behind.
        _emit(
            counts.as_dict()
            | {
                "mismatches": len(mismatches),
                "preexisting": preexisting,
                "aborted": 1,
            },
            mismatches,
            standing_named,
        )
        raise

    summary = counts.as_dict() | {
        "mismatches": len(mismatches),
        "preexisting": preexisting,
    }
    entries = _emit(summary, mismatches, standing_named)
    _fail_if_mismatched(mismatches, entries)


class Migration(migrations.Migration):
    dependencies = [("games", "0047_playthrough_preset_completed")]

    operations = [
        migrations.RunPython(
            repair_playthrough_starts,
            #: Append-only: no rollback takes events back.
            migrations.RunPython.noop,
            elidable=True,
        )
    ]
