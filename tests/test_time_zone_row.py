"""TimeZoneRow component markup: the hidden submitted channel, the single
always-visible picker trigger, and the kebab-cased element props the TS reads."""

from common.components import TimeZoneRow
from common.components.core import collect_media


def _render(
    *,
    field_name: str = "timestamp_start_timezone",
    label: str = "Start time zone",
    stored_zone: str = "",
    display_zone: str = "Europe/Prague",
    capture_default: bool = True,
) -> str:
    return str(
        TimeZoneRow(
            field_name=field_name,
            label=label,
            stored_zone=stored_zone,
            display_zone=display_zone,
            capture_default=capture_default,
        )
    )


def test_renders_element_with_kebab_cased_props():
    html = _render(stored_zone="Asia/Tokyo", capture_default=False)
    assert "<time-zone-row" in html
    assert 'field-name="timestamp_start_timezone"' in html
    assert 'stored-zone="Asia/Tokyo"' in html
    assert 'display-zone="Europe/Prague"' in html
    assert 'capture-default="false"' in html


def test_hidden_input_is_the_submitted_channel():
    html = _render(stored_zone="Asia/Tokyo")
    assert 'name="timestamp_start_timezone"' in html
    assert "data-time-zone-value" in html
    assert 'value="Asia/Tokyo"' in html


def test_trigger_is_always_visible_with_a_ghost_style():
    """One control per field, never collapsed: a second control named after the
    same field double-announces, and a hidden trigger is unreachable in exactly
    the case a mismatch check cannot detect."""
    html = _render()
    # An htpy `hidden=True` renders as hidden="hidden" — the exact thing this
    # row must not contain. Asserting on the bare word would be wrong: the
    # submitted input is type="hidden", and the dropdown panel is stamped
    # hidden="" by the <drop-down> engine, which owns its visibility.
    assert 'hidden="hidden"' not in html
    assert 'aria-haspopup="dialog"' in html
    assert "bg-transparent" in html  # the ghost ControlButton variant
    # NULL renders the display-zone fallback in the trigger label.
    assert "Start time zone: Europe/Prague (display zone)" in html


def test_stored_zone_names_itself_in_the_trigger_label():
    assert "Start time zone: Asia/Tokyo" in _render(stored_zone="Asia/Tokyo")


def test_picker_searches_the_timezone_api_without_submitting_itself():
    html = _render()
    assert "/api/timezones/search" in html
    assert 'name="timestamp_start_timezone_picker"' in html


def test_declares_its_module_media():
    media = collect_media(
        TimeZoneRow(
            field_name="timestamp_start_timezone",
            label="Start time zone",
            stored_zone="",
            display_zone="Europe/Prague",
            capture_default=True,
        )
    )
    assert "dist/elements/time-zone-row.js" in media.js
