"""The purchase conversion command."""

# conversion-tooling

import json
from datetime import date
from io import StringIO

import pytest
from django.core.management import CommandError, call_command
from legacy_purchases import LegacyCodes, legacy_row

from games.backfill import purchase as conversion
from games.backfill.legacy_model import legacy_purchase_model
from games.backfill.purchase import PurchaseConversionDrift
from games.backfill.purchase_reconciliation import Reconciliation
from games.models import (
    Game,
    GameKind,
    LibraryEvent,
    Platform,
    Purchase,
)

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.untracked_games,
    pytest.mark.usefixtures("legacy_purchase"),
]


@pytest.fixture
def row(owned_library, stated_graph):
    steam = Platform.objects.create(name="Steam", group="PC")
    game = stated_graph(
        Game(name="Tunic", library=owned_library), owned_library, platform=steam
    ).game
    return legacy_row(
        owned_library,
        game,
        date_purchased=date(2021, 5, 3),
        price=10.0,
        price_currency="EUR",
    )


def run(*arguments: str) -> str:
    out = StringIO()
    call_command("verify_purchase_conversion", *arguments, stdout=out)
    return out.getvalue()


def test_the_preflight_writes_nothing(owned_user, row):
    events = LibraryEvent.objects.count()

    printed = run("--user", owned_user.username)

    assert "PREFLIGHT" in printed
    assert "EUR: legacy 10.0, converted 10.00" in printed
    assert LibraryEvent.objects.count() == events


def test_confirm_commits(owned_user, row):
    run("--user", owned_user.username, "--confirm", owned_user.username)

    assert Purchase.objects.filter(pk=row.pk).exists()
    again = run("--user", owned_user.username, "--confirm", owned_user.username)
    assert "no live copy awaits conversion" in again
    assert "committed" not in again


def test_a_mismatched_confirmation_is_refused(owned_user, row):
    with pytest.raises(CommandError, match="exactly match"):
        run("--user", owned_user.username, "--confirm", "someone")
    assert not Purchase.objects.exists()


def test_the_snapshot_is_written(owned_user, owned_library, row, tmp_path):
    path = tmp_path / "legacy.json"

    run("--user", owned_user.username, "--snapshot", str(path))

    snapshot = json.loads(path.read_text())
    assert snapshot["library"] == str(owned_library.pk)
    assert set(snapshot["scopes"]) == {"all-time", "2021"}


def test_a_refusal_names_the_row(owned_user, row):
    legacy_purchase_model().objects.filter(pk=row.pk).update(price=1e12)
    out = StringIO()

    with pytest.raises(CommandError, match="1 refusal"):
        call_command(
            "verify_purchase_conversion", "--user", owned_user.username, stdout=out
        )

    assert str(row.pk) in out.getvalue()


def test_an_unexplained_difference_commits_nothing(owned_user, row, monkeypatch):
    monkeypatch.setattr(
        Reconciliation, "failures", lambda self: ["EUR: something moved"]
    )

    with pytest.raises(CommandError, match="1 unexplained"):
        run("--user", owned_user.username, "--confirm", owned_user.username)

    assert not Purchase.objects.exists()


def test_the_preflight_rolls_back_catalog_rows(owned_user, owned_library, row):
    base = Game.objects.get(pk=row.games.get().pk)
    legacy_row(
        owned_library,
        base,
        date_purchased=date(2021, 6, 1),
        price=5.0,
        price_currency="EUR",
        type=LegacyCodes.DLC,
        name="Expansion",
        related_game=base,
    )

    printed = run("--user", owned_user.username)

    assert "PREFLIGHT" in printed
    assert not Game.objects.filter(kind=GameKind.DLC).exists()


def test_a_drift_commits_nothing(owned_user, row, monkeypatch):
    def drifted(libraries):
        raise PurchaseConversionDrift("Library does not replay.")

    monkeypatch.setattr(conversion, "require_replay_parity", drifted)

    with pytest.raises(CommandError, match="Nothing converted"):
        run("--user", owned_user.username, "--confirm", owned_user.username)

    assert not Purchase.objects.exists()
