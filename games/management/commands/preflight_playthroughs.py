"""Print the preflight, for a log and a person.

A preflight reports and does not gate, so what it finds never fails the run.
Only a scope this command cannot resolve is an error.
"""

import json
import uuid

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from games.models import UserLibrary
from games.preflight.playthrough import (
    DEFAULT_SAMPLE_SIZE,
    NO_COUNTS,
    LibraryPreflight,
    preflight_library,
    shared_catalog_counts,
)

MACHINE_PREFIX = "PLAYTHROUGH_PREFLIGHT_JSON="
GENERATED_PREFIX = "Generated at "


class Command(BaseCommand):
    help = "Report what #684 will meet in the legacy PlayEvent rows."

    def add_arguments(self, parser):
        scope = parser.add_mutually_exclusive_group(required=True)
        scope.add_argument("--user", help="Report the library owned by USERNAME.")
        scope.add_argument(
            "--library", dest="library_id", help="Report one library UUID."
        )
        scope.add_argument(
            "--all-libraries",
            action="store_true",
            help="Explicitly report every library.",
        )
        parser.add_argument(
            "--sample-size",
            type=int,
            default=DEFAULT_SAMPLE_SIZE,
            help="Identifiers printed beside each count. 0 keeps the counts only.",
        )

    def handle(self, *args, **options):
        libraries = self._resolve_libraries(options)
        sample_size = options["sample_size"]
        if sample_size < 0:
            raise CommandError(
                "A sample size counts identifiers, so it is not negative."
            )

        reports = [
            preflight_library(library, sample_size=sample_size) for library in libraries
        ]
        shared = shared_catalog_counts()
        summary = sum((report.counts for report in reports), NO_COUNTS)

        generated_at = timezone.now().isoformat()
        payload = {
            "schema_version": 1,
            "generated_at": generated_at,
            "summary": summary.as_dict(),
            "libraries": [report.as_dict() for report in reports],
            "shared_catalog": shared.as_dict(),
        }
        self.stdout.write(
            MACHINE_PREFIX + json.dumps(payload, sort_keys=True, separators=(",", ":"))
        )
        self.stdout.write(f"{GENERATED_PREFIX}{generated_at}")
        if not reports:
            #: An empty scope reads as an all-zero report.
            self.stdout.write(
                "No library was read, so every count below counts nothing."
            )
        for report in reports:
            self._write_report(report)
        self.stdout.write(f"Shared catalog games: {shared.shared_games}")
        self.stdout.write(f"  live play events on them: {shared.shared_game_rows}")
        self.stdout.write(
            f"  rows more than one library tracks: {shared.contested_rows}"
        )

    def _write_report(self, report: LibraryPreflight) -> None:
        counts = report.counts
        write = self.stdout.write
        write(
            f"Playthrough preflight - library {report.library_id} ({report.username})"
        )
        write(f"  tracked games: {counts.tracked}")
        write(f"    holding no play events: {counts.tracked_without_rows}")
        write(f"    on a removed game: {counts.tracked_on_removed_game}")
        write(f"  play events in scope: {counts.rows_total}")
        write(f"  live play events: {counts.live_rows}")
        write(f"    clean, both endpoints: {counts.clean_both}")
        write(f"    clean, start only: {counts.clean_start_only}")
        write(f"    clean, completion only: {counts.clean_end_only}")
        write(f"    no known endpoint: {counts.no_known_endpoint}")
        write(f"    completion before start: {counts.reversed_endpoints}")
        self._write_sample(report.samples.reversed_endpoints)
        write("  not converted:")
        write(f"    removed rows: {counts.rows_removed}")
        write(f"    on a removed game: {counts.rows_on_removed_game}")
        write(f"    on an untracked game: {counts.rows_untracked}")
        write(f"    with no projection row: {counts.rows_without_projection}")
        write(f"    in no bucket above: {counts.rows_unaccounted}")
        write("  ordering:")
        write(f"    ordered by date alone: {counts.ordered_by_date}")
        write(f"    display number decided by insertion order: {counts.tie_broken}")
        self._write_sample(report.samples.tie_broken)
        write(
            f"    date order differs from insertion order: "
            f"{counts.date_order_differs_from_insertion}"
        )
        self._write_sample(report.samples.date_order_differs)
        write(f"  #676 status events with a known day: {counts.status_events_676}")
        write(
            f"    #676 status events with no known day: {counts.status_events_undated}"
        )
        write(f"    endpoints with one unambiguous pair: {counts.pairs_unambiguous}")
        write(
            f"      whose status was retired or abandoned: "
            f"{counts.pairs_retired_or_abandoned}"
        )
        write(f"    endpoints with an ambiguous pair: {counts.pairs_ambiguous}")
        self._write_sample(report.samples.ambiguous_endpoints)
        write(f"    endpoints with no candidate: {counts.pairs_absent}")
        write(f"    status events no endpoint claimed: {counts.unclaimed_events}")

    def _write_sample(self, values) -> None:
        if values:
            self.stdout.write("      " + " ".join(str(value) for value in values))

    def _resolve_libraries(self, options):
        libraries = UserLibrary.objects.select_related("user").order_by("pk")
        if options["all_libraries"]:
            return list(libraries)
        if options["user"]:
            return [self._library_of_user(libraries, options["user"])]
        return [self._library_by_id(libraries, options["library_id"])]

    def _library_of_user(self, libraries, username: str) -> UserLibrary:
        """A missing user is not a user missing a library."""
        user_model = get_user_model()
        try:
            user = user_model.objects.get(username=username)
        except user_model.DoesNotExist as error:
            raise CommandError(f"No user is named {username!r}.") from error
        try:
            return libraries.get(user=user)
        except UserLibrary.DoesNotExist as error:
            raise CommandError(f"User {username!r} owns no library.") from error

    def _library_by_id(self, libraries, library_id: str) -> UserLibrary:
        """The text is read here, so the query catches one error."""
        try:
            parsed = uuid.UUID(library_id)
        except ValueError as error:
            raise CommandError(f"Library {library_id!r} is no UUID.") from error
        try:
            return libraries.get(pk=parsed)
        except UserLibrary.DoesNotExist as error:
            raise CommandError(f"Library {parsed} does not exist.") from error
