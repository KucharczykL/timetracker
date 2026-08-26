from uuid import UUID

from django.core.management.base import BaseCommand, CommandError

from games.events.rebuild import (
    RebuildMode,
    RebuildReport,
    TableDiff,
    rebuild_projections,
)
from games.events.reconcile import (
    REMEDY,
    ReferenceReconciliation,
    UnresolvedReferences,
)
from games.models import UserLibrary


class Command(BaseCommand):
    """Arguments and printing; the decisions are elsewhere."""

    help = (
        "Rebuild one library's projections from its event stream, or -- with "
        "--check -- report what a rebuild would change without writing anything. "
        "Exits non-zero when a rebuild did not swap."
    )

    def add_arguments(self, parser):
        parser.add_argument("library", help="The UUID of the library to rebuild.")
        parser.add_argument(
            "--check",
            action="store_true",
            help="Replay and diff only: take no lock and write nothing.",
        )

    def handle(self, *args, **options):
        library = self._get_library(options["library"])
        mode = RebuildMode.CHECK if options["check"] else RebuildMode.REBUILD
        try:
            report = rebuild_projections(library, mode=mode)
        except UnresolvedReferences as error:
            self._write_reconciliation(error.reconciliation)
            #: Both modes fail. No rebuild repairs this.
            raise CommandError(
                f"The events name {error.reconciliation.unresolved} row(s) that "
                "no longer exist, so nothing was replayed."
            ) from error
        self._write_report(report)

        if mode is RebuildMode.CHECK:
            self._write_check_outcome(report)
            return
        if not report.swapped:
            raise CommandError(
                f"The rebuild lost to a concurrent write on all "
                f"{len(report.attempts)} attempt(s); nothing was swapped. The "
                "library is busy enough that a quieter moment is the fix."
            )
        self.stdout.write(
            self.style.SUCCESS(f"Swapped {len(report.tables)} table(s) into place.")
        )
        #: True by having got this far.
        self.stdout.write(self.style.SUCCESS("References: all resolved."))

    @staticmethod
    def _get_library(raw_id: str) -> UserLibrary:
        try:
            library_id = UUID(raw_id)
        except ValueError as error:
            raise CommandError(f"{raw_id!r} is not a library id.") from error
        try:
            return UserLibrary.objects.get(pk=library_id)
        except UserLibrary.DoesNotExist as error:
            raise CommandError(f"No library {library_id}.") from error

    def _write_report(self, report: RebuildReport) -> None:
        self.stdout.write(f"Library {report.library_id}: {report.mode.value}")
        if report.stream_id is None:
            self.stdout.write("Stream: none, this library has never appended.")
        else:
            self.stdout.write(f"Stream {report.stream_id}")
        self.stdout.write(
            f"Replayed {report.replayed_through} event(s) through "
            f"{len(report.tables)} table(s); head at diff {report.head_at_diff}."
        )
        for table in report.tables:
            self._write_table(table)
        for number, attempt in enumerate(report.attempts, start=1):
            if attempt.conflict is not None:
                self.stdout.write(
                    self.style.WARNING(f"  attempt {number}: {attempt.conflict}")
                )
        self.stdout.write(
            f"{len(report.attempts)} attempt(s) in {report.elapsed_seconds:.2f}s."
        )

    def _write_table(self, table: TableDiff) -> None:
        self.stdout.write(
            f"  {table.table}: {table.live_rows} live, {table.rebuilt_rows} "
            f"rebuilt, {table.only_live} only live, {table.only_rebuilt} only "
            f"rebuilt, {table.differing} differing"
        )
        if table.sample:
            self.stdout.write(f"    first keys: {', '.join(table.sample)}")

    def _write_reconciliation(self, reconciliation: ReferenceReconciliation) -> None:
        """Every gap the refusal carries."""
        self.stderr.write(
            f"Library {reconciliation.library_id}: the events name "
            f"{reconciliation.unresolved} row(s) that no longer exist, over "
            f"{len(reconciliation.kinds_checked)} kind(s) checked."
        )
        for gap in reconciliation.gaps:
            self.stderr.write(
                f"  {gap.kind} {gap.referenced_id} ({gap.label!r}, {gap.detail!r}): "
                f"first named by event #{gap.first_sequence}, in "
                f"{gap.event_count} event(s), at payload key {gap.payload_key!r}"
            )
        remaining = reconciliation.unresolved - len(reconciliation.gaps)
        if remaining:
            self.stderr.write(f"  and {remaining} more.")
        self.stderr.write(REMEDY)

    def _write_check_outcome(self, report: RebuildReport) -> None:
        if report.head_at_diff != report.replayed_through:
            #: No lock: the drift may be false.
            self.stdout.write(
                self.style.WARNING(
                    "The head moved while the check ran, so the diff above is "
                    "advisory. Re-run it, or rebuild -- a rebuild turns the same "
                    "race into a redo."
                )
            )
        drifted = sum(
            table.only_live + table.only_rebuilt + table.differing
            for table in report.tables
        )
        if not drifted:
            self.stdout.write(
                self.style.SUCCESS("Projections match the replayed events.")
            )
            return
        tables = sum(
            1
            for table in report.tables
            if table.only_live or table.only_rebuilt or table.differing
        )
        self.stdout.write(
            self.style.WARNING(
                f"{drifted} row(s) differ from the replay across {tables} table(s)."
            )
        )
