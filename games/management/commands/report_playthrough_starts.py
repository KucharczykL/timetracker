"""Print what #1038 would state, for a log and a person.

A report states nothing and gates nothing, so what it finds never
fails the run. Only a scope this command cannot resolve is an error.
"""

import json
import uuid

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from games.backfill.playthrough_start import (
    DEFAULT_SAMPLE_SIZE,
    NO_START_COUNTS,
    LibraryStartReport,
    report_library,
)
from games.models import UserLibrary

MACHINE_PREFIX = "PLAYTHROUGH_START_REPORT_JSON="
GENERATED_PREFIX = "Generated at "


class Command(BaseCommand):
    help = "Report what #1038 would state for the runs #684 left empty."

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
            help="Runs printed beside each count. 0 keeps the counts only.",
        )

    def handle(self, *args, **options):
        libraries = self._resolve_libraries(options)
        sample_size = options["sample_size"]
        if sample_size < 0:
            raise CommandError("A sample size counts runs, so it is not negative.")

        reports = [
            report_library(library, sample_size=sample_size) for library in libraries
        ]
        summary = sum((report.counts for report in reports), NO_START_COUNTS)
        generated_at = timezone.now().isoformat()
        payload = {
            "schema_version": 1,
            "generated_at": generated_at,
            "summary": summary.as_dict(),
            "libraries": [report.as_dict() for report in reports],
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

    def _write_report(self, report: LibraryStartReport) -> None:
        counts = report.counts
        write = self.stdout.write
        write(
            f"Playthrough start repair - library {report.library_id} "
            f"({report.username})"
        )
        write(f"  runs the pass may date: {counts.runs_in_scope}")
        write(f"    holding a status day only: {counts.status_only}")
        write(f"    holding a session day only: {counts.session_only}")
        write(f"    holding both: {counts.both}")
        write(f"      whose two days agree: {counts.both_agree}")
        write(f"    holding neither, left stating no act: {counts.no_evidence}")
        write(f"  dated by the status: {counts.from_status}")
        write(f"  dated by a session: {counts.from_session}")
        write(f"  session days read in {report.zone}; status days in the")
        write("    server zone #676 froze them in")
        for gap, times in sorted(report.gaps.items()):
            if gap:
                write(f"    days apart {gap}: {times}")
        for sample in report.samples:
            write(
                f"      {sample.run_id} {sample.game_name} "
                f"{sample.day.isoformat()} {sample.source}"
            )

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
