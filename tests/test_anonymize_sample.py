import gzip
from datetime import date, datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

import yaml
from django.core.management import call_command
from django.test import TestCase

from games.models import Device, Game, PlayEvent, Platform, Purchase, Session

GENERATED_KEYS = {
    "price_per_game",
    "duration_calculated",
    "duration_total",
    "days_to_finish",
}


def _build_dataset():
    """A small dataset exercising every branch the anonymizer must handle."""
    platform = Platform.objects.create(name="Steam", group="PC")
    device = Device.objects.create(name="Anna's laptop")
    games = [Game.objects.create(name=f"Game {index}") for index in range(5)]

    base_game = games[0]
    game_purchase = Purchase.objects.create(
        platform=platform,
        date_purchased=date(2021, 5, 1),
        date_refunded=date(2021, 5, 10),
        price=42.0,
        name="Humble order #12345",
    )
    game_purchase.games.set([games[1], games[2]])

    dlc_purchase = Purchase.objects.create(
        platform=platform,
        date_purchased=date(2022, 3, 3),
        price=9.99,
        type=Purchase.DLC,
        related_game=base_game,
    )
    dlc_purchase.games.set([games[3]])

    # Session tied to a game, a session with game=None, and one with NULL manual.
    Session.objects.create(
        game=games[1],
        timestamp_start=datetime(2021, 6, 1, 20, 0, tzinfo=timezone.utc),
        timestamp_end=datetime(2021, 6, 1, 22, 0, tzinfo=timezone.utc),
        device=device,
        note="played after dinner",
    )
    Session.objects.create(
        game=None,
        timestamp_start=datetime(2021, 7, 1, 10, 0, tzinfo=timezone.utc),
        timestamp_end=None,
        note="gameless",
    )
    Session.objects.create(
        game=games[2],
        timestamp_start=datetime(2021, 8, 1, 12, 0, tzinfo=timezone.utc),
        timestamp_end=datetime(2021, 8, 1, 13, 0, tzinfo=timezone.utc),
        duration_manual=None,
    )

    PlayEvent.objects.create(
        game=games[1],
        started=date(2021, 6, 1),
        ended=date(2021, 6, 20),
        note="finished on holiday",
    )
    PlayEvent.objects.create(game=games[2], started=None, ended=None, note="wishlist")

    return game_purchase, dlc_purchase


def _load_output(path):
    with gzip.open(path, "rt") as stream:
        return yaml.safe_load(stream)


class AnonymizeSampleTest(TestCase):
    def test_rollback_leaves_source_database_unchanged(self):
        game_purchase, _ = _build_dataset()
        # Sentinels chosen outside the anonymizer's output range.
        game_purchase.price = 999.0
        game_purchase.name = "SENTINEL"
        game_purchase.save()
        session = Session.objects.get(note="played after dinner")

        with TemporaryDirectory() as tempdir:
            call_command(
                "anonymize_sample", seed=1, output=Path(tempdir) / "out.yaml.gz"
            )

        game_purchase.refresh_from_db()
        session.refresh_from_db()
        self.assertEqual(game_purchase.price, 999.0)
        self.assertEqual(game_purchase.name, "SENTINEL")
        self.assertEqual(session.note, "played after dinner")
        self.assertEqual(session.timestamp_start.year, 2021)

    def test_output_is_deterministic_for_a_fixed_seed(self):
        _build_dataset()
        with TemporaryDirectory() as tempdir:
            first = Path(tempdir) / "first.yaml.gz"
            second = Path(tempdir) / "second.yaml.gz"
            call_command("anonymize_sample", seed=7, output=first)
            call_command("anonymize_sample", seed=7, output=second)
            self.assertEqual(first.read_bytes(), second.read_bytes())

    def test_output_invariants(self):
        _build_dataset()
        with TemporaryDirectory() as tempdir:
            output = Path(tempdir) / "out.yaml.gz"
            call_command("anonymize_sample", seed=3, output=output)
            objects = _load_output(output)

        by_model = {}
        for item in objects:
            by_model.setdefault(item["model"], []).append(item)
            self.assertFalse(
                GENERATED_KEYS & item["fields"].keys(),
                f"generated key leaked into {item['model']}",
            )

        for purchase in by_model["games.purchase"]:
            fields = purchase["fields"]
            self.assertEqual(fields["name"], "")
            self.assertFalse(fields["needs_price_update"])
            self.assertGreaterEqual(fields["price"], 0)
            self.assertLessEqual(fields["price"], 100)
            self.assertGreaterEqual(len(fields["games"]), 1)
            self.assertLessEqual(len(fields["games"]), 10)
            if fields["type"] != Purchase.GAME:
                self.assertIsNotNone(fields["related_game"])

        for session in by_model["games.session"]:
            self.assertEqual(session["fields"]["note"], "")
            # Audit timestamp is derived from the jittered start, never a real date.
            self.assertEqual(
                session["fields"]["created_at"], session["fields"]["timestamp_start"]
            )

        for event in by_model["games.playevent"]:
            self.assertEqual(event["fields"]["note"], "")

    def test_output_reloads_via_loaddata(self):
        _build_dataset()
        with TemporaryDirectory() as tempdir:
            output = Path(tempdir) / "out.yaml.gz"
            call_command("anonymize_sample", seed=5, output=output)
            # loaddata over the same pks must parse and apply without error.
            call_command("loaddata", str(output))

        for purchase in Purchase.objects.all():
            self.assertLessEqual(purchase.price, 100)
            self.assertEqual(purchase.name, "")

    def test_scrub_devices_replaces_names(self):
        _build_dataset()
        with TemporaryDirectory() as tempdir:
            output = Path(tempdir) / "out.yaml.gz"
            call_command("anonymize_sample", seed=1, output=output, scrub_devices=True)
            objects = _load_output(output)

        for device in [item for item in objects if item["model"] == "games.device"]:
            self.assertRegex(device["fields"]["name"], r"^Device \d+$")

    def test_name_overrides_rename_games(self):
        _build_dataset()
        secret = Game.objects.create(name="Real Secret Title")
        with TemporaryDirectory() as tempdir:
            overrides = Path(tempdir) / "name_overrides.yaml"
            overrides.write_text("Real Secret Title: Placeholder Title\n")
            output = Path(tempdir) / "out.yaml.gz"
            call_command(
                "anonymize_sample", seed=1, output=output, name_overrides=overrides
            )
            objects = _load_output(output)

        names = {
            item["fields"]["name"] for item in objects if item["model"] == "games.game"
        }
        self.assertIn("Placeholder Title", names)
        self.assertNotIn("Real Secret Title", names)
        # Rename keeps the row (and its pk), it is not dropped.
        secret.refresh_from_db()
        self.assertEqual(secret.name, "Real Secret Title")  # source DB untouched
