"""Arguments and printing; the decisions are elsewhere."""

from uuid import UUID

from django.core.management.base import BaseCommand, CommandError
from django.db.utils import DatabaseError

from games.events.benchmark import (
    BenchmarkReport,
    Budget,
    BudgetVerdict,
    RebuildDiffNotEmpty,
    WorkPerEvent,
)
from games.events.benchmark_run import run_benchmark
from games.events.rebuild import RebuildReport
from games.models import UserLibrary

DEFAULT_SEED_EVENTS = 100_000

#: Measured on the development machine; see docs/event-benchmarks.md.
SECONDS_PER_SEEDED_EVENT = 65 / 100_000
SECONDS_PER_REBUILT_EVENT = 59 / 100_000
SECONDS_PER_PURGED_EVENT = 52 / 100_000

CURSOR_UNDER_A_POOLER = (
    "The replay's server-side cursor did not survive. A transaction-pooling "
    "connection pooler closes it between statements, and "
    "DISABLE_SERVER_SIDE_CURSORS cannot be set yet -- that is issue #917. "
    "Point this at a direct connection, not the pooler."
)


class Command(BaseCommand):
    help = (
        "Measure command latency, rebuild time, and per-event write cost "
        "against the real TrackGame workload. Seeds a scratch library and "
        "removes it again, unless --library names one to check read-only. "
        "Exits non-zero on a rebuild diff, and -- with --gate -- on a missed "
        "budget."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--seed",
            type=int,
            default=None,
            help=f"Events to seed (default {DEFAULT_SEED_EVENTS}).",
        )
        parser.add_argument("--library", help="Check this library instead; read-only.")
        parser.add_argument("--iterations", type=int, default=200)
        parser.add_argument(
            "--warmup", type=int, default=10, help="Additional, discarded."
        )
        parser.add_argument(
            "--gate", action="store_true", help="Exit non-zero on a missed budget."
        )
        parser.add_argument(
            "--json", action="store_true", help="Print the report as JSON."
        )
        parser.add_argument(
            "--keep", action="store_true", help="Leave the scratch library."
        )
        parser.add_argument(
            "--no-count-fold",
            dest="count_fold",
            action="store_false",
            help="Do not instrument the rebuild; use for a verdict inside the overhead.",
        )

    def handle(self, *args, **options):
        library = self._resolve_library(options)
        #: Resolved here, not at the parser: --library has to be able to tell
        #: "no seed given" from "the default typed out".
        seed = DEFAULT_SEED_EVENTS if options["seed"] is None else options["seed"]
        if library is None:
            self._write_estimate(
                seed=seed,
                iterations=options["iterations"],
                warmup=options["warmup"],
                #: --json owns stdout; a human watching still wants the notice.
                aside=options["json"],
            )
        try:
            report = run_benchmark(
                seed=seed,
                iterations=options["iterations"],
                warmup=options["warmup"],
                library=library,
                keep=options["keep"],
                count_fold=options["count_fold"],
                announce_scratch_user=(
                    self._announce_scratch_user if options["keep"] else None
                ),
            )
        except RebuildDiffNotEmpty as error:
            raise CommandError(str(error)) from error
        except DatabaseError as error:
            if "cursor" in str(error).lower():
                raise CommandError(CURSOR_UNDER_A_POOLER) from error
            raise

        if options["json"]:
            self.stdout.write(report.as_json())
        else:
            self._write_report(report)
        if options["gate"]:
            self._gate(report)

    @staticmethod
    def _resolve_library(options) -> UserLibrary | None:
        raw_id = options["library"]
        if raw_id is None:
            return None
        if options["seed"] is not None:
            raise CommandError("--seed and --library cannot both be given.")
        try:
            library_id = UUID(raw_id)
        except ValueError as error:
            raise CommandError(f"{raw_id!r} is not a library id.") from error
        try:
            return UserLibrary.objects.get(pk=library_id)
        except UserLibrary.DoesNotExist as error:
            raise CommandError(f"No library {library_id}.") from error

    def _announce_scratch_user(self, username: str) -> None:
        """Before any scenario runs: a run that raises also leaves it behind."""
        self.stdout.write(
            "Keeping the scratch library. Remove it with: "
            f"manage.py delete_user_library --user {username} --confirm {username}"
        )

    def _write_estimate(
        self, *, seed: int, iterations: int, warmup: int, aside: bool
    ) -> None:
        estimate = seed * (
            SECONDS_PER_SEEDED_EVENT
            + SECONDS_PER_REBUILT_EVENT
            + SECONDS_PER_PURGED_EVENT
        )
        notice = (
            f"About to create a scratch user, {seed} events and "
            f"{seed + 2 * iterations + warmup} catalog rows, then remove them. "
            f"Estimate: {estimate / 60:.1f} minute(s)."
        )
        if aside:
            #: Unstyled: this is a notice on stderr, not a failure.
            self.stderr.write(notice, style_func=str)
        else:
            self.stdout.write(notice)

    def _write_report(self, report: BenchmarkReport) -> None:
        self._write_environment(report)
        if report.seed is not None:
            self.stdout.write(
                f"Seed: {report.seed.events} event(s) in "
                f"{report.seed.append_seconds:.2f}s "
                f"({report.seed.events_per_second:,.0f} event/s), "
                f"{report.seed.catalog_rows} catalog row(s) in "
                f"{report.seed.catalog_seconds:.2f}s."
            )
            #: An append measurement, not a command one: no budget applies,
            #: because no bulk command exists to measure yet.
            self.stdout.write("  The event/s figure is a bulk append, not a command.")
        if report.command is not None:
            self.stdout.write(
                f"Command: {report.command.samples} sample(s), p50 "
                f"{report.command.p50 * 1000:.1f}ms, p95 "
                f"{report.command.p95 * 1000:.1f}ms, max "
                f"{report.command.maximum * 1000:.1f}ms."
            )
        if report.amplification is not None:
            self._write_work("Per command", report.amplification)
        if report.fold is not None:
            self._write_work("Per folded event", report.fold)
        if report.rebuild is not None:
            self._write_rebuild(report.rebuild)
        if report.teardown_seconds is not None:
            self.stdout.write(f"Teardown: {report.teardown_seconds:.2f}s.")
        for budget in report.budgets:
            self._write_budget(budget)

    def _write_environment(self, report: BenchmarkReport) -> None:
        captured = report.environment
        self.stdout.write(
            f"{captured.platform}, {captured.cpu_count} CPU(s), Python "
            f"{captured.python_version}, PostgreSQL {captured.postgresql_version}."
        )
        self.stdout.write(
            f"  shared_buffers {captured.shared_buffers}, work_mem "
            f"{captured.work_mem}, DEBUG {captured.debug}."
        )
        if report.scratch_username is not None:
            self.stdout.write(f"  scratch user {report.scratch_username}")

    def _write_work(self, label: str, work: WorkPerEvent) -> None:
        if not work.events:
            return
        self.stdout.write(
            f"{label}: {work.statements / work.events:.1f} statement(s), "
            f"{work.projection_statements / work.events:.1f} to projections "
            f"({work.projection_rows / work.events:.1f} row(s)), "
            f"{work.event_store_statements / work.events:.1f} to the event store "
            f"({work.event_store_rows / work.events:.1f} row(s)), over "
            f"{work.events} event(s)."
        )
        for table, statements in sorted(work.statements_per_table.items()):
            rows = work.rows_per_table.get(table, 0)
            self.stdout.write(f"    {table}: {statements} statement(s), {rows} row(s)")

    def _write_rebuild(self, rebuild: RebuildReport) -> None:
        self.stdout.write(
            f"Rebuild: folded {rebuild.folded_through} event(s) through "
            f"{len(rebuild.tables)} table(s) in {rebuild.elapsed_seconds:.2f}s "
            f"over {len(rebuild.attempts)} attempt(s)."
        )
        for number, attempt in enumerate(rebuild.attempts, start=1):
            swap = (
                "-" if attempt.swap_seconds is None else f"{attempt.swap_seconds:.2f}s"
            )
            self.stdout.write(
                f"    attempt {number}: replay {attempt.replay_seconds:.2f}s, "
                f"diff {attempt.diff_seconds:.2f}s, swap {swap}"
                + ("" if attempt.conflict is None else f" ({attempt.conflict})")
            )
        for table in rebuild.tables:
            self.stdout.write(
                f"    {table.table}: {table.live_rows} live, "
                f"{table.rebuilt_rows} rebuilt, no difference"
            )

    def _write_budget(self, budget: Budget) -> None:
        line = (
            f"{budget.name}: {budget.measured:.3f}{budget.unit} against "
            f"{budget.limit:.3f}{budget.unit} -- {budget.verdict.value}"
        )
        if budget.verdict is BudgetVerdict.PASSED:
            self.stdout.write(self.style.SUCCESS(line))
        elif budget.verdict is BudgetVerdict.MISSED:
            self.stdout.write(self.style.ERROR(line))
        else:
            #: Too small to judge; the number is still worth printing.
            self.stdout.write(self.style.WARNING(line))

    def _gate(self, report: BenchmarkReport) -> None:
        missed = [
            budget
            for budget in report.budgets
            if budget.verdict is BudgetVerdict.MISSED
        ]
        if not missed:
            return
        raise CommandError(
            "Missed budget(s): "
            + "; ".join(
                f"{budget.name} {budget.measured:.3f}{budget.unit} over "
                f"{budget.limit:.3f}{budget.unit}"
                for budget in missed
            )
        )
