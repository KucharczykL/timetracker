from __future__ import annotations

from collections import Counter

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import DEFAULT_DB_ALIAS, transaction
from django.db.models.deletion import Collector

from games.retention import purging_library


class Command(BaseCommand):
    help = (
        "Show or execute the complete cascade caused by deleting one User and "
        "their library. Dry-run is the default."
    )

    def add_arguments(self, parser):
        parser.add_argument("--user", required=True, help="Username to inspect.")
        parser.add_argument(
            "--confirm",
            help="Delete only when this value exactly matches --user.",
        )

    def handle(self, *args, **options):
        username = options["user"]
        confirmation = options["confirm"]
        if confirmation is None:
            user = self._get_user(username)
            self._write_deletion_scope(self._deletion_counts(user))
            self.stdout.write(
                self.style.WARNING(
                    f"DRY RUN: no data deleted. Re-run with --confirm {username}."
                )
            )
            return
        if confirmation != username:
            raise CommandError("--confirm must exactly match --user; nothing deleted.")

        # A purge takes the events with the rows they reference, so the
        # retention guard has nothing left to protect and would only stand in
        # the way of the one operation allowed to leave nothing behind.
        with transaction.atomic(), purging_library():
            user = self._get_user(username, for_update=True)
            self._write_deletion_scope(self._deletion_counts(user))
            user.delete()
        self.stdout.write(
            self.style.SUCCESS(f"DELETED User {username!r} and the scope above.")
        )

    @staticmethod
    def _get_user(username, *, for_update=False):
        user_model = get_user_model()
        users = user_model.objects
        if for_update:
            users = users.select_for_update()
        try:
            return users.get(username=username)
        except user_model.DoesNotExist as error:
            raise CommandError(f"User {username!r} does not exist.") from error

    def _write_deletion_scope(self, counts):
        self.stdout.write(
            self.style.WARNING(
                "WARNING: deleting this User cascades through their library and "
                "all private library data."
            )
        )
        self.stdout.write("Deletion scope:")
        for label, count in sorted(counts.items()):
            self.stdout.write(f"  {label}: {count}")

    @staticmethod
    def _deletion_counts(user):
        collector = Collector(using=DEFAULT_DB_ALIAS)
        collector.collect([user])
        counts = Counter()
        for model, objects in collector.data.items():
            counts[model._meta.label] += len(objects)
        for queryset in collector.fast_deletes:
            counts[queryset.model._meta.label] += queryset.count()
        return counts
