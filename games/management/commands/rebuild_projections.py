from uuid import UUID

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError, OutputWrapper

from games.events.rebuild import (
    RebuildMode,
    RebuildReport,
    SwapRefusedByReference,
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
        "Rebuild the projections of one library, or of every library, from "
        "their event streams -- or, with --check, report what a rebuild would "
        "change without writing anything. Exits non-zero when a rebuild did "
        "not swap."
    )

    def add_arguments(self, parser):
        scope = parser.add_mutually_exclusive_group(required=True)
        scope.add_argument("--user", help="Rebuild the library owned by USERNAME.")
        scope.add_argument(
            "--library", dest="library_id", help="Rebuild one library UUID."
        )
        scope.add_argument(
            "--all-libraries",
            action="store_true",
            help="Explicitly rebuild every library, in key order.",
        )
        parser.add_argument(
            "--check",
            action="store_true",
            help="Replay and diff only: take no lock and write nothing.",
        )
        parser.add_argument(
            "--fail-on-drift",
            action="store_true",
            help=(
                "Exit non-zero when a check found a differing row. A check "
                "alone exits zero, because a rebuild removes drift; an "
                "operator rehearsing a deployment wants the opposite."
            ),
        )

    def handle(self, *args, **options):
        libraries = self._resolve_libraries(options)
        mode = RebuildMode.CHECK if options["check"] else RebuildMode.REBUILD
        for library in libraries:
            self._run_one(library, mode, fail_on_drift=options["fail_on_drift"])

    def _run_one(
        self, library: UserLibrary, mode: RebuildMode, *, fail_on_drift: bool
    ) -> None:
        try:
            report = rebuild_projections(library, mode=mode)
        except UnresolvedReferences as error:
            self._write_reconciliation(error.reconciliation)
            #: Both modes fail. No rebuild repairs this.
            raise CommandError(
                f"The events name {error.reconciliation.unresolved} row(s) that "
                "no longer exist, so nothing was replayed."
            ) from error
        except SwapRefusedByReference as error:
            #: The refusal carries the diff; no report.
            for table in error.tables:
                self._write_table(table, self.stderr)
            raise CommandError(str(error)) from error
        self._write_report(report)

        if mode is RebuildMode.CHECK:
            drifted = self._write_check_outcome(report)
            if drifted and fail_on_drift:
                raise CommandError(
                    f"{drifted} row(s) differ from the replay in library "
                    f"{report.library_id}."
                )
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

    def _resolve_libraries(self, options) -> list[UserLibrary]:
        libraries = UserLibrary.objects.select_related("user").order_by("pk")
        if options["all_libraries"]:
            return list(libraries)
        if options["user"]:
            return [self._library_of_user(libraries, options["user"])]
        return [self._library_by_id(libraries, options["library_id"])]

    @staticmethod
    def _library_of_user(libraries, username: str) -> UserLibrary:
        """Two errors: no user, or no library."""
        user_model = get_user_model()
        try:
            user = user_model.objects.get(username=username)
        except user_model.DoesNotExist as error:
            raise CommandError(f"No user is named {username!r}.") from error
        try:
            return libraries.get(user=user)
        except UserLibrary.DoesNotExist as error:
            raise CommandError(f"User {username!r} owns no library.") from error

    @staticmethod
    def _library_by_id(libraries, raw_id: str) -> UserLibrary:
        try:
            library_id = UUID(raw_id)
        except ValueError as error:
            raise CommandError(f"{raw_id!r} is not a library id.") from error
        try:
            return libraries.get(pk=library_id)
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
