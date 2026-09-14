import json
import sys

from django.db import migrations
from django.utils import timezone

MACHINE_PREFIX = "PLAYERSESSION_CONVERSION_RECONCILIATION_JSON="
HUMAN_PREFIX = "PlayerSession conversion reconciliation:"
SUMMARY_KEYS = (
    "libraries",
    "tracked",
    "rows_total",
    "rows_unreached",
    "live_rows",
    "rows_removed_converted",
    "timed",
    "duration_only",
    "corrected",
    "running_removed",
    "notes",
    "devices",
    "sole_run",
    "contained",
    "bucket",
    "buckets_minted",
    "events_appended",
    "mismatches",
)

#: Named in the exception too.
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
    #: stderr: travels with the traceback.
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
    #: The count alone says nothing.
    named = "; ".join(
        f"{entry['code']} {entry['subject']}: {entry['detail']}"
        for entry in entries[:NAMED_IN_FAILURE]
    )
    remainder = len(entries) - NAMED_IN_FAILURE
    if remainder > 0:
        named += f"; and {remainder} more"
    raise RuntimeError(
        f"PlayerSession conversion failed with {len(mismatches)} mismatch(es): {named}"
    )


def convert_legacy_sessions(apps, schema_editor):
    """State every legacy Session as events."""
    del apps, schema_editor
    from games.backfill import playersession as conversion
    from games.models import UserLibrary

    counts = conversion.NO_COUNTS
    mismatches = []
    #: One instant for every bucket.
    minted_at = timezone.now()
    try:
        conversion.refuse_shared_game_rows()
        for library in UserLibrary.objects.order_by("pk"):
            converted = conversion.convert_library(library, minted_at=minted_at)
            counts = counts + converted
            #: A second pass appends nothing.
            repeat = conversion.convert_library(library, minted_at=minted_at)
            if repeat.events_appended:
                mismatches.append(
                    conversion.Mismatch(
                        code=conversion.MismatchCode.COUNT_DRIFT,
                        subject=str(library.pk),
                        detail=f"a second pass appended {repeat.events_appended} event(s)",
                    )
                )
            mismatches.extend(conversion.reconcile(library, converted))
        mismatches.extend(conversion.ordering_violations())
    except Exception:
        #: Emit what was counted before the rollback.
        _emit(
            counts.as_dict() | {"mismatches": len(mismatches), "aborted": 1}, mismatches
        )
        raise

    summary = counts.as_dict() | {"mismatches": len(mismatches)}
    entries = _emit(summary, mismatches)
    _fail_if_mismatched(mismatches, entries)


class Migration(migrations.Migration):
    dependencies = [("games", "0003_remove_game_playtime")]

    operations = [
        migrations.RunPython(
            convert_legacy_sessions,
            migrations.RunPython.noop,
            elidable=True,
        )
    ]
