"""Every row, in a stated zone."""

from zoneinfo import ZoneInfo

from common.criteria import FilterQueryContext, with_filter_aliases


def unrestricted_filter_context(zone: ZoneInfo) -> FilterQueryContext:
    return FilterQueryContext(
        lambda model: with_filter_aliases(model._default_manager.all()),
        day_zone=lambda: zone,
    )
