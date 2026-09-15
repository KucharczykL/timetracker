from django.db import migrations
from django.utils import timezone

MACHINE_PREFIX = "PLAYERSESSION_CONVERSION_RECONCILIATION_JSON="
HUMAN_PREFIX = "PlayerSession conversion reconciliation:"
FAILURE_SUBJECT = "PlayerSession conversion"
#: Pinned to ConversionCounts' fields by a test.
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


def convert_legacy_sessions(apps, schema_editor):
    """State every legacy Session as events."""
    del apps, schema_editor
    from games.backfill import playersession as conversion
    from games.backfill.reporting import (
        ReportPrefixes,
        emit_report,
        failure_sentence,
    )
    from games.models import UserLibrary

    prefixes = ReportPrefixes(machine=MACHINE_PREFIX, human=HUMAN_PREFIX)
    counts = conversion.NO_COUNTS
    mismatches = []
    #: One instant for every bucket.
    minted_at = timezone.now()
    try:
        conversion.refuse_shared_game_rows()
        for library in UserLibrary.objects.only(*conversion.LIBRARY_FIELDS).order_by(
            "pk"
        ):
            converted = conversion.convert_library(library, minted_at=minted_at)
            counts = counts + converted
            #: A second pass appends and mints nothing.
            repeat = conversion.convert_library(library, minted_at=minted_at)
            if repeat.events_appended or repeat.buckets_minted:
                mismatches.append(
                    conversion.Mismatch(
                        code=conversion.MismatchCode.COUNT_DRIFT,
                        subject=str(library.pk),
                        detail=f"a second pass appended {repeat.events_appended} "
                        f"event(s) and minted {repeat.buckets_minted} bucket(s)",
                    )
                )
            mismatches.extend(conversion.reconcile(library, converted))
        mismatches.extend(conversion.ordering_violations())
    except Exception:
        #: Emit what was counted before the rollback.
        emit_report(
            counts.as_dict() | {"mismatches": len(mismatches), "aborted": 1},
            mismatches,
            prefixes=prefixes,
            summary_keys=SUMMARY_KEYS,
        )
        raise

    entries = emit_report(
        counts.as_dict() | {"mismatches": len(mismatches)},
        mismatches,
        prefixes=prefixes,
        summary_keys=SUMMARY_KEYS,
    )
    sentence = failure_sentence(entries, subject=FAILURE_SUBJECT)
    if sentence is not None:
        raise RuntimeError(sentence)


class Migration(migrations.Migration):
    dependencies = [("games", "0003_remove_game_playtime")]

    operations = [
        migrations.RunPython(
            convert_legacy_sessions,
            migrations.RunPython.noop,
            elidable=True,
        )
    ]
