"""State every library's calendar once, and refuse to commit a wrong one."""

import uuid
from datetime import datetime
from enum import StrEnum

from django.db import transaction
from django.db.models import Count

from games.backfill.appending import append_one
from games.backfill.mismatch import Mismatch
from games.backfill.playersession import display_zone_name
from games.events.calendar import calendar_day_zone_changed
from games.events.rebuild import RebuildMode, rebuild_projections
from games.models import (
    LibraryCalendar,
    PlayerGame,
    PlayerSession,
    PlayerSessionTimingMode,
    Playthrough,
    ProjectionModel,
    UserLibrary,
)

CALENDAR_ISSUE = 1047
KEY_PREFIX = f"backfill:{CALENDAR_ISSUE}:calendar"

#: The projection tables migration 0005's schema holds.
PROJECTIONS_AT_0005: tuple[type[ProjectionModel], ...] = (
    LibraryCalendar,
    PlayerGame,
    PlayerSession,
    Playthrough,
)


class CalendarMismatchCode(StrEnum):
    """Every reason the seed refuses to commit."""

    CALENDAR_MISSING = "calendar_missing"
    ROW_ZONE = "row_zone"
    SEED_DRIFT = "seed_drift"
    REPLAY_DIFFERS = "replay_differs"


def seed_library(library: UserLibrary, *, minted_at: datetime) -> bool:
    """State the owner's display zone as the calendar; true when appended.

    The zone #700 seeded every session row with, so the projector's
    rewrite changes no day. The key replays as a no-op on a second pass.
    """
    zone = display_zone_name(library)
    with transaction.atomic():
        return append_one(
            library,
            calendar_day_zone_changed(library.pk, zone),
            actor=library.user,
            idempotency_key=f"{KEY_PREFIX}:day_zone:{library.pk}",
            command_input={"day_zone": zone},
            recorded_at=minted_at,
            correlation_id=uuid.uuid7(),
            source_metadata={"origin": "backfill", "issue": CALENDAR_ISSUE},
        )


def calendar_mismatches(library: UserLibrary) -> list[Mismatch[CalendarMismatchCode]]:
    """Every row's zone is the calendar's, and a replay reproduces it."""
    mismatches: list[Mismatch[CalendarMismatchCode]] = []
    calendar = LibraryCalendar.objects.filter(library=library).only("day_zone").first()
    if calendar is None:
        return [
            Mismatch(
                code=CalendarMismatchCode.CALENDAR_MISSING,
                subject=str(library.pk),
                detail="the seed left no calendar row",
            )
        ]
    off_calendar = (
        PlayerSession.objects.filter(
            library=library,
            timing_mode__in=(
                PlayerSessionTimingMode.TIMED,
                PlayerSessionTimingMode.CORRECTED,
            ),
        )
        .exclude(day_zone=calendar.day_zone)
        .values("day_zone")
        .annotate(rows=Count("id"))
        .order_by("day_zone")
    )
    mismatches.extend(
        Mismatch(
            code=CalendarMismatchCode.ROW_ZONE,
            subject=str(library.pk),
            detail=f"{group['rows']} row(s) state {group['day_zone']!r}, the "
            f"calendar {calendar.day_zone!r}",
        )
        for group in off_calendar
    )
    report = rebuild_projections(
        library, mode=RebuildMode.CHECK, models=PROJECTIONS_AT_0005
    )
    mismatches.extend(
        Mismatch(
            code=CalendarMismatchCode.REPLAY_DIFFERS,
            subject=table.table,
            detail=f"only_live={table.only_live} only_rebuilt={table.only_rebuilt} "
            f"differing={table.differing} sample={list(table.sample)}",
        )
        for table in report.tables
        if table.only_live or table.only_rebuilt or table.differing
    )
    if report.head_at_diff != report.replayed_through:
        mismatches.append(
            Mismatch(
                code=CalendarMismatchCode.REPLAY_DIFFERS,
                subject=str(library.pk),
                detail=f"replayed through {report.replayed_through}, the head "
                f"stood at {report.head_at_diff}",
            )
        )
    return mismatches
