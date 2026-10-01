"""Convert one library's legacy purchases; reconcile."""

import json
from pathlib import Path
from typing import NamedTuple, cast

from django.contrib.auth import get_user_model
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from games.backfill.purchase import (
    LibraryConversion,
    PurchaseConversionDrift,
    PurchaseConversionRefused,
    convert_purchases,
    legacy_rows,
)
from games.backfill.purchase_plan import LegacyRow
from games.backfill.purchase_reconciliation import (
    legacy_figures,
    legacy_statistics,
    reconcile,
    review_lists,
)
from games.models import LegacyPurchase, PlayerGame, UserLibrary
from games.views.stats_data import compute_stats


class _Preflight(Exception):
    """Rolls the preflight back."""


class Backlog(NamedTuple):
    """Figures the exclusions move."""

    unfinished: int
    dropped: int
    tracked: int


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
        library = self._library(username)
        rows = legacy_rows(LegacyPurchase, library.pk)
        if options["snapshot"] is not None:
            snapshot = legacy_statistics(LegacyPurchase, library, rows)
            options["snapshot"].write_text(json.dumps(snapshot, indent=2) + "\n")
            self.stdout.write(
                f"Snapshot of {len(snapshot['scopes'])} scope(s) written."
            )
        try:
            with transaction.atomic():
                if not self._convert(library, rows):
                    return
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

    def _convert(self, library: UserLibrary, rows: list[LegacyRow]) -> bool:
        """Whether the pass had anything to state."""
        legacy = legacy_figures(LegacyPurchase, library, None).values
        before = Backlog(
            unfinished=cast(int, legacy["purchased_unfinished_count"]),
            dropped=cast(int, legacy["dropped_count"]),
            tracked=self._tracked(library),
        )
        try:
            conversion = convert_purchases(rows)
        except PurchaseConversionRefused as refused:
            for refusal in refused.refusals:
                self.stdout.write(self.style.ERROR(str(refusal)))
            raise CommandError(
                f"{len(refused.refusals)} refusal(s); nothing converted."
            ) from refused
        except PurchaseConversionDrift as drift:
            raise CommandError(f"{drift} Nothing converted.") from drift
        if conversion.nothing_awaited:
            self.stdout.write(
                f"{len(rows)} legacy row(s); no live copy awaits conversion."
            )
            return False
        [done] = conversion.libraries
        self._report(library, rows, done)
        figures = compute_stats(library, None)
        after = Backlog(
            unfinished=figures["purchased_unfinished_count"],
            dropped=figures["dropped_count"],
            tracked=self._tracked(library),
        )
        self.stdout.write(
            f"Backlog: unfinished {before.unfinished} -> {after.unfinished}, "
            f"dropped {before.dropped} -> {after.dropped}; "
            f"tracked games {before.tracked} -> {after.tracked}."
        )
        return True

    def _report(
        self, library: UserLibrary, rows: list[LegacyRow], done: LibraryConversion
    ) -> None:
        checked = reconcile(rows, done)
        self.stdout.write(
            f"{len(rows)} legacy row(s): {checked.planned_copies} planned "
            f"copies, {checked.own_copies} copies and {checked.purchases} purchases "
            f"stated, {checked.skipped} skipped, {checked.unvalued} unvalued; "
            f"{done.appended} events appended."
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
            f"Refunded purchases {checked.refunded_purchases.actual} of "
            f"{checked.refunded_purchases.expected}; copies ended as refunded "
            f"{checked.refund_ended_copies.actual} of "
            f"{checked.refund_ended_copies.expected}."
        )
        for skip in done.skipped:
            self.stdout.write(
                f"Skipped {skip.legacy_id}, game {skip.game_id}: the library "
                "removed the game."
            )
        for item in done.unvalued:
            self.stdout.write(
                f"Unvalued {item.purchase_id} of {item.legacy_id}: {item.reason}"
            )
        for (access, format), count in checked.copies_by_access.items():
            self.stdout.write(f"Copies {access}/{format}: {count}")
        for target, valuation in checked.valuations.items():
            self.stdout.write(
                f"Valued in {target}: legacy {valuation.legacy}, "
                f"seeded {valuation.seeded}"
            )
        failures = checked.failures()
        if failures:
            for failure in failures:
                self.stdout.write(self.style.ERROR(failure))
            raise CommandError(
                f"{len(failures)} unexplained difference(s); nothing converted."
            )

    @staticmethod
    def _tracked(library: UserLibrary) -> int:
        return PlayerGame.objects.filter(
            library=library, removed_at__isnull=True
        ).count()

    @classmethod
    def _library(cls, username: str) -> UserLibrary:
        user = cls._get_user(username)
        try:
            return user.library
        except UserLibrary.DoesNotExist as error:
            raise CommandError(f"User {username!r} holds no library.") from error

    @staticmethod
    def _get_user(username: str) -> User:
        user_model = get_user_model()
        try:
            return user_model.objects.get(username=username)
        except user_model.DoesNotExist as error:
            raise CommandError(f"User {username!r} does not exist.") from error
