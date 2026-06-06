"""Python builder for the stats page body (replaces stats.html).

Both stats views (`stats_alltime`-style and per-year) assemble a `context`
dict and pass it here. Optional sections are driven by `ctx.get(...)` exactly
like the old `{% if key %}` blocks: a missing or empty value hides the section.
"""

from django.template.defaultfilters import date as date_filter
from django.template.defaultfilters import floatformat
from django.utils.html import conditional_escape
from django.utils.safestring import SafeText, mark_safe

from common.components import Component, Div, GameLink
from common.time import durationformat, format_duration

_CELL = "px-2 sm:px-4 md:px-6 md:py-2"
_CELL_MONO = f"{_CELL} font-mono"
_NAME_TH = f"{_CELL} purchase-name truncate max-w-20char"


def _td(children, cls: str = _CELL_MONO) -> SafeText:
    if not isinstance(children, list):
        children = [children]
    children = [c if isinstance(c, (str, SafeText)) else str(c) for c in children]
    return Component(tag_name="td", attributes=[("class", cls)], children=children)


def _th(text: str, cls: str = _CELL) -> SafeText:
    return Component(tag_name="th", attributes=[("class", cls)], children=[text])


def _tr(cells: list) -> SafeText:
    return Component(tag_name="tr", children=cells)


def _kv(label, value) -> SafeText:
    """A label/value row: plain label cell + mono value cell."""
    return _tr([_td(label, _CELL), _td(value)])


def _h1(title: str) -> SafeText:
    return Component(
        tag_name="h1",
        attributes=[("class", "text-5xl text-center my-6")],
        children=[title],
    )


def _table(rows: list, thead: SafeText | None = None) -> SafeText:
    children = []
    if thead is not None:
        children.append(thead)
    children.append(Component(tag_name="tbody", children=rows))
    return Component(
        tag_name="table",
        attributes=[("class", "responsive-table")],
        children=children,
    )


def _dur(value) -> str:
    return format_duration(value, durationformat)


def _purchase_name(purchase) -> SafeText:
    """Mirror of the `purchase-name` partial in the old template."""
    game_name = getattr(purchase, "game_name", None)
    first_game = purchase.first_game
    if purchase.type != "game":
        name = game_name or purchase.name
        link = GameLink(first_game.id, name)
        suffix = f" ({first_game.name} {purchase.get_type_display()})"
        return mark_safe(str(link) + conditional_escape(suffix))
    name = game_name or first_game.name
    return GameLink(first_game.id, name)


def _year_dropdown(year, year_range) -> SafeText:
    options = []
    for year_item in year_range or []:
        attrs = [("value", str(year_item))]
        if year == year_item:
            attrs.append(("selected", True))
        options.append(
            Component(tag_name="option", attributes=attrs, children=[str(year_item)])
        )
    select = Component(
        tag_name="select",
        attributes=[
            ("name", "year"),
            ("id", "yearSelect"),
            ("onchange", "this.form.submit();"),
            ("class", "mx-2"),
        ],
        children=options,
    )
    label = Component(
        tag_name="label",
        attributes=[
            ("class", "text-5xl text-center inline-block mb-10"),
            ("for", "yearSelect"),
        ],
        children=["Stats for:"],
    )
    form = Component(
        tag_name="form",
        attributes=[("method", "get"), ("class", "text-center")],
        children=[label, select],
    )
    return Div([("class", "flex justify-center items-center")], [form])


def _playtime_table(ctx) -> SafeText:
    year = ctx.get("year")
    rows = [
        _kv("Hours", ctx.get("total_hours")),
        _kv("Sessions", ctx.get("total_sessions")),
        _kv(
            "Days",
            f"{ctx.get('unique_days')} ({ctx.get('unique_days_percent')}%)",
        ),
    ]
    if ctx.get("total_games"):
        rows.append(_kv("Games", ctx.get("total_games")))
    rows.append(_kv(f"Games ({year})", ctx.get("total_year_games")))
    if ctx.get("all_finished_this_year_count"):
        rows.append(_kv("Finished", ctx.get("all_finished_this_year_count")))
    rows.append(
        _kv(f"Finished ({year})", ctx.get("this_year_finished_this_year_count"))
    )

    def _game_row(label, value, game):
        return _tr(
            [
                _td(label, _CELL),
                _td([str(value), " (", GameLink(game.id, game.name), ")"]),
            ]
        )

    longest_game = ctx.get("longest_session_game")
    if longest_game and longest_game.id:
        rows.append(
            _game_row("Longest session", ctx.get("longest_session_time"), longest_game)
        )
    most_sessions_game = ctx.get("highest_session_count_game")
    if most_sessions_game and most_sessions_game.id:
        rows.append(
            _game_row(
                "Most sessions", ctx.get("highest_session_count"), most_sessions_game
            )
        )
    avg_game = ctx.get("highest_session_average_game")
    if avg_game and avg_game.id:
        rows.append(
            _game_row(
                "Highest session average", ctx.get("highest_session_average"), avg_game
            )
        )
    first_game = ctx.get("first_play_game")
    if first_game and first_game.id:
        rows.append(
            _tr(
                [
                    _td("First play", _CELL),
                    _td(
                        [
                            GameLink(first_game.id, first_game.name),
                            f" ({ctx.get('first_play_date')})",
                        ]
                    ),
                ]
            )
        )
    last_game = ctx.get("last_play_game")
    if last_game and last_game.id:
        rows.append(
            _tr(
                [
                    _td("Last play", _CELL),
                    _td(
                        [
                            GameLink(last_game.id, last_game.name),
                            f" ({ctx.get('last_play_date')})",
                        ]
                    ),
                ]
            )
        )
    return _table(rows)


def _purchases_table(ctx) -> SafeText:
    rows = [
        _kv("Total", ctx.get("all_purchased_this_year_count")),
        _kv(
            "Refunded",
            f"{ctx.get('all_purchased_refunded_this_year_count')} "
            f"({ctx.get('refunded_percent')}%)",
        ),
        _kv(
            "Dropped",
            f"{ctx.get('dropped_count')} ({ctx.get('dropped_percentage')}%)",
        ),
        _kv(
            "Unfinished",
            f"{ctx.get('purchased_unfinished_count')} "
            f"({ctx.get('unfinished_purchases_percent')}%)",
        ),
        _kv("Backlog Decrease", ctx.get("backlog_decrease_count")),
        _kv(
            f"Spendings ({ctx.get('total_spent_currency')})",
            f"{floatformat(ctx.get('total_spent'))} "
            f"({floatformat(ctx.get('spent_per_game'))}/game)",
        ),
    ]
    return _table(rows)


def _two_col_table(header: str, items, name_key, value_fn) -> SafeText:
    thead = Component(
        tag_name="thead",
        children=[_tr([_th(header), _th("Playtime")])],
    )
    rows = [_tr([_td(name_key(item)), _td(value_fn(item))]) for item in items]
    return _table(rows, thead)


def _finished_table(purchases) -> SafeText:
    thead = Component(
        tag_name="thead",
        children=[_tr([_th("Name", _NAME_TH), _th("Date")])],
    )
    rows = [
        _tr([_td(_purchase_name(p)), _td(date_filter(p.date_finished, "d/m/Y"))])
        for p in purchases
    ]
    return _table(rows, thead)


def _priced_table(purchases, currency) -> SafeText:
    thead = Component(
        tag_name="thead",
        children=[
            _tr([_th("Name", _NAME_TH), _th(f"Price ({currency})"), _th("Date")])
        ],
    )
    rows = [
        _tr(
            [
                _td(_purchase_name(p)),
                _td(floatformat(p.converted_price)),
                _td(date_filter(p.date_purchased, "d/m/Y")),
            ]
        )
        for p in purchases
    ]
    return _table(rows, thead)


def stats_content(ctx: dict) -> SafeText:
    year = ctx.get("year")
    currency = ctx.get("total_spent_currency")
    sections: list = [
        _year_dropdown(year, ctx.get("stats_dropdown_year_range")),
        _h1("Playtime"),
        _playtime_table(ctx),
    ]

    months = list(ctx.get("month_playtimes") or [])
    if months:
        sections.append(_h1("Playtime per month"))
        month_rows = [
            _kv(date_filter(m["month"], "F"), _dur(m["playtime"])) for m in months
        ]
        sections.append(_table(month_rows))

    sections += [
        _h1("Purchases"),
        _purchases_table(ctx),
        _h1("Games by playtime"),
        _two_col_table(
            "Name",
            ctx.get("top_10_games_by_playtime") or [],
            lambda g: GameLink(g.id, g.name),
            lambda g: _dur(g.total_playtime),
        ),
        _h1("Platforms by playtime"),
        _two_col_table(
            "Platform",
            ctx.get("total_playtime_per_platform") or [],
            lambda item: item["platform_name"],
            lambda item: _dur(item["playtime"]),
        ),
    ]

    all_finished = list(ctx.get("all_finished_this_year") or [])
    if all_finished:
        sections += [_h1("Finished"), _finished_table(all_finished)]

    year_finished = list(ctx.get("this_year_finished_this_year") or [])
    if year_finished:
        sections += [_h1(f"Finished ({year} games)"), _finished_table(year_finished)]

    bought_finished = list(ctx.get("purchased_this_year_finished_this_year") or [])
    if bought_finished:
        sections += [
            _h1(f"Bought and Finished ({year})"),
            _finished_table(bought_finished),
        ]

    unfinished = list(ctx.get("purchased_unfinished") or [])
    if unfinished:
        sections += [
            _h1("Unfinished Purchases"),
            _priced_table(unfinished, currency),
        ]

    all_purchased = list(ctx.get("all_purchased_this_year") or [])
    if all_purchased:
        sections += [_h1("All Purchases"), _priced_table(all_purchased, currency)]

    return Div(
        [("class", "dark:text-white max-w-sm sm:max-w-xl lg:max-w-3xl mx-auto")],
        sections,
    )
