"""Print the census, for a log and a person.

A preflight reports and does not gate, so what it finds
never fails the run. Only a scope this command cannot
resolve is an error.
"""

import json
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from games.models import UserLibrary
from games.preflight.session import (
    DEFAULT_SAMPLE_SIZE,
    NO_COUNTS,
    LibraryPreflight,
    preflight_library,
    shared_catalog_counts,
)

MACHINE_PREFIX = "SESSION_PREFLIGHT_JSON="
GENERATED_PREFIX = "Generated at "


class Command(BaseCommand):
    help = "Report what #700 will meet in the legacy Session rows."

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
        parser.add_argument(
            "--day-zone",
            help="Read the second column in this zone instead of the library's.",
        )

    def handle(self, *args, **options):
        libraries = self._resolve_libraries(options)
        sample_size = options["sample_size"]
        if sample_size < 0:
            raise CommandError(
                "A sample size counts identifiers, so it is not negative."
            )
        day_zone = self._resolve_zone(options["day_zone"])

        reports = [
            preflight_library(library, sample_size=sample_size, day_zone=day_zone)
            for library in libraries
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
        self.stdout.write(f"  sessions on them: {shared.shared_game_sessions}")

    def _write_report(self, report: LibraryPreflight) -> None:
        counts = report.counts
        primary, secondary = report.zones
        write = self.stdout.write
        write(f"Session preflight - library {report.library_id} ({report.username})")
        write(f"  days read in {primary} (primary) and {secondary} (secondary)")
        write(f"  games owned: {counts.games_owned}")
        write(f"    holding no sessions: {counts.games_without_sessions}")
        write(f"  sessions in scope: {counts.sessions_in_scope}")
        write(f"  classified: {counts.classified}")
        write(f"    of which removed: {counts.removed}")
        write("  timing:")
        write(f"    timed (end, no manual duration): {counts.timed}")
        write(f"    duration only (no end): {counts.duration_only}")
        write(f"    corrected (end and manual duration): {counts.corrected}")
        write(f"    end earlier than start: {counts.negative_elapsed}")
        self._write_sample(report.samples.negative_elapsed)
        write(f"    manual duration below zero: {counts.negative_manual}")
        self._write_sample(report.samples.negative_manual)
        write(f"    still running (start alone): {counts.running}")
        self._write_sample(report.samples.running)
        write("  observed:")
        write(f"    manual duration is null: {counts.manual_duration_null}")
        write(f"    committed zone stated: {counts.committed_zone_stated}")
        write("  no mode converts:")
        write(f"    on a removed game: {counts.on_removed_game}")
        write(f"    on an untracked game: {counts.without_player_game}")
        write(f"    on a removed tracking row: {counts.on_removed_player_game}")
        write(f"    in no category above: {counts.unaccounted}")
        write(f"  assignment ({primary} | {secondary}):")
        write(f"    sole run: {counts.sole_run} (both zones)")
        write(
            f"    contained: {counts.contained_primary} | {counts.contained_secondary}"
        )
        write(f"    bucket: {counts.bucket_primary} | {counts.bucket_secondary}")
        self._write_sample(report.samples.bucket_primary)
        write(
            f"    more than one claimer: {counts.many_claimers_primary} | "
            f"{counts.many_claimers_secondary}"
        )
        self._write_sample(report.samples.many_claimers_primary)
        write(
            f"    games needing a bucket: {counts.games_needing_bucket_primary} | "
            f"{counts.games_needing_bucket_secondary}"
        )
        self._write_sample(report.samples.games_needing_bucket_primary)
        write("  the same instant read in both zones:")
        write(f"    falls on another day: {counts.day_differs}")
        write(f"    falls in another month: {counts.month_differs}")
        write(f"    falls in another year: {counts.year_differs}")

    def _write_sample(self, values) -> None:
        if values:
            self.stdout.write("      " + " ".join(str(value) for value in values))

    def _resolve_zone(self, name: str | None) -> ZoneInfo | None:
        if name is None:
            return None
        try:
            return ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise CommandError(f"{name!r} names no time zone.") from error

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
