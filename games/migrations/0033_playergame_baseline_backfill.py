import json

from django.db import migrations
from django.utils import timezone

MACHINE_PREFIX = "PLAYERGAME_BASELINE_RECONCILIATION_JSON="
HUMAN_PREFIX = "PGAME baseline reconciliation:"
SUMMARY_KEYS = (
    "libraries",
    "games",
    "tracked",
    "created_events",
    "status_events",
    "mastered_events",
    "corrective_events",
    "unknown_effective_times",
    "skipped_tombstoned",
    "shared_games",
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
            f"PGAME baseline backfill failed with {len(mismatches)} mismatch(es)."
        )


def _summary(counts, libraries, shared_games, mismatch_count):
    return {
        "libraries": libraries,
        "games": counts.games,
        "tracked": counts.tracked,
        "created_events": counts.created_events,
        "status_events": counts.status_events,
        "mastered_events": counts.mastered_events,
        "corrective_events": counts.corrective_events,
        "unknown_effective_times": counts.unknown_effective_times,
        "skipped_tombstoned": counts.skipped_tombstoned,
        "shared_games": shared_games,
        "mismatches": mismatch_count,
    }


def backfill_playergame_baseline(apps, schema_editor):
    """Record the baseline events every library's games fold from.

    The live models and the live event machinery, deliberately: historical
    models cannot run a projector or validate a payload, so an apps.get_model
    backfill would have to write events and projection rows by hand, and that
    is a second event writer. The cost is that this migration is pinned to the
    application as it stands when it runs, and the reconciliation below is what
    keeps a future incompatibility loud.
    """
    del apps, schema_editor
    from games.backfill.playergame import (
        NO_COUNTS,
        Mismatch,
        backfill_library,
        reconcile,
        unmapped_statuses,
    )
    from games.models import Game, UserLibrary

    run_time = timezone.now()
    libraries = list(UserLibrary.objects.order_by("pk"))
    shared_games = Game.objects.filter(library__isnull=True).count()

    #: Pre-flight, so an unmapped letter is a report rather than a KeyError.
    mismatches = [
        mismatch for library in libraries for mismatch in unmapped_statuses(library)
    ]
    if mismatches:
        _emit(
            _summary(NO_COUNTS, len(libraries), shared_games, len(mismatches)),
            mismatches,
        )
        _fail_if_mismatched(mismatches)

    counts = NO_COUNTS
    for library in libraries:
        counts = counts + backfill_library(library, run_time=run_time)
        #: A second pass appends nothing, and proves it by counting nothing.
        repeat = backfill_library(library, run_time=run_time)
        drifted = (
            repeat.created_events
            + repeat.status_events
            + repeat.mastered_events
            + repeat.corrective_events
        )
        if drifted:
            mismatches.append(
                Mismatch(
                    code="count_drift",
                    game_id=str(library.pk),
                    detail=f"a second pass appended {drifted} event(s)",
                )
            )
        mismatches.extend(reconcile(library))

    _emit(
        _summary(counts, len(libraries), shared_games, len(mismatches)),
        mismatches,
    )
    _fail_if_mismatched(mismatches)


class Migration(migrations.Migration):
    dependencies = [("games", "0032_playergame_archived_at")]

    operations = [
        migrations.RunPython(
            backfill_playergame_baseline,
            migrations.RunPython.noop,
            elidable=True,
        )
    ]
