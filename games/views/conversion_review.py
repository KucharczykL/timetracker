"""The Library page's conversion review rows."""

from dataclasses import dataclass

from django.http import HttpRequest
from django.middleware.csrf import get_token

from common.components import (
    Fragment,
    LiveSettingFields,
    Node,
    SettingFieldState,
    SummaryAction,
    SummaryList,
    SummaryRow,
    SummaryValue,
)
from common.criteria import AggregateCriterion, ChoiceCriterion, Modifier
from common.filter_execution import execute_filter
from games.conversion_review import ORIGIN, REVIEW_WORDS, REVIEWED, ReviewTarget
from games.filters import (
    GameFilter,
    LibraryEntryFilter,
    PurchaseFilter,
    filter_query_context_for_library,
    filter_url,
)
from games.forms import ConversionReviewForm
from games.models import LibraryEvent, UserLibrary
from games.reads.entries import library_entries
from games.reads.games_list import games_list_base
from games.reads.purchases import library_purchases
from timetracker.settings_commands import SettingNamespace

REVIEW_SUBTITLE = "What converting your earlier purchases changed."
REPURCHASED = "Repurchased games"
REPURCHASED_REASON = "Games with two copies or more."


@dataclass(frozen=True, slots=True)
class ReviewRow:
    label: str
    reason: str
    count: int
    url: str


def converted(library: UserLibrary) -> bool:
    """The library holds a conversion event."""
    return LibraryEvent.objects.filter(
        library=library, source_metadata__origin=ORIGIN
    ).exists()


def conversion_review_rows(library: UserLibrary) -> tuple[ReviewRow, ...]:
    """Each category's rows; empty ones left out."""
    context = filter_query_context_for_library(library)
    rows: list[ReviewRow] = []
    for word in REVIEWED:
        words = REVIEW_WORDS[word]
        criterion = ChoiceCriterion(value=[str(word)], modifier=Modifier.INCLUDES)
        if words.target is ReviewTarget.PURCHASES:
            purchases = PurchaseFilter(conversion_review=criterion)
            count = execute_filter(
                purchases, library_purchases(library), context
            ).count()
            url = filter_url(purchases)
        else:
            entries = LibraryEntryFilter(conversion_review=criterion)
            count = execute_filter(entries, library_entries(library), context).count()
            url = filter_url(entries)
        if count:
            rows.append(ReviewRow(words.label, words.reason, count, url))
    repurchased = GameFilter(
        entry_count=AggregateCriterion(value=2, modifier=Modifier.GREATER_THAN_OR_EQUAL)
    )
    count = execute_filter(
        repurchased, games_list_base(library, repurchased), context
    ).count()
    if count:
        rows.append(
            ReviewRow(REPURCHASED, REPURCHASED_REASON, count, filter_url(repurchased))
        )
    return tuple(rows)


def ConversionReview(request: HttpRequest, library: UserLibrary) -> Node | None:
    """The review and its Hide control."""
    if not converted(library):
        return None
    hidden = library.preferences.conversion_review_hidden
    control = LiveSettingFields(
        ConversionReviewForm(hidden=hidden),
        states={
            "hidden": SettingFieldState(
                key="conversion-review-hidden",
                source="library",
                show_source=False,
            )
        },
        patch_url_template="/api/library/__key__",
        csrf=get_token(request),
        namespace=SettingNamespace.LIBRARY,
    )
    rows = () if hidden else conversion_review_rows(library)
    return SummaryRow(
        label="Conversion review",
        subtitle=REVIEW_SUBTITLE,
        detail=Fragment(
            control,
            SummaryList(
                *(
                    SummaryRow(
                        label=row.label,
                        subtitle=row.reason,
                        value=SummaryValue(row.count, row.url),
                        actions=(SummaryAction("Review", row.url),),
                        dense=True,
                    )
                    for row in rows
                )
            )
            if rows
            else None,
        ),
    )
