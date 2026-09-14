"""Compare every playtime figure across both tables."""

from django.core.management.base import BaseCommand, CommandError

from games.management.library_scope import (
    add_library_scope,
    resolve_libraries,
    resolve_zone,
)
from games.reads.playtime_parity import (
    UNCOMPARED_MEMBERS,
    differing,
    display_zone,
    playtime_figures,
    projection_day_zones,
)


class Command(BaseCommand):
    help = "Compare every playtime figure the legacy table and the projection state."

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
            zone = override if override is not None else display_zone(library)
            figures = playtime_figures(library, zone)
            differences = differing(figures)
            compared += len(figures)
            differing_count += len(differences)
            day_zones = ", ".join(projection_day_zones(library)) or "none"
            self.stdout.write(
                f"Playtime parity - library {library.pk} ({library.user.username})"
            )
            self.stdout.write(
                f"  legacy days read in {zone.key}; "
                f"projection rows fix days in: {day_zones}"
            )
            for figure in figures:
                marker = "DIFFERS" if figure in differences else "equal"
                self.stdout.write(
                    f"  {figure.scope}: legacy {figure.legacy}, "
                    f"projection {figure.projection} [{marker}]"
                )

        for member, reason in UNCOMPARED_MEMBERS.items():
            self.stdout.write(f"Not compared: {member} ({reason})")
        summary = (
            f"{differing_count} of {compared} figures differ "
            f"across {len(libraries)} libraries"
        )
        if differing_count:
            raise CommandError(summary)
        self.stdout.write(self.style.SUCCESS(summary))
