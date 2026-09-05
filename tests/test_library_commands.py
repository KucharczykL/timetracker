from __future__ import annotations

import os
import subprocess
from datetime import UTC, date, datetime
from gzip import open as gzip_open
from io import StringIO
from pathlib import Path
from uuid import UUID, uuid7

import pytest
import yaml
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from games.models import (
    Device,
    ExchangeRate,
    Game,
    Platform,
    PlayerGame,
    PlayEvent,
    Playthrough,
    PlaythroughKind,
    Purchase,
    PurchaseConversionState,
    Session,
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
    device = Device.objects.create(library=owner.library, name="Owner device")
    game = Game.objects.create(
        library=owner.library,
        name="Owner game",
        platform=platform,
    )
    purchase = Purchase.objects.create(
        library=owner.library,
        price=10,
        price_currency="CZK",
        date_purchased=date(2025, 1, 1),
        platform=platform,
    )
    purchase.games.add(game)
    Session.objects.create(
        game=game,
        device=device,
        timestamp_start=datetime(2025, 1, 1, tzinfo=UTC),
    )
    PlayEvent.objects.create(game=game, started=date(2025, 1, 1))
    return platform, device, game, purchase


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
    _, _, game, _ = _owned_graph(owner)
    foreign_device = Device.objects.create(
        library=outsider.library,
        name="Foreign device",
    )
    session = game.sessions.get()
    Session.objects.filter(pk=session.pk).update(device=foreign_device)
    output = StringIO()

    with pytest.raises(CommandError, match="violation"):
        call_command(
            "audit_library_ownership",
            "--user",
            owner.username,
            stdout=output,
        )

    assert "Session.device" in output.getvalue()


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
    platform, _, game, _ = _owned_graph(owner)
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
    assert Purchase.objects.filter(platform=steam).exists()
    assert Game.objects.filter(library=owner.library).exists()
    assert not Game.objects.exclude(library=owner.library).exists()
    assert Device.objects.filter(library=owner.library).exists()
    assert not Device.objects.exclude(library=owner.library).exists()
    assert Purchase.objects.filter(library=owner.library).exists()
    assert not Purchase.objects.exclude(library=owner.library).exists()
    assert Session.objects.filter(game__library=owner.library).exists()
    assert not Session.objects.exclude(game__library=owner.library).exists()
    assert PlayEvent.objects.filter(game__library=owner.library).exists()
    assert not PlayEvent.objects.exclude(game__library=owner.library).exists()


def test_committed_sample_stores_promoted_uuid_identities_as_primary_keys():
    from games.management.commands.load_sample_data import FIXTURE_PATH

    with gzip_open(FIXTURE_PATH, "rt") as fixture:
        records = yaml.safe_load(fixture)

    promoted = {
        model: [record for record in records if record["model"] == model]
        for model in ("games.device", "games.filterpreset", "games.purchase")
    }
    assert promoted["games.device"]
    assert promoted["games.purchase"]
    for model_records in promoted.values():
        assert all(isinstance(record["pk"], str) for record in model_records)
        assert all(UUID(record["pk"]).version == 7 for record in model_records)
        assert all("uuid" not in record["fields"] for record in model_records)

    device_ids = {record["pk"] for record in promoted["games.device"]}
    session_devices = {
        record["fields"]["device"]
        for record in records
        if record["model"] == "games.session" and record["fields"]["device"] is not None
    }
    assert session_devices
    assert session_devices <= device_ids


@pytest.mark.django_db
def test_sample_load_requests_conversion_when_preserved_cache_currency_differs(
    owner, monkeypatch, tmp_path
):
    from games import conversion
    from games.management.commands import load_sample_data

    queued = []
    monkeypatch.setattr(conversion, "async_task", lambda *args: queued.append(args))
    fixture = tmp_path / "sample.yaml"
    purchase_uuid = "00000000-0000-7000-8000-000000000101"
    fixture.write_text(
        f"""- model: games.purchase
  pk: {purchase_uuid}
  fields:
    library: __target_library__
    games: []
    platform: null
    date_purchased: 2025-01-01
    date_refunded: null
    infinite: false
    price: 10
    price_currency: USD
    converted_price: 230
    converted_currency: CZK
    needs_price_update: false
    num_purchases: 0
    ownership_type: di
    type: game
    name: Sample
    related_game: null
    created_at: 2025-01-01 00:00:00+00:00
    updated_at: 2025-01-01 00:00:00+00:00
"""
    )
    state = owner.library.purchase_conversion_state
    state.requested_currency = "EUR"
    state.published_currency = "EUR"
    state.save(update_fields=["requested_currency", "published_currency"])
    monkeypatch.setattr(load_sample_data, "FIXTURE_PATH", fixture)

    call_command("load_sample_data", "--user", owner.username, verbosity=0)

    state.refresh_from_db()
    purchase = Purchase.objects.get(pk=purchase_uuid)
    assert (purchase.converted_price, purchase.converted_currency) == (230, "CZK")
    assert (
        state.requested_version,
        state.requested_currency,
        state.status,
    ) == (1, "EUR", PurchaseConversionState.Status.PENDING)


@pytest.mark.django_db
def test_sample_load_rejects_a_private_row_without_portable_owner_marker(
    owner, monkeypatch, tmp_path
):
    from games.management.commands import load_sample_data

    fixture = tmp_path / "sample.yaml"
    device_id = "00000000-0000-7000-8000-000000000202"
    fixture.write_text(
        f"""- model: games.device
  pk: {device_id}
  fields:
    library: null
    name: Unowned device
    type: PC
    created_at: 2025-01-01 00:00:00+00:00
"""
    )
    monkeypatch.setattr(load_sample_data, "FIXTURE_PATH", fixture)

    with pytest.raises(CommandError, match="portable owner marker"):
        call_command("load_sample_data", "--user", owner.username, verbosity=0)

    assert not Device.objects.filter(pk=device_id).exists()


# PlayEvent.game, GameStatusChange.game, and both platform foreign keys reference
# their promoted target's UUIDv7 primary key; these are well-formed UUIDs that
# no fixture record carries.
ABSENT_GAME_UUID = "00000000-0000-7000-8000-000000000000"
ABSENT_DEVICE_UUID = "00000000-0000-7000-8000-000000000001"
PRESENT_GAME_UUID = "00000000-0000-7000-8000-000000000002"
ABSENT_PLATFORM_UUID = "00000000-0000-7000-8000-000000000001"


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("model", "fields", "target_model"),
    [
        ("games.session", {"game": ABSENT_GAME_UUID}, "Game"),
        ("games.playevent", {"game": ABSENT_GAME_UUID}, "Game"),
        ("games.gamestatuschange", {"game": ABSENT_GAME_UUID}, "Game"),
        (
            "games.purchase",
            {"library": "__target_library__", "games": [999]},
            "Game",
        ),
        (
            "games.purchase",
            {"library": "__target_library__", "related_game": ABSENT_GAME_UUID},
            "Game",
        ),
        (
            "games.game",
            {"library": "__target_library__", "platform": ABSENT_PLATFORM_UUID},
            "Platform",
        ),
        (
            "games.purchase",
            {"library": "__target_library__", "platform": ABSENT_PLATFORM_UUID},
            "Platform",
        ),
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
def test_sample_load_rejects_a_session_device_outside_the_fixture_graph(
    owner, monkeypatch, tmp_path
):
    from games.management.commands import load_sample_data

    fixture = tmp_path / "sample.yaml"
    fixture.write_text(
        yaml.safe_dump(
            [
                {
                    "model": "games.game",
                    # Session.game names its target's primary key, which for Game
                    # is the UUID - so the included game must carry it here for
                    # this fixture to fail on the *device* it is testing.
                    "pk": PRESENT_GAME_UUID,
                    "fields": {
                        "library": "__target_library__",
                        "name": "Included game",
                        "platform": None,
                    },
                },
                {
                    "model": "games.session",
                    "pk": 302,
                    "fields": {
                        "game": PRESENT_GAME_UUID,
                        "device": ABSENT_DEVICE_UUID,
                    },
                },
            ]
        )
    )
    monkeypatch.setattr(load_sample_data, "FIXTURE_PATH", fixture)

    with pytest.raises(
        CommandError, match=rf"references Device {ABSENT_DEVICE_UUID}.*not included"
    ):
        call_command("load_sample_data", "--user", owner.username, verbosity=0)


@pytest.mark.django_db
def test_sample_load_rejects_duplicate_fixture_primary_keys(
    owner, monkeypatch, tmp_path
):
    from games.management.commands import load_sample_data

    fixture = tmp_path / "sample.yaml"
    duplicate_device_id = "00000000-0000-7000-8000-000000000401"
    fixture.write_text(
        yaml.safe_dump(
            [
                {
                    "model": "games.device",
                    "pk": duplicate_device_id,
                    "fields": {
                        "library": "__target_library__",
                        "name": "First",
                    },
                },
                {
                    "model": "games.device",
                    "pk": duplicate_device_id,
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
        match=rf"duplicate games.device primary key {duplicate_device_id}",
    ):
        call_command("load_sample_data", "--user", owner.username, verbosity=0)

    assert not Device.objects.filter(pk=duplicate_device_id).exists()


@pytest.mark.django_db(transaction=True)
def test_sample_load_force_inserts_and_rolls_back_a_late_primary_key_collision(
    owner, monkeypatch, tmp_path
):
    from games.management.commands import load_sample_data

    fixture = tmp_path / "sample.yaml"
    colliding_device_id = "00000000-0000-7000-8000-000000000503"
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
                    "model": "games.device",
                    "pk": colliding_device_id,
                    "fields": {
                        "library": "__target_library__",
                        "name": "Fixture device",
                        "created_at": "2025-01-01 00:00:00+00:00",
                    },
                },
            ]
        )
    )
    monkeypatch.setattr(load_sample_data, "FIXTURE_PATH", fixture)
    original_check = load_sample_data.Command._reject_primary_key_collisions

    def insert_after_check(records):
        original_check(records)
        Device.objects.create(
            pk=colliding_device_id,
            library=owner.library,
            name="Concurrent device",
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
    assert not Device.objects.filter(pk=colliding_device_id).exists()
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
    _, owner_device, owner_game, _ = _owned_graph(owner)
    _, _, outsider_game, outsider_purchase = _owned_graph(outsider)
    outsider_session = outsider_game.sessions.get()

    Game.objects.filter(pk=outsider_game.pk).update(platform=owner_platform)
    Purchase.objects.filter(pk=outsider_purchase.pk).update(
        platform=owner_platform,
        related_game=owner_game,
    )
    Purchase.games.through.objects.create(
        purchase_id=outsider_purchase.pk,
        game_id=owner_game.pk,
    )
    Session.objects.filter(pk=outsider_session.pk).update(device=owner_device)
    UserLibraryPreferences.objects.filter(library=outsider.library).update(
        default_device=owner_device
    )
    Playthrough.objects.create(
        id=uuid7(),
        library=owner.library,
        player_game=PlayerGame.objects.get(game=outsider_game),
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

    report = output.getvalue()
    for relation in (
        "Game.platform",
        "Purchase.platform",
        "Purchase.related_game",
        "Purchase.games",
        "Session.device",
        "UserLibraryPreferences.default_device",
        "Playthrough.player_game",
    ):
        assert relation in report
    assert (
        f"Session.device: session {outsider_session.pk}, device {owner_device.pk}"
        in report
    )
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
        f"Playthrough.player_game: playthrough {run.pk}, "
        f"tracked game {tracked.pk}" in output.getvalue()
    )


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
