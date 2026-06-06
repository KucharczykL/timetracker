"""Stash-style filter bars and the SelectableFilter widget."""

from django.db import models
from django.utils.html import escape
from django.utils.safestring import SafeText, mark_safe

from common.components.core import Component


_FILTER_LABEL_CLASS = "text-xs font-medium text-body uppercase tracking-wide"


_FILTER_INPUT_CLASS = (
    "block w-full rounded-base border border-default-medium "
    "bg-neutral-secondary-medium text-sm text-heading p-2 "
    "focus:ring-brand focus:border-brand"
)


_FILTER_CHECKBOX_CLASS = (
    "rounded border-default-medium bg-neutral-secondary-medium "
    "text-brand focus:ring-brand"
)


_FILTER_GRID_CLASS = "grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-4"


def _filter_parse(filter_json: str) -> dict:
    if not filter_json:
        return {}
    try:
        import json

        loaded = json.loads(filter_json)
        return loaded if isinstance(loaded, dict) else {}
    except (ValueError, TypeError):
        return {}


def _filter_get_choice(existing: dict, field: str) -> tuple[list[str], list[str], str]:
    raw = existing.get(field, {})
    if not isinstance(raw, dict):
        return [], [], ""
    val = raw.get("value", [])
    excl = raw.get("excludes", [])
    mod = raw.get("modifier", "")
    if isinstance(val, str):
        val = [val]
    if isinstance(excl, str):
        excl = [excl]
    return [str(v) for v in (val or [])], [str(v) for v in (excl or [])], mod or ""


def _filter_mins_to_hrs(val) -> str:
    if val is None or val == "" or val == 0:
        return ""
    try:
        mins = int(val)
    except (TypeError, ValueError):
        return ""
    if mins == 0:
        return ""
    hrs = mins / 60
    return str(int(hrs)) if hrs == int(hrs) else f"{hrs:.1f}"


def _filter_field(label: str, widget) -> SafeText:
    """A labelled filter field: <div><label>…</label>{widget}</div>."""
    return Component(
        tag_name="div",
        attributes=[("class", "flex flex-col gap-1")],
        children=[
            Component(
                tag_name="label",
                attributes=[("class", _FILTER_LABEL_CLASS)],
                children=[label],
            ),
            widget,
        ],
    )


def _filter_number(label, name, value="", placeholder="") -> SafeText:
    return _filter_field(
        label,
        Component(
            tag_name="input",
            attributes=[
                ("type", "number"),
                ("name", escape(name)),
                ("id", escape(name)),
                ("value", escape(value)),
                ("placeholder", escape(placeholder)),
                ("class", _FILTER_INPUT_CLASS),
            ],
        ),
    )


def _filter_checkbox(name: str, label: str, checked: bool) -> SafeText:
    return Component(
        tag_name="label",
        attributes=[("class", "flex items-center gap-2 text-sm text-heading")],
        children=[
            Component(
                tag_name="input",
                attributes=[
                    ("type", "checkbox"),
                    ("name", name),
                    ("value", "1"),
                    *([("checked", "true")] if checked else []),
                    ("class", _FILTER_CHECKBOX_CLASS),
                ],
            ),
            label,
        ],
    )


def _filter_range_inputs(cls, min_id, max_id, min_v, max_v, dmin, dmax, step="1"):
    """Twin <input type=range> slider (used by the game filter bar)."""
    mv = min_v or str(dmin)
    xv = max_v or str(dmax)
    return Component(
        tag_name="div",
        attributes=[("class", f"range-slider {cls} relative h-6 mt-1 mb-2")],
        children=[
            mark_safe(
                f'<input type="range" class="range-min absolute w-full pointer-events-none '
                f"appearance-none bg-transparent h-2 "
                f"[&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:h-4 "
                f"[&::-webkit-slider-thumb]:w-4 [&::-webkit-slider-thumb]:rounded-full "
                f"[&::-webkit-slider-thumb]:bg-brand [&::-webkit-slider-thumb]:cursor-pointer "
                f'[&::-webkit-slider-thumb]:relative [&::-webkit-slider-thumb]:z-10" '
                f'data-target="{min_id}" data-peer="{max_id}" '
                f'min="{dmin}" max="{dmax}" value="{mv}" step="{step}">'
                f'<input type="range" class="range-max absolute w-full pointer-events-none '
                f"appearance-none bg-transparent h-2 "
                f"[&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:h-4 "
                f"[&::-webkit-slider-thumb]:w-4 [&::-webkit-slider-thumb]:rounded-full "
                f"[&::-webkit-slider-thumb]:bg-brand [&::-webkit-slider-thumb]:cursor-pointer "
                f'[&::-webkit-slider-thumb]:relative [&::-webkit-slider-thumb]:z-20" '
                f'data-target="{max_id}" data-peer="{min_id}" '
                f'min="{dmin}" max="{dmax}" value="{xv}" step="{step}">'
            ),
        ],
    )


def _filter_range_handles(cls, min_id, max_id, lo, hi, step="1"):
    """Handle-based slider (used by the session & purchase filter bars)."""
    return Component(
        tag_name="div",
        attributes=[
            ("class", f"range-slider {cls} relative h-10 mt-1 mb-2 select-none"),
            ("data-min", str(lo)),
            ("data-max", str(hi)),
            ("data-step", str(step)),
        ],
        children=[
            mark_safe(
                '<div class="absolute top-1/2 -translate-y-1/2 w-full h-2 rounded-full bg-neutral-secondary-medium border border-default-medium"></div><div class="range-track-fill absolute top-1/2 -translate-y-1/2 h-2 bg-brand rounded-full" style="left:0;width:100%"></div>'
                + f'<div class="range-handle-min absolute top-1/2 -translate-y-1/2 w-5 h-5 bg-brand rounded-full border-2 border-white shadow cursor-pointer hover:scale-110 transition-transform" data-target="{min_id}" style="left:0"></div><div class="range-handle-max absolute top-1/2 -translate-y-1/2 w-5 h-5 bg-brand rounded-full border-2 border-white shadow cursor-pointer hover:scale-110 transition-transform" data-target="{max_id}" style="left:100%"></div>'
            ),
        ],
    )


_FILTER_FORM_ID = "filter-bar-form"


_FILTER_INPUT_ID = "filter-json-input"


def _filter_collapse_button() -> SafeText:
    return Component(
        tag_name="button",
        attributes=[
            ("type", "button"),
            (
                "onclick",
                "var b=document.getElementById('filter-bar-body');b.classList.toggle('hidden');if(!b.classList.contains('hidden')&&window.initRangeSliders)window.initRangeSliders()",
            ),
            (
                "class",
                "flex items-center gap-2 text-sm font-medium text-body "
                "hover:text-heading mb-2",
            ),
        ],
        children=[
            mark_safe(
                '<svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M10.5 6h9.75M10.5 6a1.5 1.5 0 1 1-3 0m3 0a1.5 1.5 0 1 0-3 0M3.75 6H7.5m3 12h9.75m-9.75 0a1.5 1.5 0 0 1-3 0m3 0a1.5 1.5 0 0 0-3 0m-3.75 0H7.5m9-6h3.75m-3.75 0a1.5 1.5 0 0 1-3 0m3 0a1.5 1.5 0 0 0-3 0m-9.75 0h9.75" /></svg>'
            ),
            "Filters",
        ],
    )


def _filter_action_row(preset_list_url: str, preset_save_url: str) -> SafeText:
    return Component(
        tag_name="div",
        attributes=[("class", "flex gap-3 items-center")],
        children=[
            Component(
                tag_name="button",
                attributes=[
                    ("type", "submit"),
                    (
                        "class",
                        "px-4 py-2 text-sm font-medium text-white bg-brand "
                        "rounded-lg hover:bg-brand-strong focus:ring-4 "
                        "focus:ring-brand-medium",
                    ),
                ],
                children=["Apply"],
            ),
            Component(
                tag_name="button",
                attributes=[
                    ("type", "button"),
                    (
                        "onclick",
                        f"clearFilterBar('{_FILTER_FORM_ID}', '{_FILTER_INPUT_ID}')",
                    ),
                    (
                        "class",
                        "px-4 py-2 text-sm font-medium text-gray-900 bg-white "
                        "border border-gray-200 rounded-lg hover:bg-gray-100 "
                        "dark:bg-gray-800 dark:border-gray-600 dark:text-gray-400 "
                        "dark:hover:bg-gray-700 dark:hover:text-white",
                    ),
                ],
                children=["Clear"],
            ),
            Component(
                tag_name="span",
                attributes=[
                    ("class", "flex gap-2 items-center"),
                    ("id", "save-preset-area"),
                ],
                children=[
                    Component(
                        tag_name="input",
                        attributes=[
                            ("type", "text"),
                            ("id", "preset-name-input"),
                            ("placeholder", "Preset name..."),
                            (
                                "class",
                                "hidden px-3 py-2 text-sm rounded-lg border "
                                "border-default-medium bg-neutral-secondary-medium "
                                "text-heading focus:ring-brand focus:border-brand",
                            ),
                        ],
                    ),
                    Component(
                        tag_name="button",
                        attributes=[
                            ("type", "button"),
                            ("id", "save-preset-btn"),
                            ("onclick", "showPresetNameInput()"),
                            (
                                "class",
                                "px-4 py-2 text-sm font-medium text-gray-900 "
                                "bg-white border border-gray-200 rounded-lg "
                                "hover:bg-gray-100 dark:bg-gray-800 "
                                "dark:border-gray-600 dark:text-gray-400 "
                                "dark:hover:bg-gray-700 dark:hover:text-white",
                            ),
                        ],
                        children=["Save Preset"],
                    ),
                    Component(
                        tag_name="button",
                        attributes=[
                            ("type", "button"),
                            ("id", "confirm-save-preset-btn"),
                            (
                                "onclick",
                                f"savePreset('{_FILTER_FORM_ID}', '{_FILTER_INPUT_ID}', '{preset_save_url}')",
                            ),
                            (
                                "class",
                                "hidden px-4 py-2 text-sm font-medium text-white "
                                "bg-green-700 rounded-lg hover:bg-green-800 "
                                "focus:ring-4 focus:ring-green-300",
                            ),
                        ],
                        children=["Save"],
                    ),
                ],
            ),
            Component(
                tag_name="div",
                attributes=[
                    ("id", "preset-dropdown"),
                    ("class", "relative"),
                    ("data-preset-list-url", preset_list_url),
                ],
                children=[
                    Component(
                        tag_name="span",
                        attributes=[("class", "text-sm text-body")],
                        children=["Loading presets..."],
                    ),
                ],
            ),
        ],
    )


def _filter_bar(fields, filter_json, preset_list_url, preset_save_url) -> SafeText:
    """Shared collapsible filter-bar chrome. `fields` is the per-entity body
    (grids, sliders, checkboxes); the shell adds the collapse toggle, the form,
    the hidden filter-json input and the Apply/Clear/preset action row."""
    return Component(
        tag_name="div",
        attributes=[("id", "filter-bar"), ("class", "mb-6")],
        children=[
            _filter_collapse_button(),
            Component(
                tag_name="div",
                attributes=[
                    ("id", "filter-bar-body"),
                    (
                        "class",
                        "hidden border border-default-medium rounded-base p-4 "
                        "bg-neutral-secondary-medium/50",
                    ),
                ],
                children=[
                    Component(
                        tag_name="form",
                        attributes=[
                            ("id", _FILTER_FORM_ID),
                            ("onsubmit", "return applyFilterBar(event)"),
                        ],
                        children=[
                            Component(
                                tag_name="input",
                                attributes=[
                                    ("type", "hidden"),
                                    ("id", _FILTER_INPUT_ID),
                                    ("name", "filter"),
                                    # NB: Component escapes attribute values, so the
                                    # raw JSON is passed through (no double-escape).
                                    ("value", filter_json),
                                ],
                            ),
                            *fields,
                            _filter_action_row(preset_list_url, preset_save_url),
                        ],
                    ),
                ],
            ),
        ],
    )


def FilterBar(
    filter_json: str = "",
    status_options: list[tuple[str, str]] | None = None,
    platform_options: list[tuple[int, str]] | None = None,
    preset_list_url: str = "",
    preset_save_url: str = "",
) -> SafeText:
    """Collapsible filter bar for the Game list."""
    from games.models import Game, Platform

    if status_options is None:
        status_options = [(s.value, s.label) for s in Game.Status]
    if platform_options is None:
        platform_options = list(
            Platform.objects.order_by("name").values_list("id", "name")
        )

    existing = _filter_parse(filter_json)
    status_sel, status_excl, status_mod = _filter_get_choice(existing, "status")
    plat_sel, plat_excl, plat_mod = _filter_get_choice(existing, "platform")
    plat_opts_str = [(str(k), v) for k, v in platform_options]

    year_rel = existing.get("year_released", {})
    year_min = str(year_rel.get("value", "")) if isinstance(year_rel, dict) else ""
    year_max = str(year_rel.get("value2", "")) if isinstance(year_rel, dict) else ""
    mastered_val = (
        existing.get("mastered", {}).get("value", False)
        if isinstance(existing.get("mastered"), dict)
        else False
    )
    playtime = existing.get("playtime_minutes", {})
    playtime_min = (
        _filter_mins_to_hrs(playtime.get("value", ""))
        if isinstance(playtime, dict)
        else ""
    )
    playtime_max = (
        _filter_mins_to_hrs(playtime.get("value2", ""))
        if isinstance(playtime, dict)
        else ""
    )

    try:
        year_agg = Game.objects.aggregate(
            yr_min=models.Min("year_released"), yr_max=models.Max("year_released")
        )
    except Exception:
        year_agg = {}
    try:
        pt_agg = Game.objects.aggregate(pt_max=models.Max("playtime"))
    except Exception:
        pt_agg = {}
    yr_data_min = max(int(year_agg.get("yr_min") or 1970), 1970)
    yr_data_max = min(int(year_agg.get("yr_max") or 2030), 2030)
    pt_data_max = (
        int((pt_agg.get("pt_max") or 0).total_seconds() / 3600)
        if pt_agg.get("pt_max")
        else 200
    )

    fields = [
        Component(
            tag_name="div",
            attributes=[("class", _FILTER_GRID_CLASS)],
            children=[
                _filter_field(
                    "Status",
                    SelectableFilter(
                        "status",
                        status_options,
                        status_sel,
                        status_excl,
                        status_mod,
                        nullable=not Game._meta.get_field("status").has_default(),
                    ),
                ),
                _filter_field(
                    "Platform",
                    SelectableFilter(
                        "platform",
                        plat_opts_str,
                        plat_sel,
                        plat_excl,
                        plat_mod,
                        nullable=Game._meta.get_field("platform").null,
                    ),
                ),
                _filter_number("Year Min", "filter-year-min", year_min, "e.g. 2020"),
                _filter_number("Year Max", "filter-year-max", year_max, "e.g. 2024"),
            ],
        ),
        _filter_range_inputs(
            "year-range",
            "filter-year-min",
            "filter-year-max",
            year_min,
            year_max,
            yr_data_min,
            yr_data_max,
        ),
        Component(
            tag_name="div",
            attributes=[("class", _FILTER_GRID_CLASS)],
            children=[
                _filter_number(
                    "Playtime Min (hrs)", "filter-playtime-min", playtime_min, "e.g. 1"
                ),
                _filter_number(
                    "Playtime Max (hrs)",
                    "filter-playtime-max",
                    playtime_max,
                    "e.g. 100",
                ),
                Component(
                    tag_name="div",
                    attributes=[("class", "flex items-end pb-1")],
                    children=[
                        _filter_checkbox("filter-mastered", "Mastered", mastered_val)
                    ],
                ),
            ],
        ),
        _filter_range_inputs(
            "playtime-range",
            "filter-playtime-min",
            "filter-playtime-max",
            playtime_min or "0",
            playtime_max or str(pt_data_max),
            0,
            pt_data_max,
        ),
    ]
    return _filter_bar(fields, filter_json, preset_list_url, preset_save_url)


def SelectableFilter(
    field_name: str,
    options: list[tuple[str, str]],
    selected: list[str] | None = None,
    excluded: list[str] | None = None,
    modifier: str = "",
    nullable: bool = True,
) -> "SafeText":
    """Stash-style selectable filter with search, include/exclude, modifier tags."""
    selected = selected or []
    excluded = excluded or []

    active_mod_html = ""
    inactive_mod_html = ""
    mod_opts = [("NOT_NULL", "(Any)")]
    if nullable:
        mod_opts.append(("IS_NULL", "(None)"))
    for mod_val, mod_label in mod_opts:
        if modifier == mod_val:
            active_mod_html = (
                f'<span class="sf-modifier-tag active" data-modifier="{mod_val}">'
                f"{mod_label}</span> "
            )
        else:
            inactive_mod_html += (
                f'<div class="sf-option sf-modifier-option" data-modifier="{mod_val}" '
                f'data-label="{mod_label}">'
                f'<span class="sf-option-label">{mod_label}</span></div>'
            )

    selected_html = ""
    for val in selected:
        label = _find_label(options, val)
        selected_html += (
            f'<span class="sf-tag" data-value="{escape(val)}" data-type="include">'
            f'<span class="sf-tag-text text-body">\u2713 {escape(label)}</span>'
            f'<button type="button" class="sf-remove">\u00d7</button></span> '
        )
    for val in excluded:
        label = _find_label(options, val)
        selected_html += (
            f'<span class="sf-tag sf-excluded" data-value="{escape(val)}" data-type="exclude">'
            f'<span class="sf-tag-text text-body">\u2717 {escape(label)}</span>'
            f'<button type="button" class="sf-remove">\u00d7</button></span> '
        )

    options_html = ""
    for val, label in options:
        options_html += (
            f'<div class="sf-option" data-value="{escape(val)}" data-label="{escape(label)}">'
            f'<span class="sf-option-label">{escape(label)}</span>'
            f'<span class="sf-option-buttons">'
            f'<button type="button" class="sf-btn-include" data-action="include" title="Include">+</button>'
            f'<button type="button" class="sf-btn-exclude" data-action="exclude" title="Exclude">\u2212</button>'
            f"</span></div>"
        )

    return Component(
        tag_name="div",
        attributes=[
            (
                "class",
                "sf-container border border-default-medium rounded-base bg-neutral-secondary-medium",
            ),
            ("data-selectable-filter", field_name),
            *([("data-modifier", modifier)] if modifier else []),
        ],
        children=[
            Component(
                tag_name="div",
                attributes=[
                    ("class", "sf-selected flex flex-wrap gap-1 p-2 min-h-[28px]"),
                ],
                children=[mark_safe(active_mod_html + selected_html)],
            ),
            Component(
                tag_name="input",
                attributes=[
                    ("type", "text"),
                    (
                        "class",
                        "sf-search block w-full border-0 border-t border-default-medium "
                        "bg-transparent text-sm text-heading p-2 focus:ring-0 focus:outline-hidden",
                    ),
                    ("placeholder", "Search\u2026"),
                ],
            ),
            Component(
                tag_name="div",
                attributes=[
                    ("class", "sf-options max-h-40 overflow-y-auto p-1 text-body"),
                ],
                children=[mark_safe(inactive_mod_html + options_html)],
            ),
        ],
    )


def _find_label(options: list[tuple[str, str]], value: str) -> str:
    for v, label in options:
        if str(v) == str(value):
            return label
    return value


def SessionFilterBar(
    filter_json="", preset_list_url="", preset_save_url=""
) -> SafeText:
    """Collapsible filter bar for the Session list."""
    from games.models import Device, Game, Session

    game_opts = [
        (str(k), v) for k, v in Game.objects.order_by("name").values_list("id", "name")
    ]
    dev_opts = [
        (str(k), v)
        for k, v in Device.objects.order_by("name").values_list("id", "name")
    ]
    existing = _filter_parse(filter_json)
    gs, ge, gm = _filter_get_choice(existing, "game")
    ds, de, dm = _filter_get_choice(existing, "device")

    dur = existing.get("duration_minutes", {})
    dmin = _filter_mins_to_hrs(dur.get("value", "")) if isinstance(dur, dict) else ""
    dmax = _filter_mins_to_hrs(dur.get("value2", "")) if isinstance(dur, dict) else ""
    em = (
        existing.get("emulated", {}).get("value", False)
        if isinstance(existing.get("emulated"), dict)
        else False
    )
    ac = (
        existing.get("is_active", {}).get("value", False)
        if isinstance(existing.get("is_active"), dict)
        else False
    )
    try:
        a = Session.objects.aggregate(m=models.Max("duration_total"))
        ddm = max(
            int((a.get("m") or 0).total_seconds() / 3600) if a.get("m") else 200, 1
        )
    except Exception:
        ddm = 200

    fields = [
        Component(
            tag_name="div",
            attributes=[("class", _FILTER_GRID_CLASS)],
            children=[
                _filter_field(
                    "Game",
                    SelectableFilter(
                        "game",
                        game_opts,
                        gs,
                        ge,
                        gm,
                        nullable=not Game._meta.get_field("name").has_default(),
                    ),
                ),
                _filter_field(
                    "Device",
                    SelectableFilter(
                        "device",
                        dev_opts,
                        ds,
                        de,
                        dm,
                        nullable=Session._meta.get_field("device").null,
                    ),
                ),
                _filter_number(
                    "Duration Min (hrs)", "filter-playtime-min", dmin, "e.g. 0.5"
                ),
                _filter_number(
                    "Duration Max (hrs)", "filter-playtime-max", dmax, "e.g. 10"
                ),
            ],
        ),
        _filter_range_handles(
            "dur-range", "filter-playtime-min", "filter-playtime-max", 0, ddm
        ),
        Component(
            tag_name="div",
            attributes=[("class", "flex gap-4 mb-4")],
            children=[
                _filter_checkbox("filter-emulated", "Emulated", em),
                _filter_checkbox("filter-active", "Active", ac),
            ],
        ),
    ]
    return _filter_bar(fields, filter_json, preset_list_url, preset_save_url)


def PurchaseFilterBar(
    filter_json="", preset_list_url="", preset_save_url=""
) -> SafeText:
    """Collapsible filter bar for the Purchase list."""
    from games.models import Game, Platform, Purchase

    game_opts = [
        (str(k), v) for k, v in Game.objects.order_by("name").values_list("id", "name")
    ]
    plat_opts = [
        (str(k), v)
        for k, v in Platform.objects.order_by("name").values_list("id", "name")
    ]
    type_opts = [(t[0], t[1]) for t in Purchase.TYPES]
    own_opts = [(t[0], t[1]) for t in Purchase.OWNERSHIP_TYPES]
    existing = _filter_parse(filter_json)
    gs, ge, gm = _filter_get_choice(existing, "games")
    ps, pe, pm = _filter_get_choice(existing, "platform")
    ts, te, tm = _filter_get_choice(existing, "type")
    os_, oe, om = _filter_get_choice(existing, "ownership_type")
    price = existing.get("price", {})
    pmin = str(price.get("value", "")) if isinstance(price, dict) else ""
    pmax = str(price.get("value2", "")) if isinstance(price, dict) else ""
    rf = (
        existing.get("is_refunded", {}).get("value", False)
        if isinstance(existing.get("is_refunded"), dict)
        else False
    )
    try:
        a = Purchase.objects.aggregate(lo=models.Min("price"), hi=models.Max("price"))
        plo, phi = int(a.get("lo") or 0), max(int(a.get("hi") or 100), 1)
    except Exception:
        plo, phi = 0, 100

    fields = [
        Component(
            tag_name="div",
            attributes=[("class", _FILTER_GRID_CLASS)],
            children=[
                _filter_field(
                    "Game",
                    SelectableFilter("games", game_opts, gs, ge, gm, nullable=False),
                ),
                _filter_field(
                    "Platform",
                    SelectableFilter(
                        "platform",
                        plat_opts,
                        ps,
                        pe,
                        pm,
                        nullable=Purchase._meta.get_field("platform").null,
                    ),
                ),
                _filter_field(
                    "Type",
                    SelectableFilter(
                        "type",
                        type_opts,
                        ts,
                        te,
                        tm,
                        nullable=not Purchase._meta.get_field("type").has_default(),
                    ),
                ),
                _filter_field(
                    "Ownership",
                    SelectableFilter(
                        "ownership_type",
                        own_opts,
                        os_,
                        oe,
                        om,
                        nullable=not Purchase._meta.get_field(
                            "ownership_type"
                        ).has_default(),
                    ),
                ),
            ],
        ),
        Component(
            tag_name="div",
            attributes=[("class", _FILTER_GRID_CLASS)],
            children=[
                _filter_number("Price Min", "filter-price-min", pmin, "0.00"),
                _filter_number("Price Max", "filter-price-max", pmax, "100.00"),
                _filter_checkbox("filter-refunded", "Refunded", rf),
            ],
        ),
        _filter_range_handles(
            "price-range", "filter-price-min", "filter-price-max", plo, phi
        ),
    ]
    return _filter_bar(fields, filter_json, preset_list_url, preset_save_url)
