import gzip
from datetime import UTC, date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import UUID

import pytest
import yaml
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import transaction
from django.test import TransactionTestCase

from games.commands.playergame import TrackGame
from games.commands.playthrough import (
    CompletePlaythrough,
    DescribePlaythrough,
    StartPlaythrough,
)
from games.events.dispatch import dispatch
from games.management.commands.anonymize_sample import Command as AnonymizeCommand
from games.models import (
    Device,
    Game,
    LibraryEvent,
    Platform,
    Playthrough,
    Purchase,
    Session,
)
from games.retention import purging_library
from timetracker.temporal import TemporalValue

#: _build_dataset dispatches TrackGame/StartPlaythrough/CompletePlaythrough
#: itself now, so the autouse _track_created_games fixture's event-less
#: PlayerGame/Playthrough rows would only get in the way -- every event this
#: file dumps must trace back to a real LibraryEvent aggregate.
pytestmark = pytest.mark.untracked_games

# Models whose UUIDv7 identity has been promoted to their primary key carry it
# in the record's `pk`; the rest still carry it in a `uuid` field.
PROMOTED_MODELS = frozenset(
    [
        "games.game",
        "games.device",
        "games.filterpreset",
        "games.platform",
        "games.purchase",
        "games.session",
        "games.libraryevent",
        "games.libraryeventstreamhead",
        "games.libraryeventreference",
    ]
)


def identity(record):
    if record["model"] in PROMOTED_MODELS:
        return record["pk"]
    return record["fields"]["uuid"]


def _uuid_moment(value):
    """The millisecond a UUIDv7 embeds, as a timezone-aware datetime."""
    return datetime.fromtimestamp((UUID(str(value)).int >> 80) / 1000, UTC)


def _parsed_moment(value):
    moment = (
        value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    )
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.replace(microsecond=moment.microsecond // 1000 * 1000)


GENERATED_KEYS = {
    "price_per_game",
    "duration_calculated",
    "duration_total",
    "days_to_finish",
}


def _build_dataset():
    """A small dataset exercising every branch the anonymizer must handle."""
    owner = get_user_model().objects.create_user(username="sample-source")
    platform = Platform.objects.create(name="Steam", group="PC")
    device = Device.objects.create(
        library=owner.library,
        name="Anna's laptop",
    )
    games = [
        Game.objects.create(library=owner.library, name=f"Game {index}")
        for index in range(5)
    ]

    base_game = games[0]
    game_purchase = Purchase.objects.create(
        library=owner.library,
        price_currency="CZK",
        platform=platform,
        date_purchased=date(2021, 5, 1),
        date_refunded=date(2021, 5, 10),
        price=42.0,
        name="Humble order #12345",
    )
    game_purchase.games.set([games[1], games[2]])

    dlc_purchase = Purchase.objects.create(
        library=owner.library,
        price_currency="CZK",
        platform=platform,
        date_purchased=date(2022, 3, 3),
        price=9.99,
        type=Purchase.DLC,
        related_game=base_game,
    )
    dlc_purchase.games.set([games[3]])

    # Sessions include an open row and one with NULL manual duration.
    Session.objects.create(
        game=games[1],
        timestamp_start=datetime(2021, 6, 1, 20, 0, tzinfo=UTC),
        timestamp_end=datetime(2021, 6, 1, 22, 0, tzinfo=UTC),
        device=device,
        note="played after dinner",
    )
    Session.objects.create(
        game=games[0],
        timestamp_start=datetime(2021, 7, 1, 10, 0, tzinfo=UTC),
        timestamp_end=None,
        note="open session",
    )
    Session.objects.create(
        game=games[2],
        timestamp_start=datetime(2021, 8, 1, 12, 0, tzinfo=UTC),
        timestamp_end=datetime(2021, 8, 1, 13, 0, tzinfo=UTC),
        duration_manual=None,
    )

    dispatch(
        TrackGame(game_id=games[1].pk),
        actor=owner,
        library=owner.library,
        idempotency_key="track-1",
    )
    run_one = Playthrough.objects.get(player_game__game=games[1])
    dispatch(
        StartPlaythrough(
            playthrough_id=run_one.pk,
            when=TemporalValue.from_day(date(2021, 6, 1)),
            note="",
        ),
        actor=owner,
        library=owner.library,
        idempotency_key="start-1",
    )
    dispatch(
        CompletePlaythrough(
            playthrough_id=run_one.pk,
            when=TemporalValue.from_day(date(2021, 6, 20)),
            note="finished on holiday",
        ),
        actor=owner,
        library=owner.library,
        idempotency_key="complete-1",
    )

    dispatch(
        TrackGame(game_id=games[2].pk),
        actor=owner,
        library=owner.library,
        idempotency_key="track-2",
    )
    run_two = Playthrough.objects.get(player_game__game=games[2])
    dispatch(
        DescribePlaythrough(playthrough_id=run_two.pk, name=None, note="wishlist"),
        actor=owner,
        library=owner.library,
        idempotency_key="describe-2",
    )

    return game_purchase, dlc_purchase


def _load_output(path):
    with gzip.open(path, "rt") as stream:
        return yaml.safe_load(stream)


class AnonymizeSampleTest(TransactionTestCase):
    def test_rollback_leaves_source_database_unchanged(self):
        game_purchase, _ = _build_dataset()
        # Sentinels chosen outside the anonymizer's output range.
        game_purchase.price = 999.0
        game_purchase.name = "SENTINEL"
        game_purchase.save()
        session = Session.objects.get(note="played after dinner")

        with TemporaryDirectory() as tempdir:
            call_command(
                "anonymize_sample",
                user="sample-source",
                seed=1,
                output=Path(tempdir) / "out.yaml.gz",
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
            call_command("anonymize_sample", user="sample-source", seed=7, output=first)
            call_command(
                "anonymize_sample", user="sample-source", seed=7, output=second
            )
            self.assertEqual(first.read_bytes(), second.read_bytes())

    def test_requires_an_explicit_existing_user(self):
        _build_dataset()
        with TemporaryDirectory() as tempdir, self.assertRaises(CommandError):
            call_command("anonymize_sample", output=Path(tempdir) / "out.yaml.gz")

    def test_output_invariants(self):
        _build_dataset()
        with TemporaryDirectory() as tempdir:
            output = Path(tempdir) / "out.yaml.gz"
            call_command(
                "anonymize_sample", user="sample-source", seed=3, output=output
            )
            objects = _load_output(output)

        by_model = {}
        for item in objects:
            by_model.setdefault(item["model"], []).append(item)
            self.assertFalse(
                GENERATED_KEYS & item["fields"].keys(),
                f"generated key leaked into {item['model']}",
            )
            if item["model"] in PROMOTED_MODELS:
                self.assertEqual(UUID(str(item["pk"])).version, 7)
                self.assertNotIn("uuid", item["fields"])

        for purchase in by_model["games.purchase"]:
            fields = purchase["fields"]
            self.assertEqual(fields["name"], "")
            self.assertFalse(fields["needs_price_update"])
            self.assertGreaterEqual(fields["price"], 0)
            self.assertLessEqual(fields["price"], 100)
            self.assertGreaterEqual(len(fields["games"]), 1)
            self.assertLessEqual(len(fields["games"]), 10)
            if fields["type"] != Purchase.GAME:
                self.assertIn(
                    str(fields["related_game"]),
                    {str(identity(item)) for item in by_model["games.game"]},
                    "related_game must name a game identity in the same dump",
                )

        for session in by_model["games.session"]:
            self.assertEqual(session["fields"]["note"], "")
            # Audit timestamp is derived from the jittered start, never a real date.
            self.assertEqual(
                session["fields"]["created_at"], session["fields"]["timestamp_start"]
            )

        for event in by_model.get("games.libraryevent", []):
            payload = event["fields"]["payload"]
            if "note" in payload:
                self.assertEqual(payload["note"], "")
            if "name" in payload:
                self.assertEqual(payload["name"], "")
        for reference in by_model.get("games.libraryeventreference", []):
            self.assertNotEqual(reference["fields"]["payload_key"], "")

    def test_output_reloads_via_loaddata(self):
        game_purchase, _ = _build_dataset()
        source_user = game_purchase.library.user
        with TemporaryDirectory() as tempdir:
            output = Path(tempdir) / "out.yaml.gz"
            call_command(
                "anonymize_sample", user="sample-source", seed=5, output=output
            )
            with purging_library():
                source_user.delete()
            target = get_user_model().objects.create_user(username="sample-target")
            with patch(
                "games.management.commands.load_sample_data.FIXTURE_PATH",
                output,
            ):
                call_command("load_sample_data", "--user", target.username)

        for purchase in Purchase.objects.all():
            self.assertEqual(purchase.library, target.library)
            self.assertLessEqual(purchase.price, 100)
            self.assertEqual(purchase.name, "")
        self.assertEqual(Session.objects.count(), 3)
        self.assertTrue(
            all(session.pk.version == 7 for session in Session.objects.all())
        )
        self.assertEqual(
            Playthrough.objects.filter(
                player_game__game__library=target.library
            ).count(),
            2,
        )
        events = LibraryEvent.objects.filter(library=target.library)
        self.assertEqual(events.count(), 7)
        self.assertTrue(all(event.pk.version == 7 for event in events))

    def test_scrub_devices_uses_stable_primary_key_ordinals(self):
        game_purchase, _ = _build_dataset()
        Device.objects.create(
            pk="00000000-0000-7000-8000-000000000101",
            library=game_purchase.library,
            name="Second source name",
        )
        Device.objects.create(
            pk="00000000-0000-7000-8000-000000000100",
            library=game_purchase.library,
            name="First source name",
        )
        with TemporaryDirectory() as tempdir:
            output = Path(tempdir) / "out.yaml.gz"
            call_command(
                "anonymize_sample",
                user="sample-source",
                seed=1,
                output=output,
                scrub_devices=True,
            )
            objects = _load_output(output)

        devices = sorted(
            (item for item in objects if item["model"] == "games.device"),
            key=lambda item: UUID(item["pk"]),
        )
        self.assertEqual(
            [device["fields"]["name"] for device in devices],
            ["Device 1", "Device 2", "Device 3"],
        )

    def test_name_overrides_rename_games(self):
        game_purchase, _ = _build_dataset()
        secret = Game.objects.create(
            library=game_purchase.library,
            name="Real Secret Title",
        )
        with TemporaryDirectory() as tempdir:
            overrides = Path(tempdir) / "name_overrides.yaml"
            overrides.write_text("Real Secret Title: Placeholder Title\n")
            output = Path(tempdir) / "out.yaml.gz"
            call_command(
                "anonymize_sample",
                user="sample-source",
                seed=1,
                output=output,
                name_overrides=overrides,
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

    @pytest.mark.untracked_games
    def test_exports_only_the_selected_library_with_portable_owner_markers(self):
        _build_dataset()
        outsider = get_user_model().objects.create_user(username="sample-outsider")
        Game.objects.create(library=outsider.library, name="FOREIGN SECRET GAME")

        with TemporaryDirectory() as tempdir:
            output = Path(tempdir) / "out.yaml.gz"
            call_command(
                "anonymize_sample",
                user="sample-source",
                seed=11,
                output=output,
            )
            objects = _load_output(output)

        game_names = {
            item["fields"]["name"] for item in objects if item["model"] == "games.game"
        }
        self.assertNotIn("FOREIGN SECRET GAME", game_names)
        for item in objects:
            if item["model"] in {
                "games.device",
                "games.game",
                "games.purchase",
                "games.filterpreset",
            }:
                self.assertEqual(
                    item["fields"]["library"],
                    "__target_library__",
                )
            if item["model"] == "games.platform":
                self.assertIn(
                    item["fields"].get("library"),
                    (None, "__target_library__"),
                )


class ReassignedIdentityTest(TransactionTestCase):
    """The anonymizer must derive uuids from the dates it just randomised.

    A UUIDv7 embeds its creation millisecond, so leaving the source database's
    uuids in place both leaks the real timestamps the command exists to hide and
    breaks the ordering invariant `audit_uuid_identity` gates on.
    """

    def _dump(self, seed=11):
        _build_dataset()
        with TemporaryDirectory() as tempdir:
            output = Path(tempdir) / "out.yaml.gz"
            call_command(
                "anonymize_sample", user="sample-source", seed=seed, output=output
            )
            objects = _load_output(output)
        by_model = {}
        for item in objects:
            by_model.setdefault(item["model"], []).append(item)
        return by_model

    def test_uuid_timestamps_track_the_anonymized_created_at(self):
        by_model = self._dump()

        for game in by_model["games.game"]:
            self.assertEqual(
                _uuid_moment(identity(game)),
                _parsed_moment(game["fields"]["created_at"]),
            )
        for session in by_model["games.session"]:
            self.assertEqual(
                _uuid_moment(identity(session)),
                _parsed_moment(session["fields"]["created_at"]),
            )

    def test_output_preserves_uuid_ordering(self):
        by_model = self._dump()

        for model_label in ("games.game", "games.session", "games.purchase"):
            records = by_model[model_label]
            by_uuid = [
                item["pk"]
                for item in sorted(records, key=lambda item: UUID(str(identity(item))))
            ]
            by_created = [
                item["pk"]
                for item in sorted(
                    records,
                    key=lambda item: (str(item["fields"]["created_at"]), item["pk"]),
                )
            ]
            self.assertEqual(by_uuid, by_created, model_label)

    def test_related_game_reference_follows_the_new_uuid(self):
        by_model = self._dump()

        emitted = {identity(item) for item in by_model["games.game"]}
        for purchase in by_model["games.purchase"]:
            related = purchase["fields"]["related_game"]
            if related is not None:
                self.assertIn(str(related), {str(value) for value in emitted})

    def test_session_and_event_reference_follow_the_new_uuid(self):
        by_model = self._dump()

        games = {str(identity(item)) for item in by_model["games.game"]}
        devices = {str(identity(item)) for item in by_model["games.device"]}
        for session in by_model["games.session"]:
            self.assertIn(str(session["fields"]["game"]), games)
            device = session["fields"]["device"]
            if device is not None:
                self.assertIn(str(device), devices)
        for reference in by_model.get("games.libraryeventreference", []):
            if reference["fields"]["kind"] == "catalog.game":
                self.assertIn(str(reference["fields"]["referenced_id"]), games)

    def test_hidden_device_referrer_follows_the_new_uuid(self):
        """UserLibraryPreferences.default_device is related_name="+".

        Django's `_meta.related_objects` filters hidden relations out, so a
        referrer walk built on it strands this one on a uuid no Device carries.
        The row is never dumped, so only the database shows it - and only from
        inside the command's transaction, since `_write_fixture` runs after the
        rollback.
        """
        _build_dataset()
        library = get_user_model().objects.get(username="sample-source").library
        preferences = library.preferences
        preferences.default_device = Device.objects.get(library=library)
        preferences.save()

        with transaction.atomic():
            AnonymizeCommand()._reassign_uuids()

        preferences.refresh_from_db()
        self.assertTrue(
            Device.objects.filter(pk=preferences.default_device_id).exists(),
            "default_device still names a primary key no Device carries",
        )
