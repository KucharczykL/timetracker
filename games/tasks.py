import logging
from datetime import timedelta
from decimal import Decimal
from uuid import UUID

from django.db import DatabaseError, transaction
from django.db.models import F, Q
from django.utils.timezone import now
from django_q.models import Schedule
from django_q.tasks import async_task, schedule

from games.conversion import (
    _request_conversion_for_locked_state,
    request_revaluation,
)
from games.exchange_rates import RateFetchFailed, exchange_rate
from games.models import (
    PurchaseConversionState,
    UserLibrary,
)
from games.reads.purchases import stale_purchases, valuation_inputs
from games.valuations import (
    ConversionVersion,
    CurrencyCode,
    RateKey,
    ValuationInput,
    needs_rate,
    publish_valuations,
    value_all,
)

logger = logging.getLogger("games")


RETRY_DELAY = timedelta(minutes=15)
MAX_ERROR_LENGTH = 240


def _rates_for(
    snapshot: list[ValuationInput], target: CurrencyCode
) -> dict[RateKey, Decimal]:
    """The rates available; a missing key is absent."""
    needed = dict.fromkeys(
        facts.rate_key for facts in snapshot if needs_rate(facts, target)
    )
    fetched = {key: exchange_rate(key.currency, target, key.year) for key in needed}
    return {key: rate for key, rate in fetched.items() if rate is not None}


def _warn_skipped(
    library_id: str, target: CurrencyCode, skipped: list[ValuationInput]
) -> None:
    for facts in skipped:
        logger.warning(
            "[convert_library_prices]: library %s purchase %s not valued: "
            "no %s->%s rate for %s",
            library_id,
            facts.purchase_id,
            facts.currency,
            target,
            facts.rate_year,
        )


def _not_published(library_id: str, version: ConversionVersion, reason: str) -> None:
    logger.info(
        "[convert_library_prices]: library %s version %s not published: %s",
        library_id,
        version,
        reason,
    )


def _changed_since(
    library: UserLibrary, valuation_snapshot: list[ValuationInput]
) -> str | None:
    """What changed since the snapshot, if anything."""
    if valuation_inputs(library) != valuation_snapshot:
        return "purchases changed"
    return None


def _concise_error(error: Exception) -> str:
    return " ".join(str(error).split())[:MAX_ERROR_LENGTH]


def _mark_failed(
    library_id: str,
    requested_version: int,
    error: Exception,
    *,
    schedule_retry: bool = False,
    retry: bool = True,
) -> None:
    """Mark the version failed; a defect gets no retry."""
    retry_at = now() + RETRY_DELAY if retry else None
    library_pk = UUID(library_id)
    should_schedule = False
    with transaction.atomic():
        state = (
            PurchaseConversionState.objects.select_for_update()
            .filter(library_id=library_pk)
            .first()
        )
        if (
            state is None
            or state.requested_version != requested_version
            or state.published_version >= requested_version
        ):
            return
        should_schedule = schedule_retry and state.retry_at is None
        state.status = PurchaseConversionState.Status.FAILED
        state.retry_at = retry_at
        state.last_error = _concise_error(error)
        state.save(update_fields=["status", "retry_at", "last_error"])

    if retry_at is not None and should_schedule:
        schedule(
            "games.tasks.convert_library_prices",
            library_id,
            requested_version,
            schedule_type=Schedule.ONCE,
            next_run=retry_at,
            name=f"Retry price conversion {library_id} v{requested_version}",
        )


def convert_library_prices(library_id: str, requested_version: int) -> None:
    """Value the snapshot; publish if current."""
    library_pk = UUID(library_id)
    with transaction.atomic():
        state = (
            PurchaseConversionState.objects.select_for_update()
            .filter(library_id=library_pk)
            .first()
        )
        if (
            state is None
            or state.requested_version != requested_version
            or state.published_version >= requested_version
        ):
            return
        target_currency = state.requested_currency.upper()
        schedule_retry = state.retry_at is None
        state.status = PurchaseConversionState.Status.RUNNING
        state.last_error = ""
        state.save(update_fields=["status", "last_error"])

    try:
        library = UserLibrary.objects.get(pk=library_pk)
        valuation_snapshot = valuation_inputs(library)
        rates = _rates_for(valuation_snapshot, target_currency)
        with transaction.atomic():
            state = PurchaseConversionState.objects.select_for_update().get(
                library_id=library_pk
            )
            if (
                state.requested_version != requested_version
                or state.requested_currency.upper() != target_currency
                or state.published_version >= requested_version
            ):
                _not_published(library_id, requested_version, "superseded")
                return
            changed = _changed_since(library, valuation_snapshot)
            if changed is not None:
                # A removal requests nothing; request here.
                _request_conversion_for_locked_state(state, state.requested_currency)
                _not_published(library_id, requested_version, changed)
                return
            valuations = value_all(
                valuation_snapshot,
                rates,
                target_currency,
                library=library,
                version=requested_version,
                calculated_at=now(),
            )
            publish_valuations(library, valuations.rows)
            _warn_skipped(library_id, target_currency, valuations.skipped)
            state.published_version = requested_version
            state.published_currency = target_currency
            state.status = PurchaseConversionState.Status.COMPLETE
            state.retry_at = None
            state.last_error = ""
            state.save(
                update_fields=[
                    "published_version",
                    "published_currency",
                    "status",
                    "retry_at",
                    "last_error",
                ]
            )
    except (DatabaseError, RateFetchFailed) as error:
        logger.exception(
            "[convert_library_prices]: conversion failed for library %s version %s",
            library_id,
            requested_version,
        )
        _mark_failed(
            library_id,
            requested_version,
            error,
            schedule_retry=schedule_retry,
        )
    except Exception as error:
        logger.exception(
            "[convert_library_prices]: defect in library %s version %s; not retried",
            library_id,
            requested_version,
        )
        _mark_failed(library_id, requested_version, error, retry=False)


def recover_library_price_conversions() -> None:
    """Enqueue due runs; request stale libraries."""
    stale = PurchaseConversionState.objects.filter(
        requested_version__gt=F("published_version")
    ).filter(
        Q(
            status__in=(
                PurchaseConversionState.Status.PENDING,
                PurchaseConversionState.Status.RUNNING,
            )
        )
        | Q(status=PurchaseConversionState.Status.FAILED, retry_at__lte=now())
    )
    for state in stale:
        # Isolate each library's failure.
        try:
            async_task(
                "games.tasks.convert_library_prices",
                str(state.library_id),
                state.requested_version,
            )
        except Exception:
            logger.exception(
                "[recover]: enqueue failed for library %s", state.library_id
            )
    at_rest = PurchaseConversionState.objects.filter(
        requested_version=F("published_version")
    ).select_related("library")
    for state in at_rest:
        if len(state.requested_currency) != 3:
            logger.warning(
                "[recover]: library %s states no target currency; skipped",
                state.library_id,
            )
            continue
        try:
            stale_count = stale_purchases(state.library).count()
            if stale_count:
                logger.info(
                    "[recover]: library %s has %s stale purchase(s); requesting",
                    state.library_id,
                    stale_count,
                )
                request_revaluation(state.library)
        except Exception:
            logger.exception(
                "[recover]: revaluation request failed for library %s",
                state.library_id,
            )


def convert_prices() -> None:
    """Compatibility entry point: request current targets for every library."""
    from games.conversion import request_conversion
    from timetracker.settings_resolver import resolve_for_user_with_origin

    for library in UserLibrary.objects.select_related("user"):
        target = resolve_for_user_with_origin(
            library.user, "DEFAULT_DISPLAY_CURRENCY"
        ).value
        request_conversion(library, str(target))
