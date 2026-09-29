"""Game detail's Library section: one summary row per copy."""

from common.components import SummaryAction, SummaryRow
from common.components.core import Node
from common.date_time_presentation import DateTimePresentation
from common.returns import OriginUrl, action_url
from common.temporal_presentation import present_temporal_value
from games.end_ways import END_WAY_LABELS
from games.endpoints import ENTRY_ACCESS_END
from games.models import EntryAccess, EntryFormat, Game, LibraryEntry, UserLibrary
from games.reads.endpoints import stated, way_of
from games.reads.entries import game_entries
from games.reads.releases import UNSPECIFIED_PLATFORM, game_releases

EMPTY_LIBRARY = "Nothing in your library yet."


def release_words(entry: LibraryEntry) -> str:
    """Platform, then a named edition."""
    release = entry.release
    parts = [
        UNSPECIFIED_PLATFORM if release.platform is None else release.platform.name
    ]
    if release.edition.name:
        parts.append(release.edition.name)
    return " · ".join(parts)


def _facts(entry: LibraryEntry, presentation: DateTimePresentation) -> str:
    """Access, format, since when, and how it left."""
    parts = [EntryAccess(entry.access).label, EntryFormat(entry.format).label]
    if entry.acquired is not None:
        parts.append(f"since {present_temporal_value(entry.acquired, presentation)}")
    ended = stated(entry, ENTRY_ACCESS_END)
    if ended is not None:
        words = END_WAY_LABELS[way_of(ended)]
        if ended.when is not None:
            words = f"{words} {present_temporal_value(ended.when, presentation)}"
        parts.append(words)
    return " · ".join(parts)


def copy_actions(entry: LibraryEntry, origin: OriginUrl | None) -> list[SummaryAction]:
    """Each act a page; an ended copy's end is edited or resumed."""
    ended = stated(entry, ENTRY_ACCESS_END) is not None
    return [
        SummaryAction(
            "Edit", action_url("games:edit_library_entry", entry.pk, origin=origin)
        ),
        *(
            [
                SummaryAction(
                    "Edit end",
                    action_url("games:edit_library_entry_end", entry.pk, origin=origin),
                ),
                SummaryAction(
                    "Resume",
                    action_url("games:resume_library_entry", entry.pk, origin=origin),
                ),
            ]
            if ended
            else [
                SummaryAction(
                    "End access",
                    action_url("games:end_library_entry", entry.pk, origin=origin),
                )
            ]
        ),
        SummaryAction(
            "Remove",
            action_url("games:remove_library_entry", entry.pk, origin=origin),
        ),
    ]


def copy_rows(
    game: Game,
    library: UserLibrary,
    presentation: DateTimePresentation,
    origin: OriginUrl,
) -> list[Node]:
    """One row per live copy, earliest acquired first."""
    entries = (
        game_entries(library, game)
        .select_related("release__edition", "release__platform", "player_game__game")
        .order_by("acquired_lower", "created_at", "id")
    )
    return [
        SummaryRow(
            label=release_words(entry),
            subtitle=_facts(entry, presentation),
            actions=copy_actions(entry, origin),
            detail=entry.note or None,
        )
        for entry in entries
    ]


def library_add_url(game: Game, library: UserLibrary, origin: OriginUrl) -> str | None:
    """None where a shared game holds no Release to add."""
    if game.library_id is None and not game_releases(library, game).exists():
        return None
    return action_url("games:add_library_entry", game.pk, origin=origin)
