"""Recording written-down sessions as historical playtime, in bulk.

The act's own half: which rows the review offers, which it refuses and
why, and how one row is converted and returned. The table in
`games/bulk_actions.py` names them; `games/views/bulk.py` runs them.
"""

import uuid
from collections.abc import Sequence
from datetime import timedelta

from django.contrib.auth.models import User
from django.db.models import QuerySet

from games.bulk_actions import BulkAction, Cardinality, Refused, Resolution
from games.commands.session_reclassification import statement_from_session
from games.events.idempotency import IdempotencyKey
from games.filters import parse_session_filter
from games.models import (
    HistoricalPlaytime,
    PlayerSession,
    PlayerSessionQuerySet,
    PlayerSessionTimingMode,
    PlaythroughKind,
    UserLibrary,
)
from games.reads.player_sessions import library_sessions
from games.writes.playersession import reclassify_session, undo_reclassification

#: Longer than a sitting a person recalls.
REVIEW_THRESHOLD_HOURS = 8

NOT_WRITTEN = (
    "A session whose time the app measured is not one the review offers, so "
    "it was left as it is."
)
NOT_AVAILABLE = "One of the sessions is no longer available, so it was left as it is."
UNDER_THRESHOLD = (
    f"A session shorter than {REVIEW_THRESHOLD_HOURS} hours is not one the "
    "review offers, so it was left as it is."
)
IN_THE_BUCKET = (
    "A session in imported history is not one the review offers, because it "
    "must be told which playthrough its hours belong to. Move it from its own "
    "row."
)
ALREADY_RECORDED = "Some of the sessions were already recorded as historical playtime."


def reviewable_sessions(library: UserLibrary) -> PlayerSessionQuerySet:
    """Live written-down rows at the threshold.

    Three rules, and one of them no filter field can state: the bucket
    is told apart by its run's kind, which `PlayerSessionFilter` does
    not carry. That is why this is the scope's base rather than
    something a filter could express.
    """
    return library_sessions(library).filter(
        timing_mode=PlayerSessionTimingMode.DURATION_ONLY,
        effective_duration__gte=timedelta(hours=REVIEW_THRESHOLD_HOURS),
        #: The bulk act cannot ask for a run.
        playthrough__kind=PlaythroughKind.ORDINARY,
    )


def review_scope(library: UserLibrary, filter_json: str) -> QuerySet[PlayerSession]:
    """The review, narrowed by what the statement's filter says.

    The filter narrows this base and never replaces it, and an
    unreadable one raises rather than being dropped: a dropped filter
    widens an act, where on a list it only widens a page.
    """
    rows = reviewable_sessions(library)
    parsed = parse_session_filter(filter_json) if filter_json else None
    if parsed is None:
        return rows
    return rows.filter(parsed.to_q())


def review_resolution(library: UserLibrary, keys: Sequence[uuid.UUID]) -> Resolution:
    """Sort keys into the rows the review offers, and sentences."""
    wanted = list(dict.fromkeys(keys))
    offered = list(
        reviewable_sessions(library)
        .filter(pk__in=wanted)
        .select_related("playthrough__player_game__game")
        .order_by("-effective_duration", "id")
    )
    taken = {row.pk for row in offered}
    rest = [key for key in wanted if key not in taken]
    recorded = set(
        HistoricalPlaytime.objects.filter(
            library=library, reclassified_from__in=rest, removed_at__isnull=True
        ).values_list("reclassified_from_id", flat=True)
    )
    live = library_sessions(library).select_related("playthrough").in_bulk(rest)
    refused: list[Refused] = []
    for key in rest:
        row = live.get(key)
        if key in recorded:
            refused.append(Refused(str(key), ALREADY_RECORDED))
        elif row is None:
            #: Gone, or never this library's: either way nothing to act on.
            refused.append(Refused(str(key), NOT_AVAILABLE, lost=True))
        elif row.playthrough.kind == PlaythroughKind.IMPORTED_HISTORY:
            refused.append(Refused(str(key), IN_THE_BUCKET))
        elif row.timing_mode != PlayerSessionTimingMode.DURATION_ONLY:
            refused.append(Refused(str(key), NOT_WRITTEN))
        else:
            refused.append(Refused(str(key), UNDER_THRESHOLD))
    return Resolution(tuple(offered), tuple(refused))


def convert_one(
    actor: User,
    session: PlayerSession,
    idempotency_key: IdempotencyKey,
    correlation_id: uuid.UUID,
) -> None:
    reclassify_session(
        actor,
        session,
        statement_from_session(session),
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        source_metadata=_source(),
    )


def return_one(actor: User, session_id: uuid.UUID, correlation_id: uuid.UUID) -> None:
    """The inverse, by key: the row it names is removed by now."""
    undo_reclassification(
        actor,
        PlayerSession.objects.get(library=actor.library, pk=session_id),
        correlation_id=correlation_id,
        source_metadata=_source(),
    )


def _source() -> dict[str, object]:
    return {"bulk": {"action": RECLASSIFY.name}}


RECLASSIFY = BulkAction.on(
    name="session.reclassify",
    label="Record as historical playtime",
    title="Record these sessions as historical playtime",
    confirm_label="Record as historical playtime",
    subject="session",
    cardinality=Cardinality.MANY,
    inverse_aggregate="playersession",
    fallback="games:list_sessions",
    scope=review_scope,
    resolve=review_resolution,
    run=convert_one,
    inverse=return_one,
)
