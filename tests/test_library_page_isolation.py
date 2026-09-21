import re
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory
from django.urls import reverse
from django.utils import timezone
from historical_playtime_rows import record_row
from session_rows import session_row, timed_row, tracked_run
from statistic_cards import statistic_card

from common.duration_presentation import duration_presentation_for_request
from common.layout import recent_session_resumes
from common.returns import action_url
from games.models import (
    Device,
    Game,
    Platform,
    PlayerSession,
    Playthrough,
    Purchase,
)
from games.views.general import model_counts

pytestmark = pytest.mark.django_db


def test_library_page_requires_login(client):
    response = client.get("/tracker/library")

    assert response.status_code == 302
    assert "/login/" in response["Location"]


def test_library_page_shows_only_current_library_records(client, django_user_model):
    owner = django_user_model.objects.create_user(
        username="library-owner", password="p"
    )
    other = django_user_model.objects.create_user(username="other-owner", password="p")
    owned_game = Game.objects.create(library=owner.library, name="Owned game")
    foreign_game = Game.objects.create(library=other.library, name="Foreign game")
    Device.objects.create(library=owner.library, name="Owned device")
    Device.objects.create(library=other.library, name="Foreign device")
    started_at = timezone.now() - timedelta(hours=12)
    #: Three distinct durations, so the figure states which rows it read.
    timed_row(
        tracked_run(owner.library, owned_game),
        started_at,
        started_at + timedelta(hours=1),
    )
    timed_row(
        tracked_run(owner.library, owned_game),
        started_at,
        started_at + timedelta(hours=5),
        removed_at=timezone.now(),
    )
    timed_row(
        tracked_run(other.library, foreign_game),
        started_at,
        started_at + timedelta(hours=9),
    )
    client.force_login(owner)

    response = client.get("/tracker/library")

    assert response.status_code == 200
    body = response.content.decode()
    assert "Library" in body
    assert "Activity is coming later" in body
    assert "Games currently includes every game in your library." in body
    assert str(owner.library.pk) in body
    assert "1 Games" in body
    playtime_card = statistic_card(body, "Playtime")
    assert 'title="Tracked sessions and historical records"' in playtime_card
    #: The owner's live hour alone. The removed row would read 6.0 h, the
    #: other library's 10.0 h, and both 15.0 h.
    assert "1.0 h" in playtime_card
    assert "6.0 h" not in playtime_card
    assert "10.0 h" not in playtime_card
    assert "15.0 h" not in playtime_card
    assert "1 Devices" in body
    assert 'data-setting-key="default-device"' in body
    assert 'data-setting-source="library"' in body
    assert 'data-live-setting-control=""' in body
    default_device_url = reverse("api-1.0.0:update_library_default_device")
    patch_url_template = default_device_url.removesuffix("default-device") + "__key__"
    assert f'patch-url-template="{patch_url_template}"' in body
    assert "Preselected when logging a game." in body
    add_purchase_url = action_url("games:add_purchase", origin=reverse("games:library"))
    add_purchase_links = re.findall(
        rf'<a\b[^>]*href="{re.escape(add_purchase_url)}"[^>]*>', body
    )
    # Summary actions render both the wide link and narrow overflow-menu item;
    # both must carry the Library return target.
    assert len(add_purchase_links) == 2
    assert all("bg-success" not in link for link in add_purchase_links)
    assert "Foreign game" not in body
    assert "Foreign device" not in body


def test_library_page_evaluates_each_summary_count_once(
    client, django_user_model, django_assert_num_queries
):
    """Twenty-three queries; the Playtime count is one.

    The navbar reads the library's calendar to cut its day
    window, and that read costs nothing here: the user and
    its library arrive in one statement, so the number is
    what it was before either.
    """
    owner = django_user_model.objects.create_user(username="query-owner", password="p")
    client.force_login(owner)

    with django_assert_num_queries(23):
        response = client.get("/tracker/library")

    assert response.status_code == 200


@pytest.fixture
def world(client, django_user_model):
    owner = django_user_model.objects.create_user(username="owner", password="p")
    foreign_user = django_user_model.objects.create_user(
        username="foreign", password="p"
    )
    owner_library = owner.library
    foreign_library = foreign_user.library
    client.force_login(owner)
    # Return 500 responses instead of re-raising the current global `.get()`
    # leaks; RED must compare observable HTTP behavior (500/200 vs 404).
    client.raise_request_exception = False

    shared_platform = Platform.objects.create(name="Shared catalogue platform")
    own_platform = Platform.objects.create(
        library=owner_library, name="Owner private platform"
    )
    foreign_platform = Platform.objects.create(
        library=foreign_library, name="Foreign private platform"
    )
    own_game = Game.objects.create(
        library=owner_library, name="Owner game", platform=own_platform
    )
    foreign_game = Game.objects.create(
        library=foreign_library, name="Foreign game", platform=foreign_platform
    )
    own_device = Device.objects.create(library=owner_library, name="Owner device")
    foreign_device = Device.objects.create(
        library=foreign_library, name="Foreign device"
    )

    now = timezone.now()
    #: The navbar sums the local day (#949).
    start_of_today = timezone.localtime(now).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    own_start = max(now - timedelta(hours=1), start_of_today)
    foreign_start = max(now - timedelta(hours=6), start_of_today)
    #: The projection's twins, which the navbar and the counts read.
    own_row = session_row(
        own_game,
        device=own_device,
        started_at=own_start,
        ended_at=own_start + timedelta(hours=1),
    )
    foreign_row = session_row(
        foreign_game,
        device=foreign_device,
        started_at=foreign_start,
        ended_at=foreign_start + timedelta(hours=6),
    )
    #: Earlier than own_row, so the resume still names that one.
    own_running = session_row(
        own_game, device=own_device, started_at=own_start - timedelta(hours=3)
    )
    own_purchase = Purchase.objects.create(
        library=owner_library,
        name="Owner purchase",
        platform=own_platform,
        date_purchased=now.date(),
        price=10,
        price_currency="USD",
        converted_price=10,
        converted_currency="USD",
    )
    own_purchase.games.add(own_game)
    foreign_purchase = Purchase.objects.create(
        library=foreign_library,
        name="Foreign purchase",
        platform=foreign_platform,
        date_purchased=now.date(),
        price=20,
        price_currency="USD",
        converted_price=20,
        converted_currency="USD",
    )
    foreign_purchase.games.add(foreign_game)
    #: #1012 keyed the edit route on the run, and tracking
    #: states one, so each library names its own. None where
    #: the test tracks no game, which names no run either.
    own_run = Playthrough.objects.filter(library=owner_library).first()
    foreign_run = Playthrough.objects.filter(library=foreign_library).first()
    own_record = record_row([own_run])
    foreign_record = record_row([foreign_run])
    return SimpleNamespace(**locals())


@pytest.mark.parametrize(
    ("url_name", "own_text", "foreign_text"),
    [
        ("games:list_games", "Owner game", "Foreign game"),
        ("games:list_sessions", "Owner game", "Foreign game"),
        ("games:list_purchases", "Owner purchase", "Foreign purchase"),
        ("games:list_devices", "Owner device", "Foreign device"),
        ("games:list_platforms", "Owner private platform", "Foreign private platform"),
        ("games:list_playthroughs", "Owner game", "Foreign game"),
        ("games:list_historical_playtime", "Owner game", "Foreign game"),
    ],
)
def test_lists_show_owned_rows_and_omit_foreign_rows(
    world, url_name, own_text, foreign_text
):
    response = world.client.get(reverse(url_name))

    assert response.status_code == 200
    body = response.content.decode()
    assert own_text in body
    assert foreign_text not in body


def test_platform_management_list_omits_shared_catalogue_rows(world):
    body = world.client.get(reverse("games:list_platforms")).content.decode()

    assert world.own_platform.name in body
    assert world.shared_platform.name not in body


def _object_url(url_name, obj):
    if url_name == "games:view_game":
        return obj.get_absolute_url()
    return reverse(url_name, args=[obj.pk])


@pytest.mark.parametrize(
    ("url_name", "object_name"),
    [
        ("games:view_game", "foreign_game"),
        ("games:edit_game", "foreign_game"),
        ("games:remove_game", "foreign_game"),
        ("games:edit_session", "foreign_row"),
        ("games:reset_session", "foreign_row"),
        ("games:remove_session", "foreign_row"),
        ("games:view_purchase", "foreign_purchase"),
        ("games:edit_purchase", "foreign_purchase"),
        ("games:remove_purchase", "foreign_purchase"),
        ("games:refund_purchase_confirmation", "foreign_purchase"),
        ("games:split_purchase_confirmation", "foreign_purchase"),
        ("games:edit_device", "foreign_device"),
        ("games:remove_device", "foreign_device"),
        ("games:edit_platform", "foreign_platform"),
        ("games:remove_platform", "foreign_platform"),
        ("games:edit_platform", "shared_platform"),
        ("games:remove_platform", "shared_platform"),
        ("games:edit_playthrough", "foreign_run"),
        ("games:remove_playthrough", "foreign_run"),
    ],
)
def test_foreign_detail_edit_and_delete_reads_return_404(world, url_name, object_name):
    obj = getattr(world, object_name)

    assert world.client.get(_object_url(url_name, obj)).status_code == 404


@pytest.mark.parametrize(
    ("url_name", "object_name"),
    [
        ("games:view_game", "own_game"),
        ("games:edit_game", "own_game"),
        ("games:remove_game", "own_game"),
        ("games:edit_session", "own_row"),
        ("games:reset_session", "own_running"),
        ("games:remove_session", "own_row"),
        ("games:view_purchase", "own_purchase"),
        ("games:edit_purchase", "own_purchase"),
        ("games:remove_purchase", "own_purchase"),
        ("games:refund_purchase_confirmation", "own_purchase"),
        ("games:split_purchase_confirmation", "own_purchase"),
        ("games:edit_device", "own_device"),
        ("games:remove_device", "own_device"),
        ("games:edit_platform", "own_platform"),
        ("games:remove_platform", "own_platform"),
        ("games:edit_playthrough", "own_run"),
        ("games:remove_playthrough", "own_run"),
    ],
)
def test_owned_detail_edit_and_remove_reads_work(world, url_name, object_name):
    obj = getattr(world, object_name)

    assert world.client.get(_object_url(url_name, obj)).status_code == 200


@pytest.mark.parametrize(
    ("url_name", "object_name", "model"),
    [
        ("games:remove_game", "foreign_game", Game),
        ("games:remove_session", "foreign_row", PlayerSession),
        ("games:remove_purchase", "foreign_purchase", Purchase),
        ("games:remove_device", "foreign_device", Device),
        ("games:remove_platform", "foreign_platform", Platform),
        ("games:remove_playthrough", "foreign_run", Playthrough),
    ],
)
def test_foreign_removal_posts_return_404_without_mutation(
    world, url_name, object_name, model
):
    obj = getattr(world, object_name)

    response = world.client.post(reverse(url_name, args=[obj.pk]))

    assert response.status_code == 404
    assert model.objects.filter(pk=obj.pk).exists()


@pytest.mark.parametrize(
    ("url_name", "object_name", "model"),
    [
        ("games:remove_session", "own_row", PlayerSession),
        ("games:remove_purchase", "own_purchase", Purchase),
        ("games:remove_device", "own_device", Device),
        ("games:remove_platform", "own_platform", Platform),
        #: Removing a run stamps the projection,
        #: so test_removal_confirmation.py owns that assertion.
    ],
)
@pytest.mark.django_db(transaction=True)
@pytest.mark.untracked_games
def test_owned_removal_posts_work(world, url_name, object_name, model):
    obj = getattr(world, object_name)

    response = world.client.post(reverse(url_name, args=[obj.pk]))

    assert response.status_code == 302
    model.objects.filter(pk=obj.pk).get()
    assert model.objects.get(pk=obj.pk).removed_at is not None


#: A dispatch opens its own transaction.
@pytest.mark.django_db(transaction=True)
@pytest.mark.untracked_games
def test_owned_game_removal_post_works(world):
    game = world.own_game

    response = world.client.post(reverse("games:remove_game", args=[game.pk]))

    assert response.status_code == 302
    assert not Game.objects.for_library(world.owner_library).filter(pk=game.pk).exists()


@pytest.mark.parametrize(
    "url_name",
    [
        "games:add_session_for_game",
        "games:add_purchase_for_game",
        "games:add_playthrough_for_game",
    ],
)
def test_foreign_game_chained_add_pages_return_404(world, url_name):
    response = world.client.get(reverse(url_name, args=[world.foreign_game.pk]))

    assert response.status_code == 404


def test_foreign_session_action_posts_return_404_without_mutation(world):
    session = world.foreign_row
    original_start = session.started_at
    original_end = session.ended_at
    before = PlayerSession.objects.count()

    resume_response = world.client.post(
        reverse("games:resume_session", args=[world.foreign_game.pk])
    )
    finish_response = world.client.post(
        reverse("games:finish_session", args=[session.pk])
    )
    reset_response = world.client.post(
        reverse("games:reset_session", args=[session.pk])
    )

    session.refresh_from_db()
    assert (
        resume_response.status_code,
        finish_response.status_code,
        reset_response.status_code,
    ) == (
        404,
        404,
        404,
    )
    assert PlayerSession.objects.count() == before
    assert session.started_at == original_start
    assert session.ended_at == original_end


def test_foreign_purchase_action_posts_return_404_without_mutation(world):
    purchase = world.foreign_purchase
    before = Purchase.objects.count()

    refund_response = world.client.post(
        reverse("games:refund_purchase", args=[purchase.pk])
    )
    split_response = world.client.post(
        reverse("games:split_purchase", args=[purchase.pk])
    )

    purchase.refresh_from_db()
    assert (refund_response.status_code, split_response.status_code) == (404, 404)
    assert Purchase.objects.count() == before
    assert purchase.date_refunded is None


def test_navbar_recent_resumes_are_scoped_to_the_authenticated_library(world):
    request = RequestFactory().get("/")
    request.user = world.owner

    resumes = recent_session_resumes(request)

    assert [session.pk for session in resumes] == [world.own_row.pk]


def test_navbar_playtime_is_scoped_to_the_authenticated_library(world):
    request = RequestFactory().get("/")
    request.user = world.owner

    counts = model_counts(request)
    today_html = str(counts["today_played"])
    last_7_html = str(counts["last_7_played"])

    assert "1 h 00 m" in today_html
    assert "1 h 00 m" in last_7_html
    assert "7 h 00 m" not in today_html
    assert "7 h 00 m" not in last_7_html


def test_the_navbar_without_a_library_is_zero(client):
    with patch(
        "games.views.general.playtime_between_each",
        side_effect=AssertionError("no library reads no playtime"),
    ):
        request = RequestFactory().get("/")
        request.user = AnonymousUser()
        counts = model_counts(request)
        response = client.get(reverse("login"))

    zero = duration_presentation_for_request(request).format(timedelta(0))
    assert response.status_code == 200
    assert zero in str(counts["today_played"])
    assert zero in str(counts["last_7_played"])


def test_library_add_actions_preserve_the_library_as_the_return_origin(world):
    origin = reverse("games:library")
    body = world.client.get(origin).content.decode()

    for viewname in (
        "games:add_game",
        "games:add_platform",
        "games:add_device",
        "games:add_purchase",
    ):
        assert action_url(viewname, origin=origin) in body


def test_owned_or_404_is_lookup_only_for_an_already_scoped_queryset(world):
    from django.db.models import QuerySet
    from django.http import Http404

    from games.ownership import owned_or_404

    scoped_queryset = QuerySet(model=Game, using="default").filter(
        library=world.owner_library
    )

    assert (
        owned_or_404(scoped_queryset, world.owner_library, pk=world.own_game.pk)
        == world.own_game
    )
    with pytest.raises(Http404):
        owned_or_404(scoped_queryset, world.owner_library, pk=world.foreign_game.pk)
