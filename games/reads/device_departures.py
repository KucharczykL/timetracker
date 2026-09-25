"""Sessions still naming a removed device."""

from django.db.models import OuterRef, QuerySet

from games.models import Device, PlayerSession, UserLibrary
from games.reads.game_departures import counted
from games.reads.player_sessions import library_sessions

#: The annotation `with_naming_sessions` adds.
NAMING_SESSIONS = "naming_sessions"


def with_naming_sessions(
    devices: QuerySet[Device], library: UserLibrary
) -> QuerySet[Device]:
    """Annotate each device's naming sessions."""
    return devices.annotate(
        **{
            NAMING_SESSIONS: counted(
                library_sessions(library).filter(device=OuterRef("pk"))
            )
        }
    )


def naming_sessions_of(device: Device) -> int:
    """The count one annotated device carries."""
    return getattr(device, NAMING_SESSIONS)


def sessions_naming(library: UserLibrary, device: Device) -> QuerySet[PlayerSession]:
    """The live sessions naming one device."""
    return library_sessions(library).filter(device=device)
