"""Print the census, for a log and a person.

A preflight reports and does not gate, so what it finds
never fails the run. Only a scope this command cannot
resolve is an error.
"""

import json

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from games.management.library_scope import (
    add_library_scope,
    resolve_libraries,
    resolve_zone,
)
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
        add_library_scope(parser)
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
        libraries = resolve_libraries(options)
        sample_size = options["sample_size"]
        if sample_size < 0:
            raise CommandError(
                "A sample size counts identifiers, so it is not negative."
            )
        day_zone = resolve_zone(options["day_zone"])

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
        primary, secondary = report.zones.primary, report.zones.secondary
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
