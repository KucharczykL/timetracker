from __future__ import annotations

import os
import subprocess
from datetime import UTC, datetime
from gzip import open as gzip_open
from io import StringIO
from pathlib import Path
from unittest.mock import Mock
from uuid import UUID, uuid7

import pytest
import yaml
from devices import create_device
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.db.models import F
from django.utils import timezone
from session_rows import timed_row, tracked_run

from common.platform_icons import PLATFORM_ICONS
from games.management.commands.load_sample_data import loaded_tables
from games.models import (
    Device,
    ExchangeRate,
    Game,
    LibraryCalendar,
    LibraryEvent,
    Platform,
    PlayerGame,
    PlayerSession,
    Playthrough,
    PlaythroughKind,
    Purchase,
    PurchaseConversionState,
    Release,
    UserLibraryPreferences,
)


@pytest.fixture
def owner(db):
    return get_user_model().objects.create_user(username="command-owner")


@pytest.fixture
def outsider(db):
    return get_user_model().objects.create_user(username="command-outsider")


def _owned_graph(owner):
    platform, _ = Platform.objects.get_or_create(
        library=None,
        name="Steam",
        group="PC",
    )
    device = create_device(library=owner.library, name="Owner device")
    game = Game.objects.create(
        library=owner.library,
        name="Owner game",
        platform=platform,
    )
    started_at = datetime(2025, 1, 1, tzinfo=UTC)
    timed_row(tracked_run(owner.library, game), started_at, None, device=device)
    return platform, device, game


@pytest.mark.django_db
def test_audit_requires_exactly_one_explicit_scope(owner):
    with pytest.raises(CommandError):
        call_command("audit_library_ownership")
    with pytest.raises(CommandError):
        call_command(
            "audit_library_ownership",
            "--user",
            owner.username,
            "--library",
            str(owner.library.pk),
        )
    with pytest.raises(CommandError):
        call_command(
            "audit_library_ownership",
            "--user",
            owner.username,
            "--all-libraries",
        )
    with pytest.raises(CommandError):
        call_command(
            "audit_library_ownership",
            "--library",
            str(owner.library.pk),
            "--all-libraries",
        )


@pytest.mark.django_db
def test_audit_reports_direct_derived_cross_link_and_preference_sections(owner):
    _owned_graph(owner)
    output = StringIO()

    call_command(
        "audit_library_ownership",
        "--library",
        str(owner.library.pk),
        stdout=output,
    )

    report = output.getvalue()
    assert "Direct owners" in report
    assert "games: 1" in report
    assert "Derived relationships" in report
    assert "sessions: 1" in report
    assert "Cross-library links: 0" in report
    assert "Preference structure: valid" in report


@pytest.mark.django_db
def test_audit_exits_nonzero_and_names_an_injected_cross_library_link(owner, outsider):
    _, _, game = _owned_graph(owner)
    foreign_device = create_device(
        library=outsider.library,
        name="Foreign device",
    )
    session = PlayerSession.objects.get(playthrough__player_game__game=game)
    PlayerSession.objects.filter(pk=session.pk).update(device=foreign_device)
    output = StringIO()

    with pytest.raises(CommandError, match="violation"):
        call_command(
            "audit_library_ownership",
            "--user",
            owner.username,
            stdout=output,
        )

    assert (
        f"PlayerSession.device: {session.pk} names Device {foreign_device.pk}"
        in output.getvalue()
    )


@pytest.mark.django_db
def test_purge_user_library_is_a_warning_rich_dry_run_by_default(owner):
    _owned_graph(owner)
    output = StringIO()

    call_command("purge_user_library", "--user", owner.username, stdout=output)

    assert get_user_model().objects.filter(pk=owner.pk).exists()
    assert Game.objects.filter(library=owner.library).exists()
    report = output.getvalue()
    assert "WARNING" in report
    assert "DRY RUN" in report
    assert "games.Game: 1" in report


@pytest.mark.django_db
def test_purge_user_library_rejects_a_mismatched_confirmation(owner):
    _owned_graph(owner)

    with pytest.raises(CommandError, match="must exactly match"):
        call_command(
            "purge_user_library",
            "--user",
            owner.username,
            "--confirm",
            "someone-else",
        )

    assert get_user_model().objects.filter(pk=owner.pk).exists()


@pytest.mark.django_db
def test_purge_user_library_cascades_private_data_but_keeps_shared_platform(owner):
    platform, _, game = _owned_graph(owner)
    output = StringIO()

    call_command(
        "purge_user_library",
        "--user",
        owner.username,
        "--confirm",
        owner.username,
        stdout=output,
    )

    assert not get_user_model().objects.filter(pk=owner.pk).exists()
    assert not Game.objects.filter(pk=game.pk).exists()
    assert Platform.objects.filter(pk=platform.pk, library__isnull=True).exists()
    assert "PURGED" in output.getvalue()


@pytest.mark.django_db
def test_load_sample_data_rejects_a_missing_explicit_user():
    with pytest.raises(CommandError, match="does not exist"):
        call_command("load_sample_data", "--user", "missing-user")


@pytest.mark.django_db(transaction=True)
def test_committed_sample_load_owns_private_rows_and_reuses_shared_platform(owner):
    dummy = Platform.objects.create(name="Pre-existing platform", group="Other")
    steam = Platform.objects.create(name="Steam", group="PC")

    call_command("load_sample_data", "--user", owner.username, verbosity=0)

    assert Platform.objects.filter(pk=dummy.pk).exists()
    assert Platform.objects.filter(name="Steam", group="PC").count() == 1
    assert Platform.objects.get(name="Steam", group="PC").pk == steam.pk
    # The fixture references platforms by uuid, and a reused row's uuid is not
    # the fixture's, so the loaded rows must have been remapped onto this exact
    # platform rather than carrying the fixture's identity through.
    assert Game.objects.filter(platform=steam).exists()
    assert Release.objects.filter(platform=steam).exists()
    assert Game.objects.filter(library=owner.library).exists()
    assert not Game.objects.exclude(library=owner.library).exists()
    assert Device.objects.filter(library=owner.library).exists()
    assert not Device.objects.exclude(library=owner.library).exists()
    assert Purchase.objects.filter(library=owner.library).exists()
    assert not Purchase.objects.exclude(library=owner.library).exists()
    assert PlayerSession.objects.filter(library=owner.library).exists()
    assert not PlayerSession.objects.exclude(library=owner.library).exists()
    assert LibraryCalendar.objects.filter(library=owner.library).exists()
    #: The fixture carries no valuation.
    state = PurchaseConversionState.objects.get(library=owner.library)
    assert state.requested_version > state.published_version


@pytest.mark.django_db(transaction=True)
def test_committed_sample_load_leaves_statistics_that_know_the_rows_exist(owner):
    """The queued conversion task plans on these."""
    call_command("load_sample_data", "--user", owner.username, verbosity=0)

    estimated = {}
    counted = {}
    with connection.cursor() as cursor:
        for model in loaded_tables():
            table = model._meta.db_table
            cursor.execute("SELECT reltuples FROM pg_class WHERE relname = %s", [table])
            estimated[table] = cursor.fetchone()[0]
            counted[table] = model._base_manager.count()
    assert estimated == counted


@pytest.mark.django_db(transaction=True)
def test_committed_sample_load_states_listed_icons(owner):
    output = StringIO()
    call_command("load_sample_data", "--user", owner.username, stdout=output)

    assert "named an unlisted icon" not in output.getvalue()
    icons = set(Platform.objects.values_list("icon", flat=True))
    assert icons <= set(PLATFORM_ICONS)
    assert "nintendo" in icons


@pytest.mark.django_db
def test_sample_load_canonicalises_an_unlisted_icon(owner, monkeypatch, tmp_path):
    from games.management.commands import load_sample_data

    fixture = tmp_path / "sample.yaml"
    fixture.write_text(
        """- model: games.platform
  pk: 00000000-0000-7000-8000-000000000301
  fields:
    library: __target_library__
    name: PlayStation
    group: Console
    icon: ps1
    created_at: 2025-01-01 00:00:00+00:00
    removed_at: null
"""
    )
    monkeypatch.setattr(load_sample_data, "FIXTURE_PATH", fixture)
    output = StringIO()

    call_command("load_sample_data", "--user", owner.username, stdout=output)

    assert "1 sample platform(s) named an unlisted icon" in output.getvalue()
    platform = Platform.objects.get(name="PlayStation", library=owner.library)
    assert platform.icon == "playstation"


def test_committed_sample_stores_promoted_uuid_identities_as_primary_keys():
    from games.management.commands.load_sample_data import FIXTURE_PATH

    with gzip_open(FIXTURE_PATH, "rt") as fixture:
        records = yaml.safe_load(fixture)

    promoted = {
        model: [record for record in records if record["model"] == model]
        for model in ("games.filterpreset", "games.edition", "games.release")
    }
    #: A device travels as its events, never as a row.
    assert not any(record["model"] == "games.device" for record in records)
    assert promoted["games.release"]
    for model_records in promoted.values():
        assert all(isinstance(record["pk"], str) for record in model_records)
        assert all(UUID(record["pk"]).version == 7 for record in model_records)
        assert all("uuid" not in record["fields"] for record in model_records)

    device_ids = {
        record["fields"]["aggregate_id"]
        for record in records
        if record["model"] == "games.libraryevent"
        and record["fields"]["event_type"] == "library.device.created"
    }
    assert device_ids
    assert all(UUID(device_id).version == 7 for device_id in device_ids)
    session_devices = {
        record["fields"]["payload"]["device"]["id"]
        for record in records
        if record["model"] == "games.libraryevent"
        and record["fields"]["event_type"] == "library.playersession.created"
        and record["fields"]["payload"]["device"] is not None
    }
    assert session_devices
    assert session_devices <= device_ids


@pytest.mark.django_db
def test_sample_load_rejects_a_private_row_without_portable_owner_marker(
    owner, monkeypatch, tmp_path
):
    from games.management.commands import load_sample_data

    fixture = tmp_path / "sample.yaml"
    game_id = "00000000-0000-7000-8000-000000000202"
    fixture.write_text(
        f"""- model: games.game
  pk: {game_id}
  fields:
    library: null
    name: Unmarked
    platform: null
    created_at: 2025-01-01 00:00:00+00:00
    updated_at: 2025-01-01 00:00:00+00:00
"""
    )
    monkeypatch.setattr(load_sample_data, "FIXTURE_PATH", fixture)

    with pytest.raises(CommandError, match="portable owner marker"):
        call_command("load_sample_data", "--user", owner.username, verbosity=0)

    assert not Game.objects.filter(pk=game_id).exists()


@pytest.mark.django_db
def test_sample_load_refuses_a_device_stated_as_a_row(owner, monkeypatch, tmp_path):
    """A device row vanishes at the rebuild."""
    from games.management.commands import load_sample_data

    fixture = tmp_path / "sample.yaml"
    device_id = "00000000-0000-7000-8000-000000000203"
    fixture.write_text(
        f"""- model: games.device
  pk: {device_id}
  fields:
    library: __target_library__
    name: Deck
    type: PC
    created_at: 2025-01-01 00:00:00+00:00
"""
    )
    monkeypatch.setattr(load_sample_data, "FIXTURE_PATH", fixture)

    with pytest.raises(CommandError, match="games.device"):
        call_command("load_sample_data", "--user", owner.username, verbosity=0)

    assert not Device.objects.filter(library=owner.library).exists()
    assert not LibraryEvent.objects.filter(
        library=owner.library, event_type__startswith="library.device."
    ).exists()


@pytest.mark.django_db
def test_sample_load_refuses_a_reference_naming_a_device_no_event_created(
    owner, monkeypatch, tmp_path
):
    """A referenced device needs its creation event."""
    from games.management.commands import load_sample_data

    fixture = tmp_path / "sample.yaml"
    device_id = "00000000-0000-7000-8000-000000000204"
    stream_id = "00000000-0000-7000-8000-000000000205"
    event_id = "00000000-0000-7000-8000-000000000206"
    fixture.write_text(
        yaml.safe_dump(
            [
                {
                    "model": "games.libraryeventstreamhead",
                    "pk": stream_id,
                    "fields": {"library": "__target_library__", "current_sequence": 1},
                },
                {
                    #: The named device has no creation event.
                    "model": "games.libraryevent",
                    "pk": event_id,
                    "fields": {
                        "library": "__target_library__",
                        "stream": stream_id,
                        "aggregate_id": "00000000-0000-7000-8000-000000000207",
                        "event_type": "library.device.created",
                        "payload": {"name": "Deck", "type": "PC"},
                        "payload_schema_version": 1,
                        "sequence": 1,
                        "recorded_at": "2025-01-01 00:00:00+00:00",
                        "idempotency_key": "sample:1",
                        "correlation_id": "00000000-0000-7000-8000-000000000208",
                        "causation_id": None,
                        "actor": None,
                        "effective_time": None,
                        "source_metadata": {},
                    },
                },
                {
                    "model": "games.libraryeventreference",
                    "pk": "00000000-0000-7000-8000-000000000209",
                    "fields": {
                        "library": "__target_library__",
                        "event": event_id,
                        "kind": "device",
                        "payload_key": "device",
                        "referenced_id": device_id,
                    },
                },
            ]
        )
    )
    monkeypatch.setattr(load_sample_data, "FIXTURE_PATH", fixture)

    with pytest.raises(CommandError, match=rf"Device '{device_id}'"):
        call_command("load_sample_data", "--user", owner.username, verbosity=0)


# Session.game and both platform foreign keys reference their promoted target's
# UUIDv7 primary key; these are well-formed UUIDs that no fixture record carries.
ABSENT_GAME_UUID = "00000000-0000-7000-8000-000000000000"
ABSENT_DEVICE_UUID = "00000000-0000-7000-8000-000000000001"
PRESENT_GAME_UUID = "00000000-0000-7000-8000-000000000002"
PRESENT_STREAM_UUID = "00000000-0000-7000-8000-000000000003"
PRESENT_EVENT_UUID = "00000000-0000-7000-8000-000000000004"
ABSENT_PLATFORM_UUID = "00000000-0000-7000-8000-000000000001"


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("model", "fields", "target_model"),
    [
        (
            "games.game",
            {"library": "__target_library__", "parent": ABSENT_GAME_UUID},
            "Game",
        ),
        (
            "games.game",
            {"library": "__target_library__", "platform": ABSENT_PLATFORM_UUID},
            "Platform",
        ),
        ("games.edition", {"game": ABSENT_GAME_UUID}, "Game"),
        ("games.release", {"edition": ABSENT_GAME_UUID}, "Edition"),
    ],
)
def test_sample_load_rejects_relationships_outside_the_fixture_graph(
    owner, monkeypatch, tmp_path, model, fields, target_model
):
    from games.management.commands import load_sample_data

    fixture = tmp_path / "sample.yaml"
    fixture.write_text(yaml.safe_dump([{"model": model, "pk": 301, "fields": fields}]))
    monkeypatch.setattr(load_sample_data, "FIXTURE_PATH", fixture)

    with pytest.raises(
        CommandError, match=rf"references {target_model} .*not included"
    ):
        call_command("load_sample_data", "--user", owner.username, verbosity=0)


@pytest.mark.django_db
def test_sample_load_rejects_a_release_platform_outside_the_fixture_graph(
    owner, monkeypatch, tmp_path
):
    from games.management.commands import load_sample_data

    fixture = tmp_path / "sample.yaml"
    fixture.write_text(
        yaml.safe_dump(
            [
                {
                    "model": "games.game",
                    "pk": PRESENT_GAME_UUID,
                    "fields": {"library": "__target_library__", "name": "Held"},
                },
                {
                    "model": "games.edition",
                    "pk": 302,
                    "fields": {"game": PRESENT_GAME_UUID},
                },
                {
                    "model": "games.release",
                    "pk": 303,
                    "fields": {"edition": 302, "platform": ABSENT_PLATFORM_UUID},
                },
            ]
        )
    )
    monkeypatch.setattr(load_sample_data, "FIXTURE_PATH", fixture)

    with pytest.raises(CommandError, match=r"references Platform .*not included"):
        call_command("load_sample_data", "--user", owner.username, verbosity=0)


@pytest.mark.django_db
def test_sample_load_rejects_a_session_device_outside_the_fixture_graph(
    owner, monkeypatch, tmp_path
):
    from games.management.commands import load_sample_data

    fixture = tmp_path / "sample.yaml"
    fixture.write_text(
        yaml.safe_dump(
            [
                {
                    "model": "games.libraryeventstreamhead",
                    "pk": PRESENT_STREAM_UUID,
                    "fields": {"library": "__target_library__", "current_sequence": 1},
                },
                {
                    "model": "games.libraryevent",
                    "pk": PRESENT_EVENT_UUID,
                    "fields": {
                        "library": "__target_library__",
                        "stream": PRESENT_STREAM_UUID,
                        "sequence": 1,
                        "event_type": "library.playersession.created",
                        "aggregate_id": PRESENT_EVENT_UUID,
                        "payload": {
                            "playthrough": PRESENT_GAME_UUID,
                            "device": {
                                "kind": "device",
                                "id": ABSENT_DEVICE_UUID,
                                "label": "Absent",
                                "detail": "",
                            },
                            "release": None,
                            "timing": {
                                "mode": "duration_only",
                                "stated_day": "2026-01-01",
                                "duration_seconds": 60,
                            },
                            "note": "",
                            "emulated": False,
                        },
                    },
                },
            ]
        )
    )
    monkeypatch.setattr(load_sample_data, "FIXTURE_PATH", fixture)

    with pytest.raises(
        CommandError, match=rf"references Device .{ABSENT_DEVICE_UUID}.*not included"
    ):
        call_command("load_sample_data", "--user", owner.username, verbosity=0)


@pytest.mark.django_db
def test_sample_load_rejects_duplicate_fixture_primary_keys(
    owner, monkeypatch, tmp_path
):
    from games.management.commands import load_sample_data

    fixture = tmp_path / "sample.yaml"
    duplicate_game_id = "00000000-0000-7000-8000-000000000401"
    fixture.write_text(
        yaml.safe_dump(
            [
                {
                    "model": "games.game",
                    "pk": duplicate_game_id,
                    "fields": {
                        "library": "__target_library__",
                        "name": "First",
                    },
                },
                {
                    "model": "games.game",
                    "pk": duplicate_game_id,
                    "fields": {
                        "library": "__target_library__",
                        "name": "Second",
                    },
                },
            ]
        )
    )
    monkeypatch.setattr(load_sample_data, "FIXTURE_PATH", fixture)

    with pytest.raises(
        CommandError,
        match=rf"duplicate games.game primary key {duplicate_game_id}",
    ):
        call_command("load_sample_data", "--user", owner.username, verbosity=0)

    assert not Game.objects.filter(pk=duplicate_game_id).exists()


@pytest.mark.django_db(transaction=True)
def test_sample_load_force_inserts_and_rolls_back_a_late_primary_key_collision(
    owner, monkeypatch, tmp_path
):
    from games.management.commands import load_sample_data

    fixture = tmp_path / "sample.yaml"
    colliding_game_id = "00000000-0000-7000-8000-000000000503"
    fixture.write_text(
        yaml.safe_dump(
            [
                {
                    "model": "games.platform",
                    "pk": 501,
                    "fields": {
                        "library": None,
                        "name": "Rollback platform",
                        "group": "PC",
                    },
                },
                {
                    "model": "games.exchangerate",
                    "pk": 502,
                    "fields": {
                        "currency_from": "USD",
                        "currency_to": "EUR",
                        "year": 2099,
                        "rate": 0.5,
                    },
                },
                {
                    "model": "games.game",
                    "pk": colliding_game_id,
                    "fields": {
                        "library": "__target_library__",
                        "platform": None,
                        "name": "Fixture game",
                        "created_at": "2025-01-01 00:00:00+00:00",
                        "updated_at": "2025-01-01 00:00:00+00:00",
                    },
                },
            ]
        )
    )
    monkeypatch.setattr(load_sample_data, "FIXTURE_PATH", fixture)
    original_check = load_sample_data.Command._reject_primary_key_collisions

    def insert_after_check(records):
        original_check(records)
        Game.objects.create(
            pk=colliding_game_id, library=owner.library, name="Concurrent game"
        )

    monkeypatch.setattr(
        load_sample_data.Command,
        "_reject_primary_key_collisions",
        staticmethod(insert_after_check),
    )

    with pytest.raises(CommandError, match="could not be loaded") as error:
        call_command("load_sample_data", "--user", owner.username, verbosity=0)

    assert "duplicate key" in str(error.value).lower()
    assert not Platform.objects.filter(name="Rollback platform").exists()
    assert not Game.objects.filter(pk=colliding_game_id).exists()
    assert not ExchangeRate.objects.filter(
        currency_from="USD",
        currency_to="EUR",
        year=2099,
    ).exists()


@pytest.mark.django_db
def test_scoped_audit_reports_incoming_cross_library_links(owner, outsider):
    owner_platform = Platform.objects.create(
        library=owner.library,
        name="Owner private platform",
        group="Private",
    )
    _, owner_device, _ = _owned_graph(owner)
    _, _, outsider_game = _owned_graph(outsider)
    outsider_session = PlayerSession.objects.get(
        playthrough__player_game__game=outsider_game
    )

    Game.objects.filter(pk=outsider_game.pk).update(platform=owner_platform)
    PlayerSession.objects.filter(pk=outsider_session.pk).update(device=owner_device)
    UserLibraryPreferences.objects.filter(library=outsider.library).update(
        default_device_id=owner_device.pk
    )
    Playthrough.objects.create(
        id=uuid7(),
        library=owner.library,
        player_game=PlayerGame.objects.get(game=outsider_game),
        kind=PlaythroughKind.ORDINARY,
        created_at=timezone.now(),
    )
    #: PlayerGame.game, the second registered reference: the owner's
    #: tracking row moved onto a game the outsider's library holds.
    tracked_across = Game.objects.create(
        library=outsider.library, name="Outsider tracked by owner"
    )
    PlayerGame.objects.filter(game=tracked_across).update(library=owner.library)
    output = StringIO()

    with pytest.raises(CommandError, match="violation"):
        call_command(
            "audit_library_ownership",
            "--user",
            owner.username,
            stdout=output,
        )

    report = output.getvalue()
    for relation in (
        "Game.platform",
        "PlayerSession.device",
        "UserLibraryPreferences.default_device",
        "Playthrough.player_game",
        "PlayerGame.game",
    ):
        assert relation in report
    assert (
        f"PlayerSession.device: {outsider_session.pk} names Device {owner_device.pk}"
        in report
    )
    assert "Session.device: session" not in report
    assert (
        "UserLibraryPreferences.default_device: "
        f"library {outsider.library.pk}, device {owner_device.pk}" in report
    )


@pytest.mark.django_db
def test_a_playthrough_in_another_library_is_reported(owner, outsider):
    """A cross-library row blocks the named row's purge."""
    game = Game.objects.create(library=owner.library, name="Outer Wilds")
    tracked = PlayerGame.objects.get(game=game)
    run = Playthrough.objects.create(
        id=uuid7(),
        #: The offence: not the tracked game's library.
        library=outsider.library,
        player_game=tracked,
        kind=PlaythroughKind.ORDINARY,
        created_at=timezone.now(),
    )
    output = StringIO()

    with pytest.raises(CommandError, match="violation"):
        call_command(
            "audit_library_ownership",
            "--user",
            owner.username,
            stdout=output,
        )

    assert (
        f"Playthrough.player_game: {run.pk} names PlayerGame {tracked.pk}"
        in output.getvalue()
    )


@pytest.mark.django_db
def test_a_tracked_game_from_another_library_is_reported(owner, outsider):
    """`PlayerGame.game` is RESTRICT: it blocks the other library's purge."""
    game = Game.objects.create(library=outsider.library, name="Tunic")
    tracked = PlayerGame.objects.get(game=game)
    PlayerGame.objects.filter(pk=tracked.pk).update(library=owner.library)
    output = StringIO()

    with pytest.raises(CommandError, match="violation"):
        call_command(
            "audit_library_ownership",
            "--user",
            owner.username,
            stdout=output,
        )

    assert f"PlayerGame.game: {tracked.pk} names Game {game.pk}" in output.getvalue()


@pytest.mark.django_db
def test_a_tracked_game_with_no_library_is_no_violation(owner):
    """A shared catalog row crosses no boundary."""
    shared = Game.objects.create(name="Outer Wilds")
    PlayerGame.objects.create(
        id=uuid7(),
        library=owner.library,
        game=shared,
        tracked_at=timezone.now(),
    )
    output = StringIO()

    call_command(
        "audit_library_ownership",
        "--user",
        owner.username,
        stdout=output,
    )

    assert shared.library_id is None
    assert "Cross-library links: 0" in output.getvalue()


@pytest.mark.django_db
def test_all_libraries_audit_reports_a_user_missing_their_library(owner):
    owner.library.delete()
    output = StringIO()

    with pytest.raises(CommandError, match="violation"):
        call_command("audit_library_ownership", "--all-libraries", stdout=output)

    assert f"UserLibrary missing for user {owner.pk}" in output.getvalue()


@pytest.mark.parametrize("target", ["loadsample", "anonymize-sample"])
def test_make_sample_targets_do_not_accept_an_inherited_user(target):
    environment = {**os.environ, "USER": "inherited-os-user"}

    result = subprocess.run(
        ["make", "-n", target],
        cwd=Path(settings.BASE_DIR),
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert f"USER is required: make {target} USER=<username>" in (
        result.stdout + result.stderr
    )

    explicit = subprocess.run(
        ["make", "-n", target, "USER=explicit-app-user"],
        cwd=Path(settings.BASE_DIR),
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert explicit.returncode == 0
    assert '--user "explicit-app-user"' in explicit.stdout


def test_the_committed_sample_fixture_names_no_model_the_app_dropped():
    """A dropped model fails the load."""
    from games.management.commands.load_sample_data import FIXTURE_PATH

    with gzip_open(FIXTURE_PATH, "rt") as fixture:
        records = yaml.safe_load(fixture)

    assert not {"games.playevent", "games.gamestatuschange", "games.session"} & {
        record["model"] for record in records
    }


@pytest.mark.django_db(transaction=True)
def test_sample_load_requests_a_run_after_the_replay(owner, monkeypatch):
    from games.management.commands import load_sample_data

    projected_at_request: list[bool] = []
    real = load_sample_data._request_conversion_for_locked_state

    def record(state, currency):
        projected_at_request.append(
            PlayerSession.objects.filter(library=owner.library).exists()
        )
        return real(state, currency)

    monkeypatch.setattr(
        load_sample_data, "_request_conversion_for_locked_state", record
    )
    PurchaseConversionState.objects.filter(library=owner.library).update(
        requested_version=F("published_version") + 1
    )

    call_command("load_sample_data", "--user", owner.username, verbosity=0)

    assert projected_at_request == [True]


@pytest.mark.django_db(transaction=True)
def test_sample_load_requests_a_run_for_stale_purchases_alone(owner, monkeypatch):
    from games.management.commands import load_sample_data

    stale = Mock()
    stale.exists.return_value = True
    monkeypatch.setattr(load_sample_data, "stale_purchases", lambda library: stale)
    before = PurchaseConversionState.objects.get(library=owner.library)

    call_command("load_sample_data", "--user", owner.username, verbosity=0)

    after = PurchaseConversionState.objects.get(library=owner.library)
    assert after.requested_version == before.requested_version + 1


def test_the_loader_takes_every_dumped_model():
    from games.management.commands.anonymize_sample import DUMP_LABELS
    from games.management.commands.load_sample_data import LOADABLE_MODELS

    rebuilt = {"games.platform", "games.exchangerate"}
    assert set(DUMP_LABELS) - rebuilt <= set(LOADABLE_MODELS)
