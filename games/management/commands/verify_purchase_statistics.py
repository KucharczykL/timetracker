"""Judge every purchase figure against the legacy snapshot."""

import json
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from games.backfill.purchase_reconciliation import ALL_TIME
from games.models import UserLibrary
from games.purchase_parity import (
    ConversionMap,
    SnapshotRefused,
    judge_purchase_scope,
    read_snapshot,
)
from games.stats_parity import unattributed
from games.views.stats_data import compute_stats


class Command(BaseCommand):
    help = (
        "Read a format-2 snapshot written before the conversion, compute "
        "every statistics scope now, and attribute each figure that moved. "
        "Read-only. Fails on any figure no reason explains."
    )

    def add_arguments(self, parser):
        parser.add_argument("--user", required=True, help="Username to judge.")
        parser.add_argument(
            "--snapshot", required=True, type=Path, help="The legacy snapshot."
        )

    def handle(self, *args, **options):
        library = self._library(options["user"])
        try:
            scopes = read_snapshot(json.loads(options["snapshot"].read_text()), library)
        except SnapshotRefused as refused:
            raise CommandError(str(refused)) from refused
        mapping = ConversionMap.read(library)
        failed = 0
        for label, snapshot in scopes.items():
            year = None if label == ALL_TIME else int(label)
            judged = judge_purchase_scope(
                snapshot, compute_stats(library, year), library, year, mapping
            )
            self.stdout.write(f"== {label}")
            for judgement in judged.judgements:
                for legacy, reasons in judgement.explained.items():
                    named = ", ".join(str(reason) for reason in reasons)
                    self.stdout.write(f"  {judgement.rows_key} {legacy}: {named}")
                for legacy in judgement.unexplained:
                    self.stdout.write(
                        self.style.ERROR(f"  {judgement.rows_key} {legacy}: no reason")
                    )
            for change in judged.changes:
                line = (
                    f"  {change.key}: {change.before} -> {change.after}"
                    f" ({change.attribution or 'unattributed'})"
                )
                if change.attribution is None:
                    self.stdout.write(self.style.ERROR(line))
                else:
                    self.stdout.write(line)
            failed += len(unattributed(judged.changes))
        if failed:
            raise CommandError(f"{failed} unattributed figure(s).")
        self.stdout.write(self.style.SUCCESS("Every figure is attributed."))

    @staticmethod
    def _library(username: str) -> UserLibrary:
        user_model = get_user_model()
        try:
            return user_model.objects.get(username=username).library
        except user_model.DoesNotExist as error:
            raise CommandError(f"User {username!r} does not exist.") from error
        except UserLibrary.DoesNotExist as error:
            raise CommandError(f"User {username!r} holds no library.") from error
