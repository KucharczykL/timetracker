"""Game detail lists a game's historical playtime."""

import html
from datetime import timedelta
from urllib.parse import quote

import pytest
from django.urls import reverse
from historical_playtime_rows import record_row
from stated_runs import another_run
from test_column_priority_contract import header_policies

from games.filters import HistoricalPlaytimeFilter, filter_url
from games.models import Device, Game, HistoricalPlaytimeProvenance, Playthrough

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def logged_in(client, owned_user):
    client.force_login(owned_user)
    return client


@pytest.fixture
def game(owned_library) -> Game:
    return Game.objects.create(library=owned_library, name="Outer Wilds")


@pytest.fixture
def run(game) -> Playthrough:
    return Playthrough.objects.get(player_game__game=game)


def section(client, game: Game) -> str:
    page = client.get(game.get_absolute_url()).content.decode()
    start = page.index('id="historical-playtime-container"')
    end = page.index('id="playthroughs-container"')
    return page[start:end]


def test_the_section_sits_between_sessions_and_playthroughs(logged_in, game):
    page = logged_in.get(game.get_absolute_url()).content.decode()
    sessions = page.index(">Sessions<")
    historical = page.index(">Historical playtime<")
    playthroughs = page.index(">Playthroughs<")
    assert sessions < historical < playthroughs


def test_an_empty_section_says_so_and_still_offers_add(logged_in, game):
    html = section(logged_in, game)
    assert "No historical playtime." in html
    add = reverse("games:add_historical_playtime", args=[game.pk])
    assert f'href="{add}?origin=' in html


def test_rows_read_newest_first_with_an_unknown_when_last(logged_in, game, run):
    record_row([run], when="2005", note="older")
    record_row([run], when=None, note="unknown")
    record_row([run], when="2010", note="newer")
    html = section(logged_in, game)
    assert html.index("2010") < html.index("2005") < html.index("Unknown")


def test_a_row_states_duration_provenance_runs_and_device(
    logged_in, owned_user, owned_library, game, run
):
    second = another_run(owned_user, game)
    device = Device.objects.create(library=owned_library, name="Steam Deck")
    record_row(
        [run, second],
        duration=timedelta(hours=100),
        when="2005",
        provenance=HistoricalPlaytimeProvenance.MANUALLY_ENTERED,
        device=device,
    )
    html = section(logged_in, game)
    assert "Manually entered" in html
    assert "Playthrough 1, Playthrough 2" in html
    assert "Steam Deck" in html
    assert ">1<" in html  # the count badge


def test_a_row_without_a_device_says_so(logged_in, game, run):
    record_row([run])
    assert "No device" in section(logged_in, game)


def test_row_actions_carry_the_origin(logged_in, game, run):
    record = record_row([run])
    html = section(logged_in, game)
    origin = quote(game.get_absolute_url(), safe="")
    for route in ("games:edit_historical_playtime", "games:remove_historical_playtime"):
        url = reverse(route, args=[record.pk])
        assert f'href="{url}?origin={origin}"' in html


def test_view_all_opens_the_list_narrowed_to_the_game(logged_in, game, run):
    record_row([run])
    view_all = filter_url(HistoricalPlaytimeFilter.where(game=[game.id]))
    assert html.escape(view_all) in section(logged_in, game)


def test_actions_outrank_every_other_column(logged_in, game, run):
    record_row([run])
    [policies] = header_policies(section(logged_in, game))
    actions = dict(policies)["Actions"]
    assert all(actions > priority for label, priority in policies if label != "Actions")


def test_a_removed_record_is_not_listed(logged_in, game, run):
    record = record_row([run], note="gone")
    type(record).objects.filter(pk=record.pk).update(removed_at=record.created_at)
    assert "No historical playtime." in section(logged_in, game)
