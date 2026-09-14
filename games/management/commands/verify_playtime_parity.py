"""Compare every playtime figure across both tables."""

from django.core.management.base import BaseCommand, CommandError

from games.management.library_scope import (
    add_library_scope,
    resolve_libraries,
    resolve_zone,
)
from games.reads.playtime_parity import differing, display_zone, playtime_figures


class Command(BaseCommand):
    help = "Compare every playtime figure the legacy table and the projection state."

    def add_arguments(self, parser):
        add_library_scope(parser)
        parser.add_argument(
            "--day-zone",
            help="Read days in this zone instead of the library's display zone.",
        )

    def handle(self, *args, **options):
        libraries = resolve_libraries(options)
        override = resolve_zone(options["day_zone"])

        differing_count = 0
        for library in libraries:
            zone = override if override is not None else display_zone(library)
            figures = playtime_figures(library, zone)
            differences = differing(figures)
            differing_count += len(differences)
            self.stdout.write(
                f"Playtime parity - library {library.pk} ({library.user.username}), "
                f"days read in {zone.key}"
            )
            for figure in figures:
                marker = "DIFFERS" if figure in differences else "equal"
                self.stdout.write(
                    f"  {figure.scope}: legacy {figure.legacy}, "
                    f"projection {figure.projection} [{marker}]"
                )

        summary = f"{differing_count} figures differ"
        if differing_count:
            raise CommandError(summary)
        self.stdout.write(self.style.SUCCESS(summary))
