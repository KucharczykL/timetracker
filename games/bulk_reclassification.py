"""Written-down sessions recorded as playtime, in bulk."""

import uuid
from collections.abc import Sequence
from datetime import timedelta

from django.contrib.auth.models import User
from django.db.models import QuerySet

from games.bulk_actions import (
    ActTitle,
    BulkAction,
    ChoiceValue,
    EventRows,
    PreviewColumn,
    Refused,
    Resolution,
    RowOutcome,
)
from games.bulk_narrowing import narrowed
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
IN_THE_BUCKET = (
    "A session in imported history is not one the review offers, because it "
    "must be told which playthrough its hours belong to. Move it from its own "
    "row."
)
ALREADY_RECORDED = "Some of the sessions were already recorded as historical playtime."

#: What the confirmation says about a row under the threshold, which the
#: act converts all the same: the duration suggests, and a person decides.
SHORT_ONE = (
    "One of these sessions is shorter than {hours} hours, so it may well be a "
    "single sitting rather than a total you typed in. It is recorded all the "
    "same."
)
SHORT_MANY = (
    "{count} of these sessions are shorter than {hours} hours, so they may "
    "well be single sittings rather than totals you typed in. They are "
    "recorded all the same."
)


def convertible_sessions(library: UserLibrary) -> PlayerSessionQuerySet:
    """Every live written-down row on an ordinary run.

    The act's base. No duration narrows it: a short row is noted on the
    confirmation, never left alone, because doing one at a time always
    worked and only the batch was tedious (#1357).

    A statement's filter narrows this base, never widens it.
    """
    return library_sessions(library).filter(
        timing_mode=PlayerSessionTimingMode.DURATION_ONLY,
        #: The bucket's hours name no run.
        playthrough__kind=PlaythroughKind.ORDINARY,
    )


def reviewable_sessions(library: UserLibrary) -> PlayerSessionQuerySet:
    """The rows the review suggests: convertible, and at the threshold.

    What the Library page counts and the review's filter names. The act
    reaches further; this is the suggestion, not its bound.
    """
    return convertible_sessions(library).filter(
        effective_duration__gte=timedelta(hours=REVIEW_THRESHOLD_HOURS),
    )


def conversion_scope(library: UserLibrary, filter_json: str) -> QuerySet[PlayerSession]:
    """Every convertible row, narrowed by the statement's filter."""
    return narrowed(
        convertible_sessions(library), library, filter_json, parse_session_filter
    )


def short_rows_note(rows: Sequence[PlayerSession]) -> str | None:
    """How many of these the review would not have suggested.

    None when every row is at the threshold: a note about nothing
    would teach a person to read past the ones that say something.
    """
    threshold = timedelta(hours=REVIEW_THRESHOLD_HOURS)
    short = sum(1 for row in rows if row.effective_duration < threshold)
    if not short:
        return None
    if short == 1:
        return SHORT_ONE.format(hours=REVIEW_THRESHOLD_HOURS)
    return SHORT_MANY.format(count=short, hours=REVIEW_THRESHOLD_HOURS)


def conversion_resolution(
    library: UserLibrary, keys: Sequence[uuid.UUID]
) -> Resolution[PlayerSession]:
    """Keys to rows, and to sentences."""
    wanted = list(dict.fromkeys(keys))
    #: Over every key, not only those left out.
    #: A live session beside its live record is a state no command
    #: admits, so the dispatch that met it would end the batch.
    recorded = set(
        HistoricalPlaytime.objects.filter(
            library=library, reclassified_from__in=wanted, removed_at__isnull=True
        ).values_list("reclassified_from_id", flat=True)
    )
    offered = [
        row
        for row in convertible_sessions(library)
        .filter(pk__in=wanted)
        .select_related("playthrough__player_game__game")
        .order_by("-effective_duration", "id")
        if row.pk not in recorded
    ]
    taken = {row.pk for row in offered}
    rest = [key for key in wanted if key not in taken]
    live = library_sessions(library).select_related("playthrough").in_bulk(rest)
    refused: list[Refused] = []
    for key in rest:
        row = live.get(key)
        if key in recorded:
            refused.append(Refused(str(key), ALREADY_RECORDED))
        elif row is None:
            #: Gone, or never this library's.
            refused.append(Refused(str(key), NOT_AVAILABLE, lost=True))
        elif row.playthrough.kind == PlaythroughKind.IMPORTED_HISTORY:
            refused.append(Refused(str(key), IN_THE_BUCKET))
        else:
            #: The last thing the base narrows on: a live ordinary row
            #: written down by hand is offered, whatever its length.
            refused.append(Refused(str(key), NOT_WRITTEN))
    return Resolution(tuple(offered), tuple(refused))


def convert_one(
    actor: User,
    session: PlayerSession,
    *,
    choice: ChoiceValue | None,
    idempotency_key: IdempotencyKey,
    correlation_id: uuid.UUID,
) -> RowOutcome:
    """Always moved: the resolution refused the rest."""
    reclassify_session(
        actor,
        session,
        statement_from_session(session),
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        source_metadata=_source(),
    )
    return RowOutcome.MOVED


def return_one(
    actor: User,
    session_id: uuid.UUID,
    *,
    undoes: uuid.UUID,
    idempotency_key: IdempotencyKey,
    correlation_id: uuid.UUID,
) -> RowOutcome:
    """The inverse, by key.

    A plain manager, because the row is removed by now and every
    scoped read reads that mark. The library is still stated.
    """
    return RowOutcome.of(
        undo_reclassification(
            actor,
            PlayerSession.objects.get(library=actor.library, pk=session_id),
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            source_metadata=_source(),
        )
    )


def _source() -> dict[str, object]:
    return {"bulk": {"action": RECLASSIFY.name}}


PREVIEW: tuple[PreviewColumn[PlayerSession], ...] = (
    PreviewColumn("Game", lambda row, _: row.playthrough.player_game.game.name),
    PreviewColumn("Day", lambda row, _: str(row.effective_day)),
    PreviewColumn(
        "Duration",
        lambda row, presentations: presentations.durations.format(
            row.effective_duration
        ),
        align="right",
    ),
)


RECLASSIFY = BulkAction(
    name="session.reclassify",
    label="Record as historical playtime",
    title=ActTitle(
        one="Record this session as historical playtime",
        many="Record {count} sessions as historical playtime",
    ),
    confirm_label="Record as historical playtime",
    subject="session",
    #: A move, not a removal: the hours stay.
    color="blue",
    undo_rows=EventRows(PlayerSession),
    fallback="games:list_sessions",
    scope=conversion_scope,
    resolve=conversion_resolution,
    run=convert_one,
    inverse=return_one,
    preview=PREVIEW,
    caution=short_rows_note,
)
