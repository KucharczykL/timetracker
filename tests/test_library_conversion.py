"""Per-library conversion is versioned, atomic, and recoverable."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from importlib.util import find_spec
from threading import Event, Thread
from unittest.mock import Mock

import pytest
from django.contrib.auth import get_user_model
from django.db import DatabaseError, close_old_connections, connection
from django.test import Client
from django.utils import timezone
from entries import record_entry
from graphs import default_graph
from purchases import record_purchase, request_run

from games.exchange_rates import RateFetchFailed
from games.models import (
    ExchangeRate,
    Game,
    PurchaseConversionState,
    PurchaseValuation,
    UserLibrary,
)
from timetracker.temporal import TemporalValue


@pytest.fixture
def owner(db):
    return get_user_model().objects.create_user(username="conversion-owner")


@pytest.fixture
def outsider(db):
    return get_user_model().objects.create_user(username="conversion-outsider")


def _state(owner, **values):
    defaults = {
        "requested_version": 0,
        "requested_currency": "",
        "published_version": 0,
        "published_currency": "",
        "status": PurchaseConversionState.Status.COMPLETE,
        "retry_at": None,
        "last_error": "",
    }
    defaults.update(values)
    return PurchaseConversionState.objects.update_or_create(
        library=owner.library, defaults=defaults
    )[0]


def test_conversion_module_and_public_interfaces_exist():
    """Removing the bridge module or either public command breaks Task 7 callers."""
    assert find_spec("games.conversion") is not None

    from games.conversion import request_conversion
    from games.tasks import convert_library_prices

    assert callable(request_conversion)
    assert callable(convert_library_prices)


@pytest.mark.django_db
def test_new_user_is_provisioned_with_conversion_state(owner):
    """A newly provisioned library must be immediately readable by every page."""
    state = PurchaseConversionState.objects.get(library=owner.library)
    assert state.status == PurchaseConversionState.Status.COMPLETE
    assert state.requested_version == state.published_version == 0
    assert state.requested_currency == "CZK"
    assert state.published_currency == "CZK"


@pytest.mark.django_db
def test_request_conversion_increments_version_and_enqueues_after_commit(
    owner, monkeypatch, django_capture_on_commit_callbacks
):
    """A request without a committed version/job pair could be lost permanently."""
    from games import conversion

    queued = Mock()
    monkeypatch.setattr(conversion, "async_task", queued)

    with django_capture_on_commit_callbacks(execute=True):
        version = conversion.request_conversion(owner.library, "czk")

    state = PurchaseConversionState.objects.get(library=owner.library)
    assert version == 1
    assert (
        state.requested_version,
        state.requested_currency,
        state.status,
        state.retry_at,
        state.last_error,
    ) == (1, "CZK", PurchaseConversionState.Status.PENDING, None, "")
    queued.assert_called_once_with(
        "games.tasks.convert_library_prices", str(owner.library.pk), 1
    )


@pytest.mark.django_db
def test_five_rapid_requests_coalesce_to_last_target(
    owner, monkeypatch, django_capture_on_commit_callbacks
):
    """Intermediate display-currency choices must never become publishable."""
    from games import conversion

    queued = Mock()
    monkeypatch.setattr(conversion, "async_task", queued)
    versions = []
    with django_capture_on_commit_callbacks(execute=True):
        for target in ("USD", "EUR", "GBP", "JPY", "CZK"):
            versions.append(conversion.request_conversion(owner.library, target))

    state = PurchaseConversionState.objects.get(library=owner.library)
    assert versions == [1, 2, 3, 4, 5]
    assert (state.requested_version, state.requested_currency) == (5, "CZK")
    assert [call.args[-1] for call in queued.call_args_list] == versions


@pytest.mark.django_db
def test_old_job_cannot_publish_after_newer_request(owner, monkeypatch):
    """A delayed worker for an intermediate choice must be a no-op."""
    from games import tasks

    _bought_in_dollars(owner)
    _state(
        owner,
        requested_version=2,
        requested_currency="CZK",
        published_version=0,
        status=PurchaseConversionState.Status.PENDING,
    )
    rate = Mock(return_value=Decimal(2))
    monkeypatch.setattr(tasks, "exchange_rate", rate)

    tasks.convert_library_prices(str(owner.library.pk), 1)

    state = PurchaseConversionState.objects.get(library=owner.library)
    assert not PurchaseValuation.objects.filter(library=owner.library).exists()
    assert (state.requested_version, state.published_version, state.status) == (
        2,
        0,
        PurchaseConversionState.Status.PENDING,
    )
    rate.assert_not_called()


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("currency", "failing", "error"),
    [
        ("USD", "publish_valuations", DatabaseError("publication refused")),
        ("CZK", "exchange_rate", RateFetchFailed("rate source offline")),
    ],
    ids=["database", "rate source"],
)
def test_a_failed_run_schedules_one_retry(owner, monkeypatch, currency, failing, error):
    """A transient failure exposes bounded recovery."""
    from games import tasks

    _bought_in_dollars(owner)
    _state(
        owner,
        requested_version=1,
        requested_currency=currency,
        published_version=0,
        status=PurchaseConversionState.Status.PENDING,
    )

    def refuse(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(tasks, failing, refuse)
    scheduled = Mock()
    monkeypatch.setattr(tasks, "schedule", scheduled)
    before = timezone.now()

    tasks.convert_library_prices(str(owner.library.pk), 1)
    tasks.convert_library_prices(str(owner.library.pk), 1)

    state = PurchaseConversionState.objects.get(library=owner.library)
    assert not PurchaseValuation.objects.filter(library=owner.library).exists()
    assert state.status == PurchaseConversionState.Status.FAILED
    assert str(error) in state.last_error
    assert (
        before + timedelta(minutes=14) < state.retry_at < before + timedelta(minutes=16)
    )
    scheduled.assert_called_once()
    assert scheduled.call_args.args[:3] == (
        "games.tasks.convert_library_prices",
        str(owner.library.pk),
        1,
    )


@pytest.mark.django_db
def test_daily_recovery_enqueues_only_stale_libraries(owner, outsider, monkeypatch):
    """Recovery must neither ignore failed work nor churn complete libraries."""
    from games import tasks

    _state(
        owner,
        requested_version=2,
        requested_currency="CZK",
        published_version=1,
        published_currency="EUR",
        status=PurchaseConversionState.Status.FAILED,
        retry_at=timezone.now() - timedelta(minutes=1),
    )
    _state(
        outsider,
        requested_version=3,
        requested_currency="USD",
        published_version=3,
        published_currency="USD",
        status=PurchaseConversionState.Status.COMPLETE,
    )
    queued = Mock()
    monkeypatch.setattr(tasks, "async_task", queued)

    tasks.recover_library_price_conversions()

    queued.assert_called_once_with(
        "games.tasks.convert_library_prices", str(owner.library.pk), 2
    )


@pytest.mark.django_db
def test_conversion_status_is_authenticated_and_library_scoped(owner, outsider):
    """The status route must not accept a library id or disclose another user's work."""
    retry_at = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)
    _state(
        owner,
        requested_version=4,
        requested_currency="CZK",
        published_version=3,
        published_currency="EUR",
        status=PurchaseConversionState.Status.FAILED,
        retry_at=retry_at,
        last_error="rate unavailable",
    )
    _state(
        outsider,
        requested_version=99,
        requested_currency="JPY",
        published_version=98,
        published_currency="USD",
        status=PurchaseConversionState.Status.RUNNING,
    )

    assert Client().get("/api/conversion/status").status_code == 401
    client = Client()
    client.force_login(owner)
    response = client.get("/api/conversion/status")

    assert response.status_code == 200
    assert response.json() == {
        "library_id": str(owner.library.pk),
        "requested_version": 4,
        "requested_currency": "CZK",
        "published_version": 3,
        "published_currency": "EUR",
        "status": "failed",
        "retry_at": "2026-08-15T12:00:00Z",
        "last_error": "rate unavailable",
    }


@pytest.mark.django_db
def test_authenticated_pages_embed_only_their_library_conversion_state(owner):
    state = _state(
        owner,
        requested_version=4,
        requested_currency="CZK",
        published_version=3,
        published_currency="EUR",
        status=PurchaseConversionState.Status.RUNNING,
    )
    client = Client()
    client.force_login(owner)

    html = client.get("/tracker/settings").content.decode()
    root = html[html.index("<html") : html.index(">", html.index("<html")) + 1]

    assert 'data-library-conversion-state="' in root
    assert str(state.library_id) in root
    assert "requested_version" in root
    assert 'data-library-conversion-status-url="/api/conversion/status"' in root
    assert "dist/library-conversion-status.js" in html


@pytest.mark.django_db
def test_anonymous_pages_embed_no_library_conversion_details():
    html = Client().get("/login/").content.decode()
    root = html[html.index("<html") : html.index(">", html.index("<html")) + 1]

    assert "data-library-conversion-state" not in root
    assert "data-library-conversion-status-url" not in root
    assert "dist/library-conversion-status.js" not in html


@pytest.mark.django_db
def test_site_display_change_requests_only_inheriting_libraries(
    owner,
    outsider,
    monkeypatch,
    django_capture_on_commit_callbacks,
):
    from games import conversion
    from timetracker.settings_commands import change_site_setting

    outsider.preferences.default_display_currency = "USD"
    outsider.preferences.save(update_fields=["default_display_currency", "updated_at"])
    queued = Mock()
    monkeypatch.setattr(conversion, "async_task", queued)

    with django_capture_on_commit_callbacks(execute=True):
        mutation = change_site_setting("DEFAULT_DISPLAY_CURRENCY", "EUR")

    owner_state = PurchaseConversionState.objects.get(library=owner.library)
    outsider_state = PurchaseConversionState.objects.get(library=outsider.library)
    assert mutation.changed is True
    assert (owner_state.requested_version, owner_state.requested_currency) == (1, "EUR")
    assert outsider_state.requested_version == 0
    queued.assert_called_once_with(
        "games.tasks.convert_library_prices", str(owner.library.pk), 1
    )


@pytest.mark.django_db
def test_noop_effective_site_display_change_requests_nothing(
    owner,
    monkeypatch,
    django_capture_on_commit_callbacks,
):
    from games import conversion
    from timetracker.settings_commands import change_site_setting

    queued = Mock()
    monkeypatch.setattr(conversion, "async_task", queued)

    with django_capture_on_commit_callbacks(execute=True):
        mutation = change_site_setting("DEFAULT_DISPLAY_CURRENCY", "CZK")

    state = PurchaseConversionState.objects.get(library=owner.library)
    assert mutation.changed is True
    assert state.requested_version == 0
    queued.assert_not_called()


@pytest.mark.django_db
def test_personal_display_change_and_clear_each_request_effective_target(
    owner,
    monkeypatch,
    django_capture_on_commit_callbacks,
):
    from games import conversion
    from timetracker.settings_commands import (
        change_site_setting,
        change_user_setting,
    )

    queued = Mock()
    monkeypatch.setattr(conversion, "async_task", queued)
    with django_capture_on_commit_callbacks(execute=True):
        change_site_setting("DEFAULT_DISPLAY_CURRENCY", "EUR")
        change_user_setting(owner, "DEFAULT_DISPLAY_CURRENCY", "GBP")
        change_user_setting(owner, "DEFAULT_DISPLAY_CURRENCY", "GBP")
        change_user_setting(owner, "DEFAULT_DISPLAY_CURRENCY", None)

    state = PurchaseConversionState.objects.get(library=owner.library)
    assert (state.requested_version, state.requested_currency) == (3, "EUR")
    assert [call.args[-1] for call in queued.call_args_list] == [1, 2, 3]


@pytest.mark.django_db
def test_daily_recovery_also_repairs_a_missed_pending_job(owner, monkeypatch):
    from games import tasks

    _state(
        owner,
        requested_version=2,
        requested_currency="CZK",
        published_version=1,
        published_currency="EUR",
        status=PurchaseConversionState.Status.PENDING,
    )
    queued = Mock()
    monkeypatch.setattr(tasks, "async_task", queued)

    tasks.recover_library_price_conversions()

    queued.assert_called_once_with(
        "games.tasks.convert_library_prices", str(owner.library.pk), 2
    )


def _bought_in_dollars(owner):
    """A ten-dollar purchase, bought in 2025."""
    library = owner.library
    graph = default_graph(Game(library=library, name="Priced"), library)
    return record_purchase(
        record_entry(library, graph.release),
        amount=Decimal(10),
        currency="USD",
        purchased=TemporalValue.parse("2025-01-01"),
    )


def _publish(owner, monkeypatch, target: str, rate: Decimal) -> None:
    """One run that values it in `target`."""
    from games import tasks

    ExchangeRate.objects.update_or_create(
        currency_from="USD", currency_to=target, year=2025, defaults={"rate": rate}
    )
    monkeypatch.setattr(tasks, "exchange_rate", lambda *_args: rate)
    tasks.convert_library_prices(
        str(owner.library.pk), request_run(owner.library, target)
    )


@pytest.mark.django_db
def test_statistics_label_previous_published_currency_while_new_request_failed(
    owner, monkeypatch
):
    from games.views.stats_data import compute_stats

    _bought_in_dollars(owner)
    _publish(owner, monkeypatch, "EUR", Decimal("0.9"))
    _state(
        owner,
        requested_version=2,
        requested_currency="CZK",
        published_version=1,
        published_currency="EUR",
        status=PurchaseConversionState.Status.FAILED,
        retry_at=timezone.now() + timedelta(minutes=15),
    )

    stats = compute_stats(owner.library, 2025)

    assert stats["total_spent"] == 9
    assert stats["total_spent_currency"] == "EUR"


@pytest.mark.django_db
def test_duplicate_job_exits_when_requested_version_is_already_published(
    owner, monkeypatch
):
    from games import tasks

    _bought_in_dollars(owner)
    _state(
        owner,
        requested_version=2,
        requested_currency="CZK",
        published_version=2,
        published_currency="CZK",
        status=PurchaseConversionState.Status.COMPLETE,
    )
    rate = Mock(side_effect=AssertionError("published job fetched a rate"))
    monkeypatch.setattr(tasks, "exchange_rate", rate)

    tasks.convert_library_prices(str(owner.library.pk), 2)

    state = PurchaseConversionState.objects.get(library=owner.library)
    assert not PurchaseValuation.objects.filter(library=owner.library).exists()
    assert state.status == PurchaseConversionState.Status.COMPLETE
    rate.assert_not_called()


@pytest.mark.django_db
def test_late_same_version_failure_cannot_replace_published_completion(owner):
    """A slower duplicate worker must not turn a published version into FAILED."""
    from games import tasks

    _state(
        owner,
        requested_version=2,
        requested_currency="CZK",
        published_version=2,
        published_currency="CZK",
        status=PurchaseConversionState.Status.COMPLETE,
    )

    tasks._mark_failed(
        str(owner.library.pk),
        2,
        RuntimeError("slower duplicate failed"),
        schedule_retry=False,
    )

    state = PurchaseConversionState.objects.get(library=owner.library)
    assert (state.status, state.retry_at, state.last_error) == (
        PurchaseConversionState.Status.COMPLETE,
        None,
        "",
    )


@pytest.mark.django_db
def test_losing_same_version_worker_cannot_republish_after_winner(owner, monkeypatch):
    """A duplicate already past its start check must not overwrite the winner."""
    from games import tasks

    _bought_in_dollars(owner)
    _state(
        owner,
        requested_version=2,
        requested_currency="CZK",
        published_version=1,
        published_currency="EUR",
        status=PurchaseConversionState.Status.PENDING,
    )

    def publish_winner_while_loser_fetches(*_args):
        PurchaseConversionState.objects.filter(library=owner.library).update(
            published_version=2,
            published_currency="CZK",
            status=PurchaseConversionState.Status.COMPLETE,
        )
        return Decimal(3)

    monkeypatch.setattr(tasks, "exchange_rate", publish_winner_while_loser_fetches)

    tasks.convert_library_prices(str(owner.library.pk), 2)

    state = PurchaseConversionState.objects.get(library=owner.library)
    assert not PurchaseValuation.objects.filter(library=owner.library).exists()
    assert (state.published_version, state.status) == (
        2,
        PurchaseConversionState.Status.COMPLETE,
    )


@pytest.mark.django_db(transaction=True)
def test_statistics_never_pair_new_total_with_previous_currency(owner, monkeypatch):
    """One rendered total must come from one complete publication snapshot."""
    from games.views.stats_data import compute_stats

    _bought_in_dollars(owner)
    _publish(owner, monkeypatch, "EUR", Decimal("0.9"))
    state_read = Event()
    publication_done = Event()
    errors: list[BaseException] = []
    result: dict[str, object] = {}

    def run_reader():
        close_old_connections()

        def pause_after_state_read(execute, sql, params, many, context):
            value = execute(sql, params, many, context)
            if (
                sql.lstrip().lower().startswith("select")
                and "games_purchaseconversionstate" in sql.lower()
            ):
                state_read.set()
                if not publication_done.wait(10):
                    raise TimeoutError("publication did not complete")
            return value

        try:
            with connection.execute_wrapper(pause_after_state_read):
                library = UserLibrary.objects.get(pk=owner.library.pk)
                result["stats"] = compute_stats(library, 2025)
        except Exception as error:  # noqa: BLE001 - return thread failures
            errors.append(error)
        finally:
            close_old_connections()

    reader = Thread(target=run_reader, name="stats-reader")
    reader.start()
    assert state_read.wait(10)
    try:
        _publish(owner, monkeypatch, "CZK", Decimal("1.8"))
    finally:
        publication_done.set()
    reader.join(10)

    assert not reader.is_alive()
    assert errors == []
    stats = result["stats"]
    assert isinstance(stats, dict)
    assert (stats["total_spent"], stats["total_spent_currency"]) in {
        (9, "EUR"),
        (18, "CZK"),
    }


@pytest.mark.django_db
def test_readiness_requires_conversion_state_for_every_library(owner):
    from django.core.exceptions import ImproperlyConfigured

    from games.readiness import assert_library_structure

    PurchaseConversionState.objects.filter(library=owner.library).delete()

    with pytest.raises(
        ImproperlyConfigured,
        match=f"PurchaseConversionState\\(library={owner.library.pk}\\)",
    ):
        assert_library_structure()
