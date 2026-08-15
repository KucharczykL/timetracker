"""Per-library conversion is versioned, atomic, and recoverable."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from importlib.util import find_spec
from threading import Event, Thread
from unittest.mock import Mock

import pytest
from django.contrib.auth import get_user_model
from django.db import close_old_connections, connection, transaction
from django.test import Client
from django.utils import timezone

from games.models import (
    Purchase,
    PurchaseConversionState,
    UserLibrary,
    UserPreferences,
)


@pytest.fixture
def owner(db):
    return get_user_model().objects.create_user(username="conversion-owner")


@pytest.fixture
def outsider(db):
    return get_user_model().objects.create_user(username="conversion-outsider")


def _purchase(
    owner,
    *,
    price=10,
    currency="USD",
    converted=111,
    converted_currency="EUR",
):
    return Purchase.objects.create(
        library=owner.library,
        price=price,
        price_currency=currency,
        date_purchased=date(2025, 1, 1),
        converted_price=converted,
        converted_currency=converted_currency,
        needs_price_update=True,
    )


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
def test_same_currency_and_zero_price_publish_without_exchange_rate(owner, monkeypatch):
    """Trivial rows must not fail merely because no external rate exists."""
    from games import tasks

    same = _purchase(owner, price=12, currency="CZK")
    zero = _purchase(owner, price=0, currency="USD")
    _state(
        owner,
        requested_version=1,
        requested_currency="CZK",
        status=PurchaseConversionState.Status.PENDING,
    )
    rate = Mock(side_effect=AssertionError("trivial conversion fetched a rate"))
    monkeypatch.setattr(tasks, "_get_exchange_rate", rate)

    tasks.convert_library_prices(str(owner.library.pk), 1)

    same.refresh_from_db()
    zero.refresh_from_db()
    state = PurchaseConversionState.objects.get(library=owner.library)
    assert (same.converted_price, same.converted_currency, same.needs_price_update) == (
        12,
        "CZK",
        False,
    )
    assert (zero.converted_price, zero.converted_currency, zero.needs_price_update) == (
        0,
        "CZK",
        False,
    )
    assert (
        state.published_version,
        state.published_currency,
        state.status,
        state.retry_at,
        state.last_error,
    ) == (1, "CZK", PurchaseConversionState.Status.COMPLETE, None, "")


@pytest.mark.django_db
def test_old_job_cannot_publish_after_newer_request(owner, monkeypatch):
    """A delayed worker for an intermediate choice must be a no-op."""
    from games import tasks

    purchase = _purchase(owner)
    _state(
        owner,
        requested_version=2,
        requested_currency="CZK",
        published_version=0,
        status=PurchaseConversionState.Status.PENDING,
    )
    rate = Mock(return_value=2)
    monkeypatch.setattr(tasks, "_get_exchange_rate", rate)

    tasks.convert_library_prices(str(owner.library.pk), 1)

    purchase.refresh_from_db()
    state = PurchaseConversionState.objects.get(library=owner.library)
    assert (purchase.converted_price, purchase.converted_currency) == (111, "EUR")
    assert (state.requested_version, state.published_version, state.status) == (
        2,
        0,
        PurchaseConversionState.Status.PENDING,
    )
    rate.assert_not_called()


@pytest.mark.django_db(transaction=True)
def test_purchase_edit_invalidates_candidate_before_publication(owner, monkeypatch):
    """A conversion calculated from stale original facts must be discarded."""
    from games import conversion, tasks

    purchase = _purchase(owner)
    _state(
        owner,
        requested_version=1,
        requested_currency="CZK",
        published_version=0,
        status=PurchaseConversionState.Status.PENDING,
    )
    monkeypatch.setattr(conversion, "async_task", Mock())

    def edit_while_fetching(*_args):
        purchase.price = 20
        purchase.save(update_fields=["price", "updated_at"])
        return 2

    monkeypatch.setattr(tasks, "_get_exchange_rate", edit_while_fetching)

    tasks.convert_library_prices(str(owner.library.pk), 1)

    purchase.refresh_from_db()
    state = PurchaseConversionState.objects.get(library=owner.library)
    assert purchase.converted_price == 111
    assert state.requested_version == 2
    assert state.published_version == 0
    assert state.status == PurchaseConversionState.Status.PENDING


@pytest.mark.django_db(transaction=True)
def test_publication_rolls_back_every_row_when_bulk_update_fails(owner, monkeypatch):
    """Readers must never observe part of a newly converted library."""
    from games import tasks

    first = _purchase(owner, price=10)
    second = _purchase(owner, price=20)
    _state(
        owner,
        requested_version=1,
        requested_currency="CZK",
        published_version=0,
        status=PurchaseConversionState.Status.PENDING,
    )
    monkeypatch.setattr(tasks, "_get_exchange_rate", lambda *_args: 2)

    def partial_then_fail(objects, fields):
        Purchase.objects.filter(pk=objects[0].pk).update(
            converted_price=objects[0].converted_price,
            converted_currency=objects[0].converted_currency,
        )
        raise RuntimeError("database write interrupted")

    monkeypatch.setattr(Purchase.objects, "bulk_update", partial_then_fail)

    tasks.convert_library_prices(str(owner.library.pk), 1)

    first.refresh_from_db()
    second.refresh_from_db()
    state = PurchaseConversionState.objects.get(library=owner.library)
    assert [
        (first.converted_price, first.converted_currency),
        (second.converted_price, second.converted_currency),
    ] == [(111, "EUR"), (111, "EUR")]
    assert state.published_version == 0
    assert state.status == PurchaseConversionState.Status.FAILED


@pytest.mark.django_db
def test_missing_rate_keeps_old_values_and_schedules_one_retry(owner, monkeypatch):
    """A missing rate must preserve the complete old cache and expose bounded recovery."""
    from games import tasks

    purchase = _purchase(owner)
    _state(
        owner,
        requested_version=1,
        requested_currency="CZK",
        published_version=0,
        status=PurchaseConversionState.Status.PENDING,
    )
    monkeypatch.setattr(tasks, "_get_exchange_rate", lambda *_args: None)
    scheduled = Mock()
    monkeypatch.setattr(tasks, "schedule", scheduled)
    before = timezone.now()

    tasks.convert_library_prices(str(owner.library.pk), 1)

    purchase.refresh_from_db()
    state = PurchaseConversionState.objects.get(library=owner.library)
    assert (purchase.converted_price, purchase.converted_currency) == (111, "EUR")
    assert state.status == PurchaseConversionState.Status.FAILED
    assert "USD" in state.last_error and "CZK" in state.last_error
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


@pytest.mark.django_db
def test_statistics_label_previous_published_currency_while_new_request_failed(owner):
    from games.views.stats_data import compute_stats

    _purchase(
        owner,
        price=10,
        currency="USD",
        converted=9,
        converted_currency="EUR",
    )
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

    purchase = _purchase(owner)
    _state(
        owner,
        requested_version=2,
        requested_currency="CZK",
        published_version=2,
        published_currency="CZK",
        status=PurchaseConversionState.Status.COMPLETE,
    )
    rate = Mock(side_effect=AssertionError("published job fetched a rate"))
    monkeypatch.setattr(tasks, "_get_exchange_rate", rate)

    tasks.convert_library_prices(str(owner.library.pk), 2)

    purchase.refresh_from_db()
    state = PurchaseConversionState.objects.get(library=owner.library)
    assert (purchase.converted_price, purchase.converted_currency) == (111, "EUR")
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

    purchase = _purchase(owner, price=10)
    _state(
        owner,
        requested_version=2,
        requested_currency="CZK",
        published_version=1,
        published_currency="EUR",
        status=PurchaseConversionState.Status.PENDING,
    )

    def publish_winner_while_loser_fetches(*_args):
        Purchase.objects.filter(pk=purchase.pk).update(
            converted_price=25,
            converted_currency="CZK",
            needs_price_update=False,
        )
        PurchaseConversionState.objects.filter(library=owner.library).update(
            published_version=2,
            published_currency="CZK",
            status=PurchaseConversionState.Status.COMPLETE,
        )
        return 3

    monkeypatch.setattr(tasks, "_get_exchange_rate", publish_winner_while_loser_fetches)

    tasks.convert_library_prices(str(owner.library.pk), 2)

    purchase.refresh_from_db()
    state = PurchaseConversionState.objects.get(library=owner.library)
    assert (purchase.converted_price, purchase.converted_currency) == (25, "CZK")
    assert (state.published_version, state.status) == (
        2,
        PurchaseConversionState.Status.COMPLETE,
    )


@pytest.mark.django_db(transaction=True)
def test_new_purchase_rolls_back_when_conversion_version_cannot_be_saved(
    owner, monkeypatch
):
    """Original facts must not commit without their matching requested version."""
    original_save = PurchaseConversionState.save

    def fail_version_increment(state, *args, **kwargs):
        if state.requested_version > 0:
            raise RuntimeError("conversion state unavailable")
        return original_save(state, *args, **kwargs)

    monkeypatch.setattr(PurchaseConversionState, "save", fail_version_increment)

    with pytest.raises(RuntimeError, match="conversion state unavailable"):
        _purchase(owner)

    assert not Purchase.objects.filter(library=owner.library).exists()


@pytest.mark.django_db(transaction=True)
def test_purchase_edit_rolls_back_when_conversion_version_cannot_be_saved(
    owner, monkeypatch
):
    """An edited original price and its conversion request are one commit."""
    purchase = _purchase(owner, price=10)
    _state(
        owner,
        requested_version=1,
        requested_currency="CZK",
        published_version=1,
        published_currency="CZK",
        status=PurchaseConversionState.Status.COMPLETE,
    )
    original_save = PurchaseConversionState.save

    def fail_version_increment(state, *args, **kwargs):
        if state.requested_version > 1:
            raise RuntimeError("conversion state unavailable")
        return original_save(state, *args, **kwargs)

    monkeypatch.setattr(PurchaseConversionState, "save", fail_version_increment)
    purchase.price = 20

    with pytest.raises(RuntimeError, match="conversion state unavailable"):
        purchase.save(update_fields=["price", "updated_at"])

    purchase.refresh_from_db()
    assert purchase.price == 10


@pytest.mark.django_db(transaction=True)
def test_purchase_save_preserves_target_committed_by_another_settings_worker(
    owner, monkeypatch
):
    """A stale resolver cache must not supersede the serialized state target."""
    from games import conversion
    from timetracker.settings_resolver import resolve_for_user_with_origin

    monkeypatch.setattr(conversion, "async_task", Mock())
    assert (
        resolve_for_user_with_origin(owner, "DEFAULT_DISPLAY_CURRENCY").value == "CZK"
    )
    UserPreferences.objects.filter(user=owner).update(default_display_currency="EUR")
    _state(
        owner,
        requested_version=1,
        requested_currency="EUR",
        published_version=0,
        published_currency="CZK",
        status=PurchaseConversionState.Status.PENDING,
    )

    _purchase(owner)

    state = PurchaseConversionState.objects.get(library=owner.library)
    assert (state.requested_version, state.requested_currency) == (2, "EUR")


@pytest.mark.django_db(transaction=True)
def test_purchase_date_edit_requests_conversion_for_the_new_rate_year(
    owner, monkeypatch
):
    """Changing the exchange-rate year must invalidate the published conversion."""
    from games import conversion

    monkeypatch.setattr(conversion, "async_task", Mock())
    purchase = _purchase(owner)
    Purchase.objects.filter(pk=purchase.pk).update(needs_price_update=False)
    _state(
        owner,
        requested_version=1,
        requested_currency="CZK",
        published_version=1,
        published_currency="CZK",
        status=PurchaseConversionState.Status.COMPLETE,
    )
    purchase.needs_price_update = False
    purchase.date_purchased = date(2024, 1, 1)

    purchase.save(update_fields=["date_purchased", "updated_at"])

    purchase.refresh_from_db()
    state = PurchaseConversionState.objects.get(library=owner.library)
    assert purchase.needs_price_update is True
    assert (
        state.requested_version,
        state.requested_currency,
        state.status,
    ) == (2, "CZK", PurchaseConversionState.Status.PENDING)


@pytest.mark.django_db(transaction=True)
def test_purchase_fallback_insert_requests_conversion(owner, monkeypatch):
    """A zero-row update fallback must be treated as a new conversion input set."""
    from games import conversion

    monkeypatch.setattr(conversion, "async_task", Mock())
    purchase = _purchase(owner)
    Purchase.objects.filter(pk=purchase.pk).update(needs_price_update=False)
    _state(
        owner,
        requested_version=1,
        requested_currency="CZK",
        published_version=1,
        published_currency="CZK",
        status=PurchaseConversionState.Status.COMPLETE,
    )
    purchase.needs_price_update = False
    Purchase.objects.filter(pk=purchase.pk).delete()

    purchase.save()

    purchase.refresh_from_db()
    state = PurchaseConversionState.objects.get(library=owner.library)
    assert purchase.needs_price_update is True
    assert (
        state.requested_version,
        state.requested_currency,
        state.status,
    ) == (2, "CZK", PurchaseConversionState.Status.PENDING)


@pytest.mark.django_db(transaction=True)
def test_purchase_edit_and_publication_lock_state_before_purchase(owner, monkeypatch):
    """Concurrent edit/publication must complete without a lock-order deadlock."""
    from games import conversion, tasks

    purchase = _purchase(owner, price=10)
    _state(
        owner,
        requested_version=1,
        requested_currency="CZK",
        published_version=0,
        published_currency="EUR",
        status=PurchaseConversionState.Status.PENDING,
    )
    monkeypatch.setattr(conversion, "async_task", Mock())
    monkeypatch.setattr(tasks, "_get_exchange_rate", lambda *_args: 2)

    worker_at_publication = Event()
    editor_at_state_lock = Event()
    release_worker = Event()
    errors: list[BaseException] = []
    original_bulk_update = Purchase.objects.bulk_update

    def hold_publication(objects, fields):
        worker_at_publication.set()
        if not release_worker.wait(10):
            raise TimeoutError("editor never reached the conversion state")
        return original_bulk_update(objects, fields)

    monkeypatch.setattr(Purchase.objects, "bulk_update", hold_publication)

    def run_worker():
        close_old_connections()
        try:
            tasks.convert_library_prices(str(owner.library.pk), 1)
        except Exception as error:  # noqa: BLE001 - return thread failures
            errors.append(error)
        finally:
            close_old_connections()

    def run_editor():
        close_old_connections()

        def observe_state_lock(execute, sql, params, many, context):
            if "games_purchaseconversionstate" in sql.lower():
                editor_at_state_lock.set()
            return execute(sql, params, many, context)

        try:
            with connection.execute_wrapper(observe_state_lock), transaction.atomic():
                edited = Purchase.objects.get(pk=purchase.pk)
                edited.price = 20
                edited.save(update_fields=["price", "updated_at"])
        except Exception as error:  # noqa: BLE001 - return thread failures
            errors.append(error)
        finally:
            close_old_connections()

    worker = Thread(target=run_worker, name="conversion-worker")
    editor = Thread(target=run_editor, name="purchase-editor")
    worker.start()
    assert worker_at_publication.wait(10)
    editor.start()
    assert editor_at_state_lock.wait(10)
    release_worker.set()
    worker.join(10)
    editor.join(10)

    assert not worker.is_alive()
    assert not editor.is_alive()
    assert errors == []
    purchase.refresh_from_db()
    state = PurchaseConversionState.objects.get(library=owner.library)
    assert purchase.price == 20
    assert (
        state.requested_version,
        state.published_version,
        state.status,
    ) == (2, 1, PurchaseConversionState.Status.PENDING)


@pytest.mark.django_db(transaction=True)
def test_statistics_never_pair_new_total_with_previous_currency(owner):
    """One rendered total must come from one complete publication snapshot."""
    from games.views.stats_data import compute_stats

    purchase = _purchase(
        owner,
        price=10,
        currency="USD",
        converted=9,
        converted_currency="EUR",
    )
    _state(
        owner,
        requested_version=2,
        requested_currency="CZK",
        published_version=1,
        published_currency="EUR",
        status=PurchaseConversionState.Status.RUNNING,
    )
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
        with transaction.atomic():
            state = PurchaseConversionState.objects.select_for_update().get(
                library=owner.library
            )
            Purchase.objects.filter(pk=purchase.pk).update(
                converted_price=18,
                converted_currency="CZK",
                needs_price_update=False,
            )
            state.published_version = 2
            state.published_currency = "CZK"
            state.status = PurchaseConversionState.Status.COMPLETE
            state.save(
                update_fields=[
                    "published_version",
                    "published_currency",
                    "status",
                ]
            )
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
