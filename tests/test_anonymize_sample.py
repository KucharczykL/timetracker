import gzip
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
import yaml
from devices import create_device, end_device_access, remove_device
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import transaction
from django.test import TransactionTestCase
from entries import record_entry
from graphs import default_graph
from purchases import record_purchase, refund_purchase, request_run

from games import tasks
from games.catalog_writes import EditionState, ReleaseState, state_catalog_graph
from games.commands.endpoint import ActStatement
from games.commands.historical_playtime import (
    HistoricalPlaytimeStatement,
    RecordHistoricalPlaytime,
)
from games.commands.playergame import TrackGame
from games.commands.playersession import (
    CorrectedTiming,
    DurationOnlyTiming,
    TimedTiming,
)
from games.commands.playthrough import (
    CompletePlaythrough,
    CreatePlaythrough,
    DescribePlaythrough,
    StartPlaythrough,
)
from games.events.dispatch import dispatch
from games.events.historical_playtime import sorted_runs
from games.events.playersession import day_from_text, instant_from_text
from games.events.vocabulary import DEFAULT_EVENT_TYPES
from games.management.commands.anonymize_sample import (
    FIXED_EPOCH,
    GENERATED_FIELDS,
    JITTER_DAYS,
    rewrite_path,
    shift_dated,
    shift_instant,
)
from games.management.commands.anonymize_sample import (
    Command as AnonymizeCommand,
)
from games.models import (
    Device,
    Edition,
    Game,
    GameKind,
    HistoricalPlaytime,
    HistoricalPlaytimeProvenance,
    LibraryCalendar,
    LibraryEntry,
    LibraryEvent,
    LibraryEventReference,
    Platform,
    PlayerSession,
    Playthrough,
    Purchase,
    PurchaseValuation,
    Release,
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
        "games.edition",
        "games.release",
        "games.libraryevent",
        "games.libraryeventstreamhead",
        "games.libraryeventreference",
    ]
)

#: Source zone; not the settings default.
SOURCE_ZONE = "America/New_York"
#: First start; lands on 2021-06-01.
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


GENERATED_KEYS = {"release_date_lower", "release_date_upper", "release_date_kind"}


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


def fields_of_device(event) -> bool:
    """Whether the event concerns a device."""
    return event["fields"]["event_type"].startswith("library.device.")


def _device_names(by_model):
    """Device keys and names from creations."""
    return {
        event["fields"]["aggregate_id"]: event["fields"]["payload"]["name"]
        for event in _events_of(by_model, "library.device.created")
    }


def _build_dataset():
    """A small dataset exercising every branch the anonymizer must handle."""
    owner = get_user_model().objects.create_user(username="sample-source")
    #: One calendar event; every session's zone.
    change_user_setting(owner, CALENDAR_SETTING_KEY, SOURCE_ZONE)
    platform = Platform.objects.create(name="Steam", group="PC")
    device = create_device(owner.library, "Anna's laptop")
    games = [
        Game.objects.create(library=owner.library, name=f"Game {index}")
        for index in range(5)
    ]

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

    #: One session per mode; Corrected removed.
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
    #: Its runs travel inside a list.
    dispatch(
        RecordHistoricalPlaytime(
            statement=HistoricalPlaytimeStatement(
                duration=timedelta(hours=3),
                when="2021-06-05",
                provenance=HistoricalPlaytimeProvenance.ESTIMATED,
                playthrough_ids=(run_one.pk,),
                device_id=None,
                emulated=False,
                note="",
            )
        ),
        actor=owner,
        library=owner.library,
        idempotency_key="record-1",
    )

    #: A refunded purchase ends its copy.
    entry = record_entry(
        owner.library,
        default_graph(games[1], owner.library, platform=platform).release,
        note="from the shop",
    )
    game_purchase = record_purchase(
        entry,
        name="Humble order #12345",
        amount=Decimal("42.00"),
        currency="CZK",
        purchased=TemporalValue.from_day(date(2021, 5, 1)),
    )
    refund_purchase(game_purchase, TemporalValue.from_day(date(2021, 5, 10)))
    #: An untracked add-on, tracked by its copy.
    record_purchase(
        record_entry(
            owner.library,
            default_graph(games[3], owner.library, platform=platform).release,
        ),
        amount=Decimal("9.99"),
        currency="CZK",
        purchased=TemporalValue.from_day(date(2022, 3, 3)),
    )
    return game_purchase


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
    #: EST start; 21 days later EDT.
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


def test_a_rewrite_reaches_into_lists_and_skips_nulls():
    payload = {
        "runs": [{"id": "a"}, {"id": None}, {"other": "b"}],
        "ids": ["c", None],
        "absent": None,
    }

    for path in (("runs", "id"), ("ids",), ("absent", "id"), ("missing",)):
        rewrite_path(payload, path, str.upper)

    assert payload == {
        "runs": [{"id": "A"}, {"id": None}, {"other": "b"}],
        "ids": ["C", None],
        "absent": None,
    }


@pytest.mark.parametrize(
    ("payload", "path"),
    [({"note": "x"}, ("note", "text")), ({"amount": 12}, ("amount",))],
    ids=["scalar mid-path", "non-text leaf"],
)
def test_a_rewrite_refuses_a_shape_no_vocabulary_states(payload, path):
    with pytest.raises(CommandError):
        rewrite_path(payload, path, str.upper)


def test_the_pinned_generated_keys_are_derived():
    assert GENERATED_KEYS <= GENERATED_FIELDS["games.release"]


# --- the command -------------------------------------------------------------


class AnonymizeSampleTest(TransactionTestCase):
    def test_rollback_leaves_source_database_unchanged(self):
        game_purchase = _build_dataset()
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
        self.assertEqual(game_purchase.amount, Decimal("42.00"))
        self.assertEqual(game_purchase.name, "Humble order #12345")
        self.assertEqual(session.note, "played after dinner")
        self.assertEqual(created.payload["note"], "played after dinner")
        self.assertEqual(session.started_at, FIRST_SESSION_START)

    def test_a_purchase_event_keeps_no_typed_text_or_real_amount(self):
        _build_dataset()
        owner = get_user_model().objects.get(username="sample-source")
        game = Game.objects.create(library=owner.library, name="Tunic")
        state_catalog_graph(
            game=game,
            library=owner.library,
            editions=[
                EditionState(
                    key="edition-0",
                    is_default=True,
                    releases=(
                        ReleaseState(key="edition-0-release-0", is_default=True),
                    ),
                )
            ],
        )
        entry = record_entry(
            owner.library,
            Release.objects.get(edition__game=game),
            note="from a friend",
            acquisition_note="birthday",
        )
        record_purchase(
            entry,
            name="Deluxe",
            note="gift",
            purchase_note="receipt 4421",
            amount=Decimal("123.45"),
        )

        with TemporaryDirectory() as tempdir:
            output = Path(tempdir) / "out.yaml.gz"
            call_command(
                "anonymize_sample", user="sample-source", seed=3, output=output
            )
            by_model = _by_model(_load_output(output))

        entry_created = _events_of(by_model, "library.libraryentry.created")[-1]
        purchase_created = _events_of(by_model, "library.purchase.created")[-1]
        self.assertEqual(entry_created["fields"]["payload"]["acquisition_note"], "")
        payload = purchase_created["fields"]["payload"]
        self.assertEqual(
            (payload["name"], payload["note"], payload["purchase_note"]), ("", "", "")
        )
        self.assertLessEqual(Decimal(payload["price"]["amount"]), 100)

    def test_an_end_of_access_moves_by_its_device_offset(self):
        _build_dataset()
        laptop = Device.objects.get(name="Anna's laptop")
        end_device_access(
            laptop,
            when=TemporalValue.parse("2021-05-10"),
            note="sold to her brother",
        )
        remove_device(laptop)

        with TemporaryDirectory() as tempdir:
            output = Path(tempdir) / "out.yaml.gz"
            call_command(
                "anonymize_sample", user="sample-source", seed=5, output=output
            )
            by_model = _by_model(_load_output(output))

        (ended,) = _events_of(by_model, "library.device.access_ended")
        (removed,) = _events_of(by_model, "library.device.removed")
        (created,) = [
            event
            for event in _events_of(by_model, "library.device.created")
            if event["fields"]["aggregate_id"] == ended["fields"]["aggregate_id"]
        ]
        moved = _day_of(ended) - date(2021, 5, 10)
        self.assertLessEqual(abs(moved.days), JITTER_DAYS)
        self.assertEqual(ended["fields"]["payload"], {"way": "sold", "note": ""})
        self.assertEqual(_parsed_moment(created["fields"]["recorded_at"]), FIXED_EPOCH)
        self.assertEqual(
            _parsed_moment(ended["fields"]["recorded_at"]).date(), _day_of(ended)
        )
        self.assertGreaterEqual(
            _parsed_moment(removed["fields"]["recorded_at"]),
            _parsed_moment(ended["fields"]["recorded_at"]),
        )

    def test_events_of_one_dispatch_share_one_key(self):
        _build_dataset()

        with TemporaryDirectory() as tempdir:
            output = Path(tempdir) / "out.yaml.gz"
            call_command(
                "anonymize_sample", user="sample-source", seed=5, output=output
            )
            by_model = _by_model(_load_output(output))

        keys_by_type: dict[str, set[str]] = {}
        for event in by_model["games.libraryevent"]:
            fields = event["fields"]
            keys_by_type.setdefault(fields["event_type"], set()).add(
                fields["idempotency_key"]
            )
        #: TrackGame appends both creations per dispatch.
        tracked = keys_by_type["library.playergame.created"]
        self.assertEqual(tracked, keys_by_type["library.playthrough.created"])
        created = [
            event
            for event in by_model["games.libraryevent"]
            if event["fields"]["event_type"] == "library.playergame.created"
        ]
        self.assertEqual(len(tracked), len(created))
        self.assertTrue(all(key.startswith("sample:") for key in tracked))

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
        self.assertEqual(
            [label for label in by_model if label.endswith(".session")], []
        )

        self.assertEqual(len(by_model["games.release"]), 2)
        for created in _events_of(by_model, "library.purchase.created"):
            payload = created["fields"]["payload"]
            self.assertEqual(payload["name"], "")
            self.assertLessEqual(Decimal(payload["price"]["amount"]), 100)

        for event in by_model["games.libraryevent"]:
            payload = event["fields"]["payload"]
            if "note" in payload:
                self.assertEqual(payload["note"], "")
            #: Device events keep names for replay.
            if "name" in payload and not fields_of_device(event):
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

        #: The start event gives the offset.
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

        #: Reference re-captured at the device's key.
        devices = _device_names(by_model)
        device = timed["payload"]["device"]
        self.assertIn(device["id"], devices)
        self.assertEqual(device["label"], devices[device["id"]])

        #: Run key follows the re-minted aggregate.
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

        #: Calendar aggregate: the owner marker.
        (calendar,) = _events_of(by_model, "library.calendar.day_zone_changed")
        self.assertEqual(calendar["fields"]["aggregate_id"], "__target_library__")
        self.assertEqual(calendar["fields"]["payload"]["day_zone"], SOURCE_ZONE)

    def test_output_reloads_via_loaddata(self):
        game_purchase = _build_dataset()
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
            dumped_events = len(_by_model(_load_output(output))["games.libraryevent"])
            with purging_library():
                source_user.delete()
            target = get_user_model().objects.create_user(username="sample-target")
            with patch(
                "games.management.commands.load_sample_data.FIXTURE_PATH",
                output,
            ):
                call_command("load_sample_data", "--user", target.username)

        purchases = Purchase.objects.all()
        self.assertEqual(purchases.count(), 2)
        for purchase in purchases:
            self.assertEqual(purchase.library, target.library)
            self.assertLessEqual(purchase.amount, 100)
            self.assertEqual(purchase.name, "")
        refunded = purchases.get(refunded__isnull=False)
        self.assertEqual(refunded.entry.access_end_way, "refunded")
        self.assertEqual(LibraryEntry.objects.filter(library=target.library).count(), 2)
        self.assertEqual(
            Playthrough.objects.filter(
                player_game__game__library=target.library
            ).count(),
            4,
        )
        events = LibraryEvent.objects.filter(library=target.library)
        self.assertEqual(events.count(), dumped_events)
        record = HistoricalPlaytime.objects.get(library=target.library)
        self.assertEqual(record.runs.get().playthrough.player_game, record.player_game)
        self.assertTrue(all(event.pk.version == 7 for event in events))
        sessions = PlayerSession.objects.filter(library=target.library)
        self.assertEqual(sessions.count(), 3)
        self.assertEqual(sessions.filter(removed_at__isnull=False).count(), 1)
        self.assertTrue(all(session.pk.version == 7 for session in sessions))
        calendar = LibraryCalendar.objects.get(library=target.library)
        self.assertEqual(calendar.pk, target.library.pk)
        self.assertEqual(calendar.day_zone, SOURCE_ZONE)

    def test_scrub_devices_uses_stable_primary_key_ordinals(self):
        game_purchase = _build_dataset()
        create_device(game_purchase.library, "Second source name")
        create_device(game_purchase.library, "First source name")
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

        names = _device_names(by_model)
        self.assertEqual(
            [names[key] for key in sorted(names, key=UUID)],
            ["Device 1", "Device 2", "Device 3"],
        )
        #: Payload reference carries the scrubbed name.
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
        game_purchase = _build_dataset()
        secret = Game.objects.create(
            library=game_purchase.library,
            name="Real Secret Title",
        )
        default_graph(secret, game_purchase.library)
        Edition.objects.filter(game=secret).update(name="Real Secret Title Deluxe")
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
            item["fields"]["name"]
            for item in objects
            if item["model"] in {"games.game", "games.edition"}
        }
        self.assertIn("Placeholder Title", names)
        self.assertIn("Placeholder Title Deluxe", names)
        self.assertNotIn("Real Secret Title", names)
        self.assertNotIn("Real Secret Title Deluxe", names)
        # Rename keeps the row (and its pk), it is not dropped.
        secret.refresh_from_db()
        self.assertEqual(secret.name, "Real Secret Title")  # source DB untouched

    def test_removed_game_is_dumped_with_its_events(self):
        """A removed game owes a date offset."""
        game_purchase = _build_dataset()
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

    @pytest.mark.untracked_games
    def test_exports_only_the_selected_library_with_portable_owner_markers(self):
        _build_dataset()
        outsider = get_user_model().objects.create_user(username="sample-outsider")
        foreign = Game(library=outsider.library, name="FOREIGN SECRET GAME")
        #: Every projection, each holding RESTRICT keys.
        record_purchase(
            record_entry(
                outsider.library, default_graph(foreign, outsider.library).release
            )
        )
        foreign_run = Playthrough.objects.get(player_game__game=foreign)
        _record(
            outsider,
            foreign_run,
            DurationOnlyTiming(day=date(2021, 8, 1), duration=timedelta(hours=1)),
            device=create_device(outsider.library, "Outsider's deck"),
        )
        dispatch(
            RecordHistoricalPlaytime(
                statement=HistoricalPlaytimeStatement(
                    duration=timedelta(hours=2),
                    when=None,
                    provenance=HistoricalPlaytimeProvenance.ESTIMATED,
                    playthrough_ids=(foreign_run.pk,),
                    device_id=None,
                    emulated=False,
                    note="",
                )
            ),
            actor=outsider,
            library=outsider.library,
            idempotency_key="outsider-record",
        )
        tasks.convert_library_prices(
            str(outsider.library.pk), request_run(outsider.library, "EUR")
        )
        self.assertTrue(
            PurchaseValuation.objects.filter(library=outsider.library).exists()
        )
        outsider_streams = set(
            LibraryEvent.objects.filter(library=outsider.library).values_list(
                "stream_id", flat=True
            )
        )

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
        self.assertFalse(
            {str(stream) for stream in outsider_streams}
            & {
                str(item["pk"])
                for item in _by_model(objects)["games.libraryeventstreamhead"]
            }
        )
        for item in objects:
            if item["model"] in {
                "games.device",
                "games.game",
                "games.filterpreset",
                "games.libraryevent",
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

    def test_catalog_rows_mint_at_the_epoch(self):
        _build_dataset()
        #: A removed row an event names.
        named = Release.objects.get(edition__game__name="Game 3")
        remove(named)
        with TemporaryDirectory() as tempdir:
            output = Path(tempdir) / "out.yaml.gz"
            call_command(
                "anonymize_sample", user="sample-source", seed=11, output=output
            )
            by_model = _by_model(_load_output(output))

        for label in ("games.edition", "games.release"):
            for item in by_model[label]:
                self.assertEqual(UUID(str(item["pk"])).version, 7)
                self.assertEqual(_uuid_moment(item["pk"]), FIXED_EPOCH)
        removed = {
            str(item["pk"])
            for item in by_model["games.release"]
            if item["fields"]["removed_at"] is not None
        }
        self.assertEqual(len(removed), 1)
        named_by_entries = {
            event["fields"]["payload"]["release"]["id"]
            for event in _events_of(by_model, "library.libraryentry.created")
        }
        self.assertLessEqual(removed, named_by_entries)
        self.assertNotIn(str(named.pk), named_by_entries)

    def test_catalog_keys_follow_the_new_uuid(self):
        _build_dataset()
        #: An add-on names its main game.
        Game.objects.filter(name="Game 3").update(
            kind=GameKind.DLC, parent=Game.objects.get(name="Game 0")
        )
        with TemporaryDirectory() as tempdir:
            output = Path(tempdir) / "out.yaml.gz"
            call_command(
                "anonymize_sample", user="sample-source", seed=11, output=output
            )
            by_model = _by_model(_load_output(output))

        games = {str(identity(item)) for item in by_model["games.game"]}
        editions = {str(item["pk"]) for item in by_model["games.edition"]}
        parents = [
            item["fields"]["parent"]
            for item in by_model["games.game"]
            if item["fields"]["parent"] is not None
        ]
        self.assertTrue(parents)
        self.assertLessEqual({str(parent) for parent in parents}, games)
        for edition in by_model["games.edition"]:
            self.assertIn(str(edition["fields"]["game"]), games)
        for release in by_model["games.release"]:
            self.assertIn(str(release["fields"]["edition"]), editions)

    def test_two_runs_keep_the_recorded_order(self):
        _build_dataset()
        owner = get_user_model().objects.get(username="sample-source")
        game = Game.objects.get(name="Game 1")
        dispatch(
            CreatePlaythrough(
                game_id=game.pk,
                started=ActStatement(TemporalValue.from_day(date(2020, 1, 1)), ""),
            ),
            actor=owner,
            library=owner.library,
            idempotency_key="second-run",
        )
        runs = tuple(
            Playthrough.objects.filter(player_game__game=game).values_list(
                "pk", flat=True
            )
        )
        dispatch(
            RecordHistoricalPlaytime(
                statement=HistoricalPlaytimeStatement(
                    duration=timedelta(hours=4),
                    when="2021-07-01",
                    provenance=HistoricalPlaytimeProvenance.ESTIMATED,
                    playthrough_ids=runs,
                    device_id=None,
                    emulated=False,
                    note="",
                )
            ),
            actor=owner,
            library=owner.library,
            idempotency_key="record-both",
        )
        for seed in (1, 2, 3):
            with TemporaryDirectory() as tempdir:
                output = Path(tempdir) / "out.yaml.gz"
                call_command(
                    "anonymize_sample", user="sample-source", seed=seed, output=output
                )
                by_model = _by_model(_load_output(output))
            [both] = [
                event["fields"]["payload"]["playthroughs"]
                for event in _events_of(by_model, "library.historicalplaytime.created")
                if len(event["fields"]["payload"]["playthroughs"]) == 2
            ]
            self.assertEqual(both, sorted_runs(both))

    def test_a_reference_no_event_creates_is_named(self):
        _build_dataset()
        event = LibraryEvent.objects.filter(
            event_type="library.purchase.created"
        ).first()
        stray = uuid.uuid7()
        LibraryEventReference.objects.create(
            library=event.library,
            event=event,
            kind="libraryentry",
            payload_key="stray",
            referenced_id=stray,
        )

        with (
            TemporaryDirectory() as tempdir,
            self.assertRaisesMessage(CommandError, f"libraryentry {stray}"),
        ):
            call_command(
                "anonymize_sample",
                user="sample-source",
                seed=1,
                output=Path(tempdir) / "out.yaml.gz",
            )

    def test_every_reference_follows_the_new_uuid(self):
        by_model = self._dump()

        rows_by_kind = {
            "catalog.game": {str(identity(item)) for item in by_model["games.game"]},
            "catalog.platform": {
                str(item["pk"]) for item in by_model["games.platform"]
            },
            "catalog.release": {str(item["pk"]) for item in by_model["games.release"]},
            "device": set(_device_names(by_model)),
            "libraryentry": {
                event["fields"]["aggregate_id"]
                for event in _events_of(by_model, "library.libraryentry.created")
            },
        }
        #: Every kind a payload may name.
        self.assertEqual(
            set(rows_by_kind),
            {kind.name for kind in DEFAULT_EVENT_TYPES.reference_kinds},
        )
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
        """Envelope day and payload start agree."""
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

    def test_the_default_device_key_follows_the_new_uuid(self):
        """A key, not a relation: remapped."""
        _build_dataset()
        library = get_user_model().objects.get(username="sample-source").library
        preferences = library.preferences
        preferences.set_default_device(Device.objects.get(library=library))

        with transaction.atomic():
            AnonymizeCommand()._reassign_uuids()

        preferences.refresh_from_db()
        self.assertTrue(
            Device.objects.filter(pk=preferences.default_device_id).exists(),
            "default_device still names a primary key no Device carries",
        )
