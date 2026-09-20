"""Arguments and printing; the decisions are elsewhere."""

from uuid import UUID

from django.core.management.base import BaseCommand, CommandError
from django.db.utils import DatabaseError

from games.events.benchmark import (
    BenchmarkReport,
    Budget,
    BudgetVerdict,
    RebuildDiffNotEmpty,
    Timings,
    WorkPerEvent,
)
from games.events.benchmark_run import run_benchmark
from games.events.rebuild import RebuildReport
from games.models import UserLibrary

DEFAULT_SEED_EVENTS = 100_000
#: An import's worth of records.
IMPORT_SHAPE_RECORDS = 600
#: A batch's worth of rows, the same size: one act on a library.
BATCH_SHAPE_SESSIONS = 600

#: Measured; see docs/event-benchmarks.md.
SECONDS_PER_SEEDED_EVENT = 35 / 100_000
SECONDS_PER_REBUILT_EVENT = 29 / 100_000
SECONDS_PER_PURGED_EVENT = 12 / 100_000
SECONDS_PER_RECORD_DISPATCH = 5 / 1000

CURSOR_UNDER_A_POOLER = (
    "A server-side cursor did not survive. A transaction-pooling connection "
    "pooler closes one between statements. Our own reads page by key and open "
    "none, so this came from inside Django: set DISABLE_SERVER_SIDE_CURSORS, or "
    "point this at a direct connection rather than the pooler."
)


class Command(BaseCommand):
    help = (
        "Measure command latency, rebuild time, and per-event write cost "
        "against the real TrackGame workload. Seeds a scratch library and "
        "removes it again, unless --library names one to time its reads and "
        "check its replay without writing. "
        "Exits non-zero on a rebuild diff, and -- with --gate -- on a missed "
        "budget."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--seed",
            type=int,
            default=None,
            help=(
                f"Events to seed (default {DEFAULT_SEED_EVENTS}). Three events "
                "are seeded per game, so a count not divisible by three seeds "
                "one or two events fewer. 0 seeds nothing and measures the "
                "commands alone."
            ),
        )
        parser.add_argument(
            "--bulk",
            type=int,
            default=BATCH_SHAPE_SESSIONS,
            help=(
                f"Rows in the timed batch (default {BATCH_SHAPE_SESSIONS}). Each "
                "is one written-down session, resolved and converted the way "
                "the runner does one. 0 converts nothing and leaves the batch "
                "out of the report."
            ),
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
            "--no-count-replay",
            dest="count_replay",
            action="store_false",
            help="Do not instrument the rebuild; use for a verdict inside the overhead.",
        )

    def handle(self, *args, **options):
        library = self._resolve_library(options)
        #: Here, so --library sees an unset seed.
        seed = DEFAULT_SEED_EVENTS if options["seed"] is None else options["seed"]
        if library is None:
            if options["bulk"] < 0:
                raise CommandError(
                    f"--bulk {options['bulk']} converts no row, and it does "
                    "not say so the way --bulk 0 does."
                )
            #: Zero is the stated no-seed run; one or two is a typo.
            if seed < 0 or seed in (1, 2):
                raise CommandError(
                    f"--seed {seed} seeds no game, because a game is three "
                    "events, and it does not say so the way --seed 0 does. "
                    "The smallest seeded run is --seed 3."
                )
            self._write_estimate(
                seed=seed,
                iterations=options["iterations"],
                warmup=options["warmup"],
                records=IMPORT_SHAPE_RECORDS,
                bulk=options["bulk"],
                #: --json owns stdout; the notice goes aside.
                aside=options["json"],
            )
        try:
            report = run_benchmark(
                seed=seed,
                iterations=options["iterations"],
                warmup=options["warmup"],
                records=IMPORT_SHAPE_RECORDS,
                bulk=options["bulk"],
                library=library,
                keep=options["keep"],
                count_replay=options["count_replay"],
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
        """First: a run that raises leaves it."""
        self.stdout.write(
            "Keeping the scratch library. Remove it with: "
            f"manage.py purge_user_library --user {username} --confirm {username}"
        )

    def _write_estimate(
        self,
        *,
        seed: int,
        iterations: int,
        warmup: int,
        records: int,
        bulk: int,
        aside: bool,
    ) -> None:
        estimate = (
            seed
            * (
                SECONDS_PER_SEEDED_EVENT
                + SECONDS_PER_REBUILT_EVENT
                + SECONDS_PER_PURGED_EVENT
            )
            + (records + bulk * 2 + 2 * warmup) * SECONDS_PER_RECORD_DISPATCH
        )
        #: Three events a game: a third of the rows.
        catalog_rows = seed // 3 + 2 * iterations + warmup
        notice = (
            f"About to create a scratch user, {seed} events, "
            f"{catalog_rows} catalog rows, {records} historical playtime "
            f"records and a batch of {bulk} conversions, then remove them. "
            f"Estimate: {estimate / 60:.1f} minute(s)."
        )
        if aside:
            #: Unstyled: a notice, not a failure.
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
            #: An append, not a command; no budget.
            self.stdout.write("  The event/s figure is a bulk append, not a command.")
        if report.command is not None:
            self._write_timings("Command", report.command)
        if report.session_command is not None:
            self._write_timings("Session command", report.session_command)
        if report.record_command is not None:
            self._write_timings("Record command", report.record_command)
        if report.bulk_command is not None:
            self._write_timings("Bulk command", report.bulk_command)
        if report.bulk_resolve is not None:
            #: Inside the line above, not beside it; no budget of its own.
            self._write_timings("  of which resolve", report.bulk_resolve)
        for read in report.reads:
            self._write_timings(f"Read {read.name}", read.timings)
        if report.amplification is not None:
            self._write_work("Per command", report.amplification)
        if report.replay is not None:
            self._write_work("Per replayed event", report.replay)
        if report.rebuild is not None:
            self._write_rebuild(report.rebuild)
        if report.teardown_seconds is not None:
            self.stdout.write(f"Teardown: {report.teardown_seconds:.2f}s.")
        for budget in report.budgets:
            self._write_budget(budget)

    def _write_timings(self, label: str, timings: Timings) -> None:
        self.stdout.write(
            f"{label}: {timings.samples} sample(s), p50 "
            f"{timings.p50 * 1000:.1f}ms, p95 {timings.p95 * 1000:.1f}ms, max "
            f"{timings.maximum * 1000:.1f}ms."
        )

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
            f"Rebuild: replayed {rebuild.replayed_through} event(s) through "
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
            #: Too small to judge; still worth printing.
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
