import gzip
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
import yaml
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import transaction
from django.test import TransactionTestCase

from games.commands.playergame import TrackGame
from games.commands.playersession import (
    CorrectedTiming,
    DurationOnlyTiming,
    TimedTiming,
)
from games.commands.playthrough import (
    CompletePlaythrough,
    DescribePlaythrough,
    StartPlaythrough,
)
from games.events.dispatch import dispatch
from games.events.playersession import day_from_text, instant_from_text
from games.events.vocabulary import DEFAULT_EVENT_TYPES
from games.management.commands.anonymize_sample import (
    Command as AnonymizeCommand,
)
from games.management.commands.anonymize_sample import (
    shift_dated,
    shift_instant,
)
from games.models import (
    Device,
    Game,
    LibraryCalendar,
    LibraryEvent,
    Platform,
    PlayerSession,
    Playthrough,
    Purchase,
)
from games.removal import remove
from games.retention import purging_library
from games.writes.playersession import SessionDraft, record_session, remove_session
from timetracker.settings_commands import CALENDAR_SETTING_KEY, change_user_setting
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
        "games.libraryevent",
        "games.libraryeventstreamhead",
        "games.libraryeventreference",
    ]
)

#: The zone the source library counts days in; not the settings default.
SOURCE_ZONE = "America/New_York"
#: The first session's start, as recorded; the day it lands on is 2021-06-01.
FIRST_SESSION_START = datetime(2021, 6, 1, 20, 0, tzinfo=ZoneInfo(SOURCE_ZONE))
FIRST_SESSION_ELAPSED = timedelta(hours=2)


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


GENERATED_KEYS = {"price_per_game"}


def _record(owner, run, timing, *, device=None, note=""):
    return record_session(
        owner,
        SessionDraft(
            playthrough_id=run.pk,
            timing=timing,
            device_id=None if device is None else device.pk,
            note=note,
            emulated=False,
        ),
        correlation_id=uuid.uuid7(),
    )


def _build_dataset():
    """A small dataset exercising every branch the anonymizer must handle."""
    owner = get_user_model().objects.create_user(username="sample-source")
    #: A calendar event, and the zone every session below counts days in.
    change_user_setting(owner, CALENDAR_SETTING_KEY, SOURCE_ZONE)
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

    #: Three sessions: one per timing mode, the Corrected one removed.
    _record(
        owner,
        run_one,
        TimedTiming(
            started_at=FIRST_SESSION_START,
            day_zone=SOURCE_ZONE,
            started_at_zone=SOURCE_ZONE,
            ended_at=FIRST_SESSION_START + FIRST_SESSION_ELAPSED,
            ended_at_zone=SOURCE_ZONE,
        ),
        device=device,
        note="played after dinner",
    )
    _record(
        owner,
        run_two,
        DurationOnlyTiming(day=date(2021, 8, 1), duration=timedelta(hours=1)),
    )
    corrected_id = _record(
        owner,
        run_one,
        CorrectedTiming(
            started_at=datetime(2021, 7, 1, 10, 0, tzinfo=UTC),
            ended_at=datetime(2021, 7, 1, 12, 0, tzinfo=UTC),
            duration=timedelta(minutes=90),
            day_zone=SOURCE_ZONE,
        ),
    )
    remove_session(
        owner, PlayerSession.objects.get(pk=corrected_id), correlation_id=uuid.uuid7()
    )

    return game_purchase, dlc_purchase


def _load_output(path):
    with gzip.open(path, "rt") as stream:
        return yaml.safe_load(stream)


def _by_model(objects):
    by_model = {}
    for item in objects:
        by_model.setdefault(item["model"], []).append(item)
    return by_model


def _events_of(by_model, event_type):
    return [
        event
        for event in by_model.get("games.libraryevent", [])
        if event["fields"]["event_type"] == event_type
    ]


def _day_of(event):
    return TemporalValue.parse(event["fields"]["effective_time"]).lower_bound


# --- the pure shifts -----------------------------------------------------------


def test_an_instant_keeps_its_wall_time_across_a_daylight_saving_change():
    #: 2021-03-13 20:00 New York is EST; 21 days later the same wall time is EDT.
    moved = shift_instant("2021-03-14T01:00:00Z", days=21, zone=SOURCE_ZONE)
    local = instant_from_text(moved).astimezone(ZoneInfo(SOURCE_ZONE))
    assert (local.date(), local.hour) == (date(2021, 4, 3), 20)


def test_a_timing_statement_keeps_its_elapsed_time_and_moves_its_day():
    payload = {
        "timing": {
            "mode": "timed",
            "started_at": "2021-03-14T01:00:00Z",
            "started_at_zone": SOURCE_ZONE,
            "ended_at": "2021-03-14T03:30:00Z",
            "ended_at_zone": SOURCE_ZONE,
            "day_zone": SOURCE_ZONE,
        },
        "note": "",
    }
    keys = DEFAULT_EVENT_TYPES.dated_keys("library.playersession.created")
    shifted = shift_dated(payload, keys, days=21)["timing"]
    started = instant_from_text(shifted["started_at"])
    ended = instant_from_text(shifted["ended_at"])
    assert ended - started == timedelta(hours=2, minutes=30)
    assert started.astimezone(ZoneInfo(SOURCE_ZONE)).date() == date(2021, 4, 3)
    assert payload["timing"]["started_at"] == "2021-03-14T01:00:00Z", "a copy"


def test_a_stated_day_moves_as_a_date():
    payload = {
        "timing": {
            "mode": "duration_only",
            "stated_day": "2021-12-25",
            "duration_seconds": 5,
        }
    }
    keys = DEFAULT_EVENT_TYPES.dated_keys("library.playersession.created")
    assert shift_dated(payload, keys, days=-30)["timing"]["stated_day"] == "2021-11-25"


def test_an_end_stated_alone_moves_in_its_own_zone():
    keys = DEFAULT_EVENT_TYPES.dated_keys("library.playersession.ended")
    shifted = shift_dated(
        {"ended_at": "2021-03-14T01:00:00Z", "ended_at_zone": SOURCE_ZONE},
        keys,
        days=21,
    )
    local = instant_from_text(shifted["ended_at"]).astimezone(ZoneInfo(SOURCE_ZONE))
    assert (local.date(), local.hour) == (date(2021, 4, 3), 20)


# --- the command -------------------------------------------------------------


class AnonymizeSampleTest(TransactionTestCase):
    def test_rollback_leaves_source_database_unchanged(self):
        game_purchase, _ = _build_dataset()
        # Sentinels chosen outside the anonymizer's output range.
        game_purchase.price = 999.0
        game_purchase.name = "SENTINEL"
        game_purchase.save()
        session = PlayerSession.objects.get(note="played after dinner")
        created = LibraryEvent.objects.get(
            aggregate_id=session.pk, event_type="library.playersession.created"
        )

        with TemporaryDirectory() as tempdir:
            call_command(
                "anonymize_sample",
                user="sample-source",
                seed=1,
                output=Path(tempdir) / "out.yaml.gz",
            )

        game_purchase.refresh_from_db()
        session.refresh_from_db()
        created.refresh_from_db()
        self.assertEqual(game_purchase.price, 999.0)
        self.assertEqual(game_purchase.name, "SENTINEL")
        self.assertEqual(session.note, "played after dinner")
        self.assertEqual(created.payload["note"], "played after dinner")
        self.assertEqual(session.started_at, FIRST_SESSION_START)

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

        by_model = _by_model(objects)
        for item in objects:
            self.assertFalse(
                GENERATED_KEYS & item["fields"].keys(),
                f"generated key leaked into {item['model']}",
            )
            if item["model"] in PROMOTED_MODELS:
                self.assertEqual(UUID(str(item["pk"])).version, 7)
                self.assertNotIn("uuid", item["fields"])
        self.assertNotIn("games.session", by_model)

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

        for event in by_model["games.libraryevent"]:
            payload = event["fields"]["payload"]
            if "note" in payload:
                self.assertEqual(payload["note"], "")
            if "name" in payload:
                self.assertEqual(payload["name"], "")
            self.assertEqual(event["fields"]["source_metadata"], {})
            self.assertIsNone(event["fields"]["actor"])
        for reference in by_model.get("games.libraryeventreference", []):
            self.assertNotEqual(reference["fields"]["payload_key"], "")

    def test_session_events_move_with_their_run_and_keep_their_shape(self):
        _build_dataset()
        with TemporaryDirectory() as tempdir:
            output = Path(tempdir) / "out.yaml.gz"
            call_command(
                "anonymize_sample", user="sample-source", seed=3, output=output
            )
            by_model = _by_model(_load_output(output))

        #: The run's start event says how far its game moved.
        (started,) = _events_of(by_model, "library.playthrough.started")
        offset = _day_of(started) - date(2021, 6, 1)
        self.assertNotEqual(offset, timedelta(0))
        created = _events_of(by_model, "library.playersession.created")
        self.assertEqual(len(created), 3)
        by_mode = {
            event["fields"]["payload"]["timing"]["mode"]: event for event in created
        }
        timed = by_mode["timed"]["fields"]
        timing = timed["payload"]["timing"]
        started_at = instant_from_text(timing["started_at"])
        self.assertEqual(
            started_at.astimezone(ZoneInfo(SOURCE_ZONE)).date(),
            date(2021, 6, 1) + offset,
        )
        self.assertEqual(
            instant_from_text(timing["ended_at"]) - started_at, FIRST_SESSION_ELAPSED
        )
        self.assertEqual(_day_of(by_mode["timed"]), date(2021, 6, 1) + offset)
        self.assertEqual(
            _parsed_moment(timed["recorded_at"]),
            datetime.combine(date(2021, 6, 1) + offset, datetime.min.time(), UTC),
        )
        corrected = by_mode["corrected"]["fields"]["payload"]["timing"]
        self.assertEqual(corrected["duration_seconds"], 90 * 60)
        self.assertEqual(
            _day_of(by_mode["corrected"]), date(2021, 7, 1) + offset, "same run"
        )

        #: The device reference is re-captured at the dumped row.
        devices = {
            item["pk"]: item["fields"]["name"] for item in by_model["games.device"]
        }
        device = timed["payload"]["device"]
        self.assertIn(device["id"], devices)
        self.assertEqual(device["label"], devices[device["id"]])

        #: The run key follows the run's re-minted aggregate.
        runs = {
            event["fields"]["aggregate_id"]
            for event in _events_of(by_model, "library.playthrough.created")
        }
        for event in created:
            self.assertIn(event["fields"]["payload"]["playthrough"], runs)

        #: A removal follows its creation.
        (removed,) = _events_of(by_model, "library.playersession.removed")
        self.assertEqual(
            removed["fields"]["aggregate_id"],
            by_mode["corrected"]["fields"]["aggregate_id"],
        )
        self.assertGreaterEqual(
            _parsed_moment(removed["fields"]["recorded_at"]),
            _parsed_moment(by_mode["corrected"]["fields"]["recorded_at"]),
        )

        #: The calendar's aggregate is the owner, whoever loads it.
        (calendar,) = _events_of(by_model, "library.calendar.day_zone_changed")
        self.assertEqual(calendar["fields"]["aggregate_id"], "__target_library__")
        self.assertEqual(calendar["fields"]["payload"]["day_zone"], SOURCE_ZONE)

    def test_output_reloads_via_loaddata(self):
        game_purchase, _ = _build_dataset()
        source_user = game_purchase.library.user
        dispatch(
            TrackGame(game_id=Game.objects.get(name="Game 0").pk),
            actor=source_user,
            library=source_user.library,
            idempotency_key="track-0",
        )
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
        self.assertEqual(
            Playthrough.objects.filter(
                player_game__game__library=target.library
            ).count(),
            3,
        )
        events = LibraryEvent.objects.filter(library=target.library)
        #: Nine on games and runs, one calendar, three sessions, one removal.
        self.assertEqual(events.count(), 14)
        self.assertTrue(all(event.pk.version == 7 for event in events))
        sessions = PlayerSession.objects.filter(library=target.library)
        self.assertEqual(sessions.count(), 3)
        self.assertEqual(sessions.filter(removed_at__isnull=False).count(), 1)
        self.assertTrue(all(session.pk.version == 7 for session in sessions))
        calendar = LibraryCalendar.objects.get(library=target.library)
        self.assertEqual(calendar.pk, target.library.pk)
        self.assertEqual(calendar.day_zone, SOURCE_ZONE)

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
            by_model = _by_model(_load_output(output))

        devices = sorted(by_model["games.device"], key=lambda item: UUID(item["pk"]))
        self.assertEqual(
            [device["fields"]["name"] for device in devices],
            ["Device 1", "Device 2", "Device 3"],
        )
        #: The reference inside the payload carries the scrubbed name.
        names = {device["pk"]: device["fields"]["name"] for device in devices}
        referenced = [
            event["fields"]["payload"]["device"]
            for event in _events_of(by_model, "library.playersession.created")
            if event["fields"]["payload"]["device"] is not None
        ]
        self.assertTrue(referenced)
        for reference in referenced:
            self.assertEqual(reference["label"], names[reference["id"]])
            self.assertNotEqual(reference["label"], "Anna's laptop")

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

    def test_removed_game_is_dumped_but_never_reassigned_a_purchase(self):
        """A removed game owes a date offset like any other.

        Its PlayerGame, its Playthroughs, its events and its sessions all
        stay live, and each is shifted by *its own game's* offset -- so the
        offset map is keyed by every game the library holds, not by the live
        ones. Purchase links go the other way: a purchase is live only while
        one of its games is, so the reassignment pass must keep off it.
        """
        game_purchase, _ = _build_dataset()
        library = game_purchase.library
        shelved = Game.objects.create(library=library, name="Shelved Game")
        dispatch(
            TrackGame(game_id=shelved.pk),
            actor=library.user,
            library=library,
            idempotency_key="track-shelved",
        )
        _record(
            library.user,
            Playthrough.objects.get(player_game__game=shelved),
            DurationOnlyTiming(day=date(2021, 9, 1), duration=timedelta(hours=1)),
        )
        remove(shelved)

        with TemporaryDirectory() as tempdir:
            output = Path(tempdir) / "out.yaml.gz"
            call_command(
                "anonymize_sample", user="sample-source", seed=13, output=output
            )
            objects = _load_output(output)

        by_model = _by_model(objects)
        removed_rows = [
            item
            for item in by_model["games.game"]
            if item["fields"]["removed_at"] is not None
        ]
        self.assertEqual(len(removed_rows), 1)
        self.assertEqual(len(_events_of(by_model, "library.playersession.created")), 4)
        removed_identity = str(identity(removed_rows[0]))
        for purchase in by_model["games.purchase"]:
            self.assertNotIn(
                removed_identity,
                {str(game) for game in purchase["fields"]["games"]},
            )
            self.assertNotEqual(
                str(purchase["fields"]["related_game"]), removed_identity
            )

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
        return _by_model(objects)

    def test_uuid_timestamps_track_the_anonymized_dates(self):
        by_model = self._dump()

        for game in by_model["games.game"]:
            self.assertEqual(
                _uuid_moment(identity(game)),
                _parsed_moment(game["fields"]["created_at"]),
            )
        for event in by_model["games.libraryevent"]:
            self.assertEqual(
                _uuid_moment(identity(event)),
                _parsed_moment(event["fields"]["recorded_at"]),
            )

    def test_output_preserves_uuid_ordering(self):
        by_model = self._dump()

        for model_label, date_field in (
            ("games.game", "created_at"),
            ("games.purchase", "created_at"),
            ("games.libraryevent", "recorded_at"),
        ):
            records = by_model[model_label]
            by_uuid = [
                item["pk"]
                for item in sorted(records, key=lambda item: UUID(str(identity(item))))
            ]
            by_date = [
                item["pk"]
                for item in sorted(
                    records,
                    key=lambda item: (str(item["fields"][date_field]), item["pk"]),
                )
            ]
            self.assertEqual(by_uuid, by_date, model_label)

    def test_related_game_reference_follows_the_new_uuid(self):
        by_model = self._dump()

        emitted = {identity(item) for item in by_model["games.game"]}
        for purchase in by_model["games.purchase"]:
            related = purchase["fields"]["related_game"]
            if related is not None:
                self.assertIn(str(related), {str(value) for value in emitted})

    def test_every_reference_follows_the_new_uuid(self):
        by_model = self._dump()

        rows_by_kind = {
            "catalog.game": {str(identity(item)) for item in by_model["games.game"]},
            "device": {str(identity(item)) for item in by_model["games.device"]},
        }
        for event in by_model["games.libraryevent"]:
            fields = event["fields"]
            for found in DEFAULT_EVENT_TYPES.references_in(
                fields["event_type"], fields["payload"]
            ):
                self.assertIn(found.value["id"], rows_by_kind[found.value["kind"]])
        for reference in by_model.get("games.libraryeventreference", []):
            self.assertIn(
                str(reference["fields"]["referenced_id"]),
                rows_by_kind[reference["fields"]["kind"]],
            )

    def test_the_day_a_session_event_states_matches_its_payload(self):
        """The envelope's day and the payload's start move together."""
        by_model = self._dump()

        for event in by_model["games.libraryevent"]:
            fields = event["fields"]
            if fields["event_type"] != "library.playersession.created":
                continue
            timing = fields["payload"]["timing"]
            if timing["mode"] == "duration_only":
                stated = day_from_text(timing["stated_day"])
            else:
                stated = (
                    instant_from_text(timing["started_at"])
                    .astimezone(ZoneInfo(timing["day_zone"]))
                    .date()
                )
            self.assertEqual(_day_of(event), stated)

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
