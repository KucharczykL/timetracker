"""Compare every session figure across both tables."""

from django.core.management.base import BaseCommand, CommandError

from games.management.library_scope import (
    add_library_scope,
    resolve_libraries,
    resolve_zone,
)
from games.reads.calendar import calendar_day_zone
from games.reads.playtime_parity import (
    UNCOMPARED_MEMBERS,
    differing,
    playtime_figures,
    projection_day_zones,
)
from games.reads.session_parity import (
    UNCOMPARED_SESSION_MEMBERS,
    differing_session_figures,
    session_figures,
)


class Command(BaseCommand):
    help = (
        "Compare every playtime figure and every session figure the legacy "
        "table and the projection state."
    )

    def add_arguments(self, parser):
        add_library_scope(parser)
        parser.add_argument(
            "--day-zone",
            help="Read legacy days in this zone instead of the display zone.",
        )

    def handle(self, *args, **options):
        libraries = resolve_libraries(options)
        if not libraries:
            raise CommandError("No library matched the scope, so nothing compared.")
        override = resolve_zone(options["day_zone"])

        compared = differing_count = 0
        for library in libraries:
            zone = override if override is not None else calendar_day_zone(library)
            playtime = playtime_figures(library, zone)
            playtime_differences = differing(playtime)
            sessions = session_figures(library, zone)
            session_differences = differing_session_figures(sessions)
            compared += len(playtime) + len(sessions)
            differing_count += len(playtime_differences) + len(session_differences)
            day_zones = ", ".join(projection_day_zones(library)) or "none"
            self.stdout.write(
                f"Session parity - library {library.pk} ({library.user.username})"
            )
            self.stdout.write(
                f"  legacy days read in {zone.key}; "
                f"projection rows fix days in: {day_zones}"
            )
            for figure in playtime:
                marker = "DIFFERS" if figure in playtime_differences else "equal"
                self.stdout.write(
                    f"  {figure.scope}: legacy {figure.legacy}, "
                    f"projection {figure.projection} [{marker}]"
                )
            for session_figure in sessions:
                marker = "DIFFERS" if session_figure in session_differences else "equal"
                self.stdout.write(
                    f"  {session_figure.scope}: legacy {session_figure.legacy}, "
                    f"projection {session_figure.projection} [{marker}]"
                )

        for member, reason in {
            **UNCOMPARED_MEMBERS,
            **UNCOMPARED_SESSION_MEMBERS,
        }.items():
            self.stdout.write(f"Not compared: {member} ({reason})")
        summary = (
            f"{differing_count} of {compared} figures differ "
            f"across {len(libraries)} libraries"
        )
        if differing_count:
            raise CommandError(summary)
        self.stdout.write(self.style.SUCCESS(summary))
