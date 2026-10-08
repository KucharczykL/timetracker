from django.core.management.base import BaseCommand, CommandError, OutputWrapper

from games.events.rebuild import (
    RebuildMode,
    RebuildReport,
    SwapRefused,
    TableDiff,
    rebuild_projections,
)
from games.events.reconcile import (
    REMEDY,
    ReferenceReconciliation,
    UnresolvedReferences,
)
from games.management.library_scope import add_scope_arguments, scoped_libraries
from games.models import UserLibrary
from games.planner_statistics import analyze_tables
from games.projections import projection_models


class Command(BaseCommand):
    """Arguments and printing; the decisions are elsewhere."""

    help = (
        "Rebuild the projections of one library, or of every library, from "
        "their event streams -- or, with --check, report what a rebuild would "
        "change without writing anything. Exits non-zero when a rebuild did "
        "not swap."
    )

    def add_arguments(self, parser):
        add_scope_arguments(parser, verb="Rebuild")
        parser.add_argument(
            "--check",
            action="store_true",
            help="Replay and diff only: take no lock and write nothing.",
        )
        parser.add_argument(
            "--fail-on-drift",
            action="store_true",
            help=(
                "Exit non-zero when a check found a differing row, after "
                "checking every library in scope. Needs --check: a check "
                "alone exits zero, because a rebuild removes drift, and an "
                "operator rehearsing a deployment wants the opposite."
            ),
        )

    def handle(self, *args, **options):
        if options["fail_on_drift"] and not options["check"]:
            #: Silently inert here would rebuild every library instead.
            raise CommandError(
                "--fail-on-drift reports what a check found, and a rebuild "
                "removes drift rather than reporting it. Add --check."
            )
        libraries = scoped_libraries(options)
        mode = RebuildMode.CHECK if options["check"] else RebuildMode.REBUILD
        #: The whole census, so one drift hides no other.
        drifted: list[tuple[UserLibrary, int]] = []
        try:
            for library in libraries:
                rows = self._run_one(library, mode)
                if rows:
                    drifted.append((library, rows))
        finally:
            #: Libraries rebuilt before a failure stay rebuilt.
            if mode is RebuildMode.REBUILD:
                analyze_tables(projection_models())
        if drifted and options["fail_on_drift"]:
            total = sum(rows for _library, rows in drifted)
            raise CommandError(
                f"{total} row(s) differ from the replay, across "
                f"{len(drifted)} of {len(libraries)} library(s) checked: "
                + ", ".join(str(library.pk) for library, _rows in drifted)
            )

    def _run_one(self, library: UserLibrary, mode: RebuildMode) -> int:
        """Answer the drifted rows a check counted."""
        try:
            report = rebuild_projections(library, mode=mode)
        except UnresolvedReferences as error:
            self._write_reconciliation(error.reconciliation)
            #: Both modes fail. No rebuild repairs this.
            raise CommandError(
                f"The events name {error.reconciliation.unresolved} row(s) that "
                "no longer exist, so nothing was replayed."
            ) from error
        except SwapRefused as error:
            #: The refusal carries the diff; no report.
            for table in error.tables:
                self._write_table(table, self.stderr)
            raise CommandError(str(error)) from error
        self._write_report(report)
        if not report.tables:
            #: Zero compared reads as zero differing otherwise.
            raise CommandError(
                f"Library {report.library_id} was replayed through no table, so "
                "nothing was compared. A projection registry naming none is the "
                "fault here, not a library that agrees with its events."
            )

        if mode is RebuildMode.CHECK:
            return self._write_check_outcome(report)
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
        #: A rebuild leaves no drift to report.
        return 0

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

    def _write_table(
        self, table: TableDiff, stream: OutputWrapper | None = None
    ) -> None:
        stream = self.stdout if stream is None else stream
        stream.write(
            f"  {table.table}: {table.live_rows} live, {table.rebuilt_rows} "
            f"rebuilt, {table.only_live} only live, {table.only_rebuilt} only "
            f"rebuilt, {table.differing} differing"
        )
        if table.sample:
            stream.write(f"    first keys: {', '.join(table.sample)}")

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

    def _write_check_outcome(self, report: RebuildReport) -> int:
        """Print the outcome; answer the drifted count."""
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
            return 0
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
        return drifted
