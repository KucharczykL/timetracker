"""TimeZoneRow: the per-timestamp "Time zone" row.

Composes pieces the quick-filter facets already use — a ghost
``ComboboxDropdown`` hosting a panel ``SearchSelect`` over
``/api/timezones/search`` — plus one hidden input that is the *only*
submitted channel (the picker's own input carries a ``_picker`` suffix the
server never reads). The trigger is always visible: one control per field, so
nothing double-announces and the picker is reachable even when the browser and
stored zones agree. The only ``hidden`` thing here is that input.
``ts/elements/time-zone-row.ts`` stamps the browser zone as the capture default
on unsaved records and emphasises the trigger when the zones disagree.
"""

from common.components.core import Media, Node
from common.components.custom_elements import _TimeZoneRow
from common.components.primitives import Div, Input
from common.components.search_select import ComboboxDropdown, SearchSelect

TIMEZONE_SEARCH_API_URL = "/api/timezones/search"


def TimeZoneRow(
    *,
    field_name: str,
    label: str,
    stored_zone: str,
    display_zone: str,
    capture_default: bool,
) -> Node:
    effective_label = stored_zone or f"{display_zone} (display zone)"
    picker = SearchSelect(
        name=f"{field_name}_picker",
        selected=(
            [{"value": stored_zone, "label": stored_zone, "data": {}}]
            if stored_zone
            else None
        ),
        search_url=TIMEZONE_SEARCH_API_URL,
        placeholder="Search time zones…",
        panel=True,
    )
    trigger = Div(class_="mt-1")[
        ComboboxDropdown(
            label=f"{label}: {effective_label}",
            content=picker,
            id=f"{field_name}-dropdown",
            ghost=True,
        )
    ]
    element = _TimeZoneRow(
        field_name=field_name,
        stored_zone=stored_zone,
        display_zone=display_zone,
        # A raw bool would vanish: _attrs_from_kwargs drops False and renders
        # True as the bare boolean form, while the generated reader compares
        # against the string "true".
        capture_default="true" if capture_default else "false",
        class_="block",
    )[
        Input(
            type="hidden",
            name=field_name,
            value=stored_zone,
            data_time_zone_value="",
        ),
        trigger,
    ]
    return element.with_media(Media(js=("dist/elements/time-zone-row.js",)))
