"""Python builder for the stats page body (replaces stats.html).

Both stats views (`stats_alltime`-style and per-year) assemble a `context`
dict and pass it here. Optional sections are driven by `ctx.get(...)` exactly
like the old `{% if key %}` blocks: a missing or empty value hides the section.
"""

from django.template.defaultfilters import date as date_filter
from django.template.defaultfilters import floatformat
from django.urls import reverse
from django.utils.html import conditional_escape

from common.components import (
    CONTENT_MAX_WIDTH_CLASS,
    A,
    Div,
    Element,
    Fragment,
    GameLink,
    ICON_BUTTON_SIZE_CLASS,
    Icon,
    Node,
    Safe,
    Td,
    Th,
    Tr,
    YearPicker,
)
from common.time import durationformat, format_duration
from games.filters import filter_url
from games.views import stats_links
from games.views.stats_data import StatsData

_CELL = "px-2 sm:px-4 md:px-6 md:py-2"
_CELL_MONO = f"{_CELL} font-mono"
_NAME_TH = f"{_CELL} purchase-name truncate max-w-20char"

# Stats lists are previews: capped to this many rows, with a "View all" link to
# the full filtered list (#65).
_LIST_CAP = 5


def _session_link(game_id, year) -> Node:
    """Small affordance linking a game row to its (year-scoped) session list.
    Sits next to the existing GameLink (which goes to the game detail page)."""
    return A(
        href=filter_url(stats_links.sessions_for_game(game_id, year)),
        class_="ml-1 inline-block align-middle hover:text-heading",
        title="View sessions",
    )[Icon("play", size=ICON_BUTTON_SIZE_CLASS)]


def _count_link(value, url: str) -> Node:
    return A(href=url, class_="hover:underline decoration-dotted")[str(value)]


def _view_all_row(count: int, url: str) -> Node:
    return _tr(
        [
            Td(
                attributes=[("class", _CELL), ("colspan", "3")],
                children=[
                    A(href=url, class_="underline decoration-dotted")[
                        f"View all ({count}) →"
                    ]
                ],
            )
        ]
    )


def _td(children, cls: str = _CELL_MONO) -> Node:
    if not isinstance(children, list):
        children = [children]
    return Td(attributes=[("class", cls)], children=children)


def _th(text: str, cls: str = _CELL) -> Node:
    return Th(attributes=[("class", cls)], children=[text])


def _tr(cells: list) -> Node:
    return Tr(children=cells)


def _kv(label, value) -> Node:
    """A label/value row: plain label cell + mono value cell."""
    return _tr([_td(label, _CELL), _td(value)])


def _h1(title: str) -> Node:
    return Element(
        "h1",
        attributes=[("class", "text-3xl text-heading text-center my-6")],
        children=[title],
    )


def _table(rows: list, thead: Node | None = None) -> Node:
    children = []
    if thead is not None:
        children.append(thead)
    children.append(Element("tbody", children=rows))
    return Element(
        "table",
        attributes=[("class", "responsive-table")],
        children=children,
    )


def _dur(value) -> str:
    return format_duration(value, durationformat)


def _purchase_name(purchase) -> Node:
    """Mirror of the `purchase-name` partial in the old template."""
    game_name = getattr(purchase, "game_name", None)
    first_game = purchase.first_game
    if purchase.type != "game":
        name = game_name or purchase.name
        link = GameLink(first_game.id, name)
        suffix = f" ({first_game.name} {purchase.get_type_display()})"
        return Safe(str(link) + conditional_escape(suffix))
    name = game_name or first_game.name
    return GameLink(first_game.id, name)


def _year_nav(year, year_range, url_template) -> Node:
    # `year` is an int for a specific year, or "Alltime" (from compute_stats)
    # for the all-time view. Normalize to int-or-None so nothing downstream has
    # to know about the "Alltime" sentinel.
    year_int = year if isinstance(year, int) else None
    is_alltime = year_int is None

    alltime_classes = (
        "inline-flex items-center rounded-base px-4 py-2 mr-3 text-sm font-medium "
    )
    alltime_classes += (
        "bg-brand text-white hover:bg-brand-strong"
        if is_alltime
        else "text-body hover:text-heading underline decoration-dotted"
    )
    alltime_btn = A(
        href=reverse("games:stats_alltime"),
        class_=alltime_classes,
    )["All-time stats"]
    picker = YearPicker(
        year=year_int,
        available_years=tuple(year_range or []),
        url_template=url_template,
    )
    return Div(
        [("class", "flex justify-center items-center mb-12")],
        [alltime_btn, picker],
    )


def _playtime_table(ctx) -> Node:
    year = ctx.get("year")
    rows = [
        _kv("Hours", ctx.get("total_hours")),
        _kv(
            "Sessions",
            _count_link(
                ctx.get("total_sessions"),
                filter_url(stats_links.all_sessions(year)),
            ),
        ),
        _kv(
            "Days",
            f"{ctx.get('unique_days')} ({ctx.get('unique_days_percent')}%)",
        ),
    ]
    if ctx.get("total_games"):
        rows.append(
            _kv(
                "Games",
                _count_link(
                    ctx.get("total_games"),
                    filter_url(stats_links.games_played(year)),
                ),
            )
        )
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
                _td(
                    [
                        str(value),
                        " (",
                        GameLink(game.id, game.name),
                        ")",
                        _session_link(game.id, year),
                    ]
                ),
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
                            _session_link(first_game.id, year),
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
                            _session_link(last_game.id, year),
                        ]
                    ),
                ]
            )
        )
    return _table(rows)


def _purchases_table(ctx) -> Node:
    year = ctx.get("year")
    rows = [
        _kv(
            "Total",
            _count_link(
                ctx.get("all_purchased_this_year_count"),
                filter_url(stats_links.purchases_total(year)),
            ),
        ),
        _kv(
            "Refunded",
            _count_link(
                f"{ctx.get('all_purchased_refunded_this_year_count')} "
                f"({ctx.get('refunded_percent')}%)",
                filter_url(stats_links.purchases_refunded(year)),
            ),
        ),
        _kv(
            "Dropped",
            _count_link(
                f"{ctx.get('dropped_count')} ({ctx.get('dropped_percentage')}%)",
                filter_url(stats_links.purchases_dropped(year)),
            ),
        ),
        _kv(
            "Unfinished",
            _count_link(
                f"{ctx.get('purchased_unfinished_count')} "
                f"({ctx.get('unfinished_purchases_percent')}%)",
                filter_url(stats_links.purchases_unfinished(year)),
            ),
        ),
        _kv(
            "Backlog Decrease",
            _count_link(
                ctx.get("backlog_decrease_count"),
                filter_url(stats_links.purchases_backlog_decrease(year)),
            ),
        ),
        _kv(
            f"Spendings ({ctx.get('total_spent_currency')})",
            f"{floatformat(ctx.get('total_spent'))} "
            f"({floatformat(ctx.get('spent_per_game'))}/game)",
        ),
    ]
    return _table(rows)


def _two_col_table(header: str, items, name_key, value_fn, view_all_url=None) -> Node:
    thead = Element(
        "thead",
        children=[_tr([_th(header), _th("Playtime")])],
    )
    items = list(items)
    display = items[:_LIST_CAP] if view_all_url else items
    rows = [_tr([_td(name_key(item)), _td(value_fn(item))]) for item in display]
    if view_all_url and len(items) > _LIST_CAP:
        rows.append(_view_all_row(len(items), view_all_url))
    return _table(rows, thead)


def _finished_table(purchases, view_all_url=None, total=None) -> Node:
    thead = Element(
        "thead",
        children=[_tr([_th("Name", _NAME_TH), _th("Date")])],
    )
    purchases = list(purchases)
    display = purchases[:_LIST_CAP] if view_all_url else purchases
    rows = [
        _tr([_td(_purchase_name(p)), _td(date_filter(p.date_finished, "d/m/Y"))])
        for p in display
    ]
    total = total if total is not None else len(purchases)
    if view_all_url and total > _LIST_CAP:
        rows.append(_view_all_row(total, view_all_url))
    return _table(rows, thead)


def _priced_table(purchases, currency, view_all_url=None, total=None) -> Node:
    thead = Element(
        "thead",
        children=[
            _tr([_th("Name", _NAME_TH), _th(f"Price ({currency})"), _th("Date")])
        ],
    )
    purchases = list(purchases)
    display = purchases[:_LIST_CAP] if view_all_url else purchases
    rows = [
        _tr(
            [
                _td(_purchase_name(p)),
                _td(floatformat(p.converted_price)),
                _td(date_filter(p.date_purchased, "d/m/Y")),
            ]
        )
        for p in display
    ]
    total = total if total is not None else len(purchases)
    if view_all_url and total > _LIST_CAP:
        rows.append(_view_all_row(total, view_all_url))
    return _table(rows, thead)


def stats_content(ctx: StatsData) -> Node:
    year = ctx["year"]
    currency = ctx.get("total_spent_currency")
    # Build a navigation URL with an `__year__` placeholder the picker's JS
    # substitutes. Reverse a sentinel year, then swap it for the placeholder
    # (anchored on `stats/0` so the match is unambiguous).
    url_template = reverse("games:stats_by_year", args=[0]).replace(
        "stats/0", "stats/__year__"
    )
    sections: list = [
        _year_nav(year, ctx.get("stats_dropdown_year_range"), url_template),
        _h1("Playtime"),
        _playtime_table(ctx),
    ]

    months = list(ctx.get("month_playtimes") or [])
    if months:
        sections.append(_h1("Playtime per month"))
        month_rows = [
            _tr(
                [
                    _td(
                        A(
                            href=filter_url(
                                stats_links.sessions_in_month(year, m["month"].month)
                            ),
                            class_="hover:underline decoration-dotted",
                        )[date_filter(m["month"], "F")],
                        _CELL,
                    ),
                    _td(_dur(m["playtime"])),
                ]
            )
            for m in months
        ]
        sections.append(_table(month_rows))

    sections += [
        _h1("Purchases"),
        _purchases_table(ctx),
        _h1("Games by playtime"),
        _two_col_table(
            "Name",
            ctx.get("top_10_games_by_playtime") or [],
            lambda g: Fragment(GameLink(g.id, g.name), _session_link(g.id, year)),
            lambda g: _dur(g.total_playtime),
            view_all_url=filter_url(stats_links.games_played(year), sort="-playtime"),
        ),
        _h1("Platforms by playtime"),
        _two_col_table(
            "Platform",
            ctx.get("total_playtime_per_platform") or [],
            lambda item: A(
                href=filter_url(
                    stats_links.sessions_for_platform(item["platform_id"], year)
                ),
                class_="hover:underline decoration-dotted",
            )[item["platform_name"] or "Unspecified"],
            lambda item: _dur(item["playtime"]),
        ),
    ]

    all_finished = list(ctx.get("all_finished_this_year") or [])
    if all_finished:
        sections += [
            _h1("Finished"),
            _finished_table(
                all_finished,
                view_all_url=filter_url(
                    stats_links.purchases_finished(year), sort="-finished"
                ),
                total=ctx.get("all_finished_this_year_count"),
            ),
        ]

    year_finished = list(ctx.get("this_year_finished_this_year") or [])
    if year_finished:
        sections += [
            _h1(f"Finished ({year} games)"),
            _finished_table(
                year_finished,
                view_all_url=filter_url(
                    stats_links.purchases_finished_released(year), sort="finished"
                ),
                total=ctx.get("this_year_finished_this_year_count"),
            ),
        ]

    bought_finished = list(ctx.get("purchased_this_year_finished_this_year") or [])
    if bought_finished:
        sections += [
            _h1(f"Bought and Finished ({year})"),
            _finished_table(
                bought_finished,
                view_all_url=filter_url(
                    stats_links.purchases_bought_and_finished(year), sort="finished"
                ),
            ),
        ]

    unfinished = list(ctx.get("purchased_unfinished") or [])
    if unfinished:
        sections += [
            _h1("Unfinished Purchases"),
            _priced_table(
                unfinished,
                currency,
                view_all_url=filter_url(stats_links.purchases_unfinished(year)),
                total=ctx.get("purchased_unfinished_count"),
            ),
        ]

    return Div(
        [("class", f"dark:text-white w-full {CONTENT_MAX_WIDTH_CLASS} mx-auto")],
        sections,
    )
