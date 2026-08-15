from __future__ import annotations

from datetime import UTC, date, datetime
from io import StringIO

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError

from games.models import (
    Device,
    Game,
    Platform,
    PlayEvent,
    Purchase,
    PurchaseConversionState,
    Session,
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
def test_delete_user_library_is_a_warning_rich_dry_run_by_default(owner):
    _owned_graph(owner)
    output = StringIO()

    call_command("delete_user_library", "--user", owner.username, stdout=output)

    assert get_user_model().objects.filter(pk=owner.pk).exists()
    assert Game.objects.filter(library=owner.library).exists()
    report = output.getvalue()
    assert "WARNING" in report
    assert "DRY RUN" in report
    assert "games.Game: 1" in report


@pytest.mark.django_db
def test_delete_user_library_rejects_a_mismatched_confirmation(owner):
    _owned_graph(owner)

    with pytest.raises(CommandError, match="must exactly match"):
        call_command(
            "delete_user_library",
            "--user",
            owner.username,
            "--confirm",
            "someone-else",
        )

    assert get_user_model().objects.filter(pk=owner.pk).exists()


@pytest.mark.django_db
def test_delete_user_library_cascades_private_data_but_keeps_shared_platform(owner):
    platform, _, game, _ = _owned_graph(owner)
    output = StringIO()

    call_command(
        "delete_user_library",
        "--user",
        owner.username,
        "--confirm",
        owner.username,
        stdout=output,
    )

    assert not get_user_model().objects.filter(pk=owner.pk).exists()
    assert not Game.objects.filter(pk=game.pk).exists()
    assert Platform.objects.filter(pk=platform.pk, library__isnull=True).exists()
    assert "DELETED" in output.getvalue()


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
    assert Game.objects.filter(library=owner.library).exists()
    assert not Game.objects.exclude(library=owner.library).exists()
    assert Device.objects.filter(library=owner.library).exists()
    assert not Device.objects.exclude(library=owner.library).exists()
    assert Purchase.objects.filter(library=owner.library).exists()
    assert not Purchase.objects.exclude(library=owner.library).exists()
    assert not Session.objects.exclude(game__library=owner.library).exists()
    assert not PlayEvent.objects.exclude(game__library=owner.library).exists()


@pytest.mark.django_db
def test_sample_load_requests_conversion_when_preserved_cache_currency_differs(
    owner, monkeypatch, tmp_path
):
    from games import conversion
    from games.management.commands import load_sample_data

    queued = []
    monkeypatch.setattr(conversion, "async_task", lambda *args: queued.append(args))
    fixture = tmp_path / "sample.yaml"
    fixture.write_text(
        """- model: games.purchase
  pk: 101
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
    purchase = Purchase.objects.get(pk=101)
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
    fixture.write_text(
        """- model: games.device
  pk: 202
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

    assert not Device.objects.filter(pk=202).exists()
