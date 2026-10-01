"""Convert one library's legacy purchases; reconcile."""

import json
from pathlib import Path

from django.contrib.auth import get_user_model
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from games.backfill.purchase import (
    LibraryConversion,
    PurchaseConversionRefused,
    convert_purchases,
    legacy_rows,
)
from games.backfill.purchase_plan import LegacyRow
from games.backfill.purchase_reconciliation import (
    legacy_statistics,
    reconcile,
    review_lists,
)
from games.models import LegacyPurchase, PlayerGame, UserLibrary
from games.views.stats_data import compute_stats


class _Preflight(Exception):
    """Rolls the preflight back."""


class Command(BaseCommand):
    help = (
        "Convert one library's legacy purchases inside a transaction, print "
        "every refusal, the review lists and the reconciliation, and roll "
        "back. With --confirm it commits. Run it on a scratch restore first."
    )

    def add_arguments(self, parser):
        parser.add_argument("--user", required=True, help="Username to convert.")
        parser.add_argument(
            "--confirm",
            help="Commit only when this value exactly matches --user.",
        )
        parser.add_argument(
            "--snapshot",
            type=Path,
            help="Write the legacy statistics to this JSON file first.",
        )

    def handle(self, *args, **options):
        username = options["user"]
        confirmation = options["confirm"]
        if confirmation is not None and confirmation != username:
            raise CommandError(
                "--confirm must exactly match --user; nothing converted."
            )
        library = self._get_user(username).library
        rows = legacy_rows(LegacyPurchase, library.pk)
        if options["snapshot"] is not None:
            snapshot = legacy_statistics(library, rows)
            options["snapshot"].write_text(json.dumps(snapshot, indent=2) + "\n")
            self.stdout.write(
                f"Snapshot of {len(snapshot['scopes'])} scope(s) written."
            )
        try:
            with transaction.atomic():
                self._convert(library, rows)
                if confirmation is None:
                    raise _Preflight
        except _Preflight:
            self.stdout.write(
                self.style.WARNING(
                    f"PREFLIGHT: rolled back. Re-run with --confirm {username}."
                )
            )
            return
        self.stdout.write(self.style.SUCCESS("Converted and committed."))

    def _convert(self, library: UserLibrary, rows: list[LegacyRow]) -> None:
        before = self._backlog(library)
        try:
            conversion = convert_purchases(rows)
        except PurchaseConversionRefused as refused:
            for refusal in refused.refusals:
                self.stdout.write(self.style.ERROR(str(refusal)))
            raise CommandError(
                f"{len(refused.refusals)} refusal(s); nothing converted."
            ) from refused
        if not conversion.libraries:
            self.stdout.write(
                f"{len(rows)} legacy row(s); every one converted already."
            )
            return
        [done] = conversion.libraries
        self._report(library, rows, done)
        after = self._backlog(library)
        self.stdout.write(
            f"Backlog: unfinished {before[0]} -> {after[0]}, "
            f"dropped {before[1]} -> {after[1]}; "
            f"tracked games {before[2]} -> {after[2]}."
        )

    def _report(
        self, library: UserLibrary, rows: list[LegacyRow], done: LibraryConversion
    ) -> None:
        checked = reconcile(rows, done)
        self.stdout.write(
            f"{len(rows)} legacy row(s): {checked.planned_copies} planned "
            f"copies, {checked.copies} copies and {checked.purchases} purchases "
            f"stated, {checked.skipped} skipped; {done.appended} events appended."
        )
        for category, legacy_ids in review_lists(library, done).items():
            self.stdout.write(f"Review {category}: {len(legacy_ids)}")
            for legacy_id in legacy_ids:
                self.stdout.write(f"  {legacy_id}")
        for total in checked.totals:
            self.stdout.write(
                f"{total.currency}: legacy {total.legacy}, converted "
                f"{total.converted}, quantization {total.quantization}, "
                f"skipped {total.skipped}"
            )
        self.stdout.write(
            f"Refunded purchases {checked.refunded_purchases} of "
            f"{checked.refunded_purchases_expected}; copies ended as refunded "
            f"{checked.refund_ended_copies} of {checked.refund_ended_copies_expected}."
        )
        for (access, format), count in checked.copies_by_access.items():
            self.stdout.write(f"Copies {access}/{format}: {count}")
        for target, (legacy_total, valued) in checked.valuations.items():
            self.stdout.write(
                f"Valued in {target}: legacy {legacy_total}, seeded {valued}"
            )
        failures = checked.failures()
        if failures:
            for failure in failures:
                self.stdout.write(self.style.ERROR(failure))
            raise CommandError(
                f"{len(failures)} unexplained difference(s); nothing converted."
            )

    @staticmethod
    def _backlog(library: UserLibrary) -> tuple[int, int, int]:
        figures = compute_stats(library, None)
        tracked = PlayerGame.objects.filter(
            library=library, removed_at__isnull=True
        ).count()
        return (
            figures["purchased_unfinished_count"],
            figures["dropped_count"],
            tracked,
        )

    @staticmethod
    def _get_user(username: str) -> User:
        user_model = get_user_model()
        try:
            return user_model.objects.get(username=username)
        except user_model.DoesNotExist as error:
            raise CommandError(f"User {username!r} does not exist.") from error
