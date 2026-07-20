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
    A,
    Column,
    ContentContainer,
    ControlButton,
    Div,
    Element,
    Fragment,
    GameLink,
    ICON_BUTTON_SIZE_CLASS,
    Icon,
    Node,
    PageHeading,
    Safe,
    StyledTable,
    YearPicker,
    make_row,
)
from common.time import durationformat, format_duration
from games.filters import filter_url
from games.views import stats_links
from games.views.stats_data import StatsData

_FILTER_LINK_CLASS = "underline decoration-dotted hover:decoration-solid"


# Stats lists are previews: capped to this many rows, with a "View all" link to
# the full filtered list (#65).
_LIST_CAP = 5


def _cell(value: object) -> str:
    """Coerce a scalar stat value to a table-cell string (satisfies Cell)."""
    return str(value)


def _session_link(game_id, year, label: str = "") -> Node:
    """Small affordance linking a game row to its (year-scoped) session list.
    Sits next to the existing GameLink (which goes to the game detail page).

    ``label`` is the game name, embedded in the filter so the destination bar
    renders a named pill instead of a bare id (#224). ``decoration-transparent``
    opts the play-icon glyph out of the row's forced ``[&_a]:underline``."""
    return A(
        href=filter_url(stats_links.sessions_for_game(game_id, year, label)),
        class_="ml-1 inline-block align-middle decoration-transparent hover:text-heading",
        title="View sessions",
    )[Icon("play", size=ICON_BUTTON_SIZE_CLASS)]


def _count_link(value, url: str) -> Node:
    return A(href=url, class_="hover:underline decoration-dotted")[str(value)]


def _view_all_button(count: int, url: str) -> Node:
    """The capped-preview "View all (N)" affordance, below the table (the old
    colspan footer row can't pass through make_row). Mirrors game.py's
    _game_section convention: a gray ControlButton with an arrow icon."""
    return Div(class_="mt-3")[
        ControlButton(href=url, color="gray")[
            Icon("arrowright", size=ICON_BUTTON_SIZE_CLASS),
            f"View all ({count})",
        ]
    ]


def _kv_table(rows: list) -> Node:
    """A headerless key-value StyledTable: label (as <th scope=row>) + value.
    Two placeholder columns satisfy the cell-count guard; no header renders.
    The value column right-aligns so numbers sit on a common edge."""
    return StyledTable(
        columns=[Column(""), Column("", align="right")],
        rows=rows,
        show_header=False,
    )


def _card_title(text: str) -> Node:
    """A per-card section heading (h2, subheading size). Not PageHeading —
    the page carries a single PageHeading h1; cards sit under it."""
    return Element("h2", [("class", "text-type-subheading text-heading mb-3")])[text]


def _card(title: str, body: Node) -> Node:
    """One grid cell: a section title above its StyledTable. ``min-w-0`` lets the
    cell shrink so a wide table scrolls inside its own box instead of blowing out
    the grid column."""
    return Div(class_="min-w-0")[_card_title(title), body]


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

    alltime_classes = "inline-flex items-center rounded-base px-4 py-2 mr-3 text-type-body font-medium "
    alltime_classes += (
        "solid-brand hover:bg-brand-strong"
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
    return Div(class_="flex justify-center items-center mb-12")[alltime_btn, picker]


def _playtime_table(ctx) -> Node:
    year = ctx.get("year")
    rows = [
        make_row("Hours", _cell(ctx.get("total_hours"))),
        make_row(
            "Sessions",
            _count_link(
                ctx.get("total_sessions"),
                filter_url(stats_links.all_sessions(year)),
            ),
        ),
        make_row(
            "Days",
            f"{ctx.get('unique_days')} ({ctx.get('unique_days_percent')}%)",
        ),
    ]
    if ctx.get("total_games"):
        rows.append(
            make_row(
                "Games",
                _count_link(
                    ctx.get("total_games"),
                    filter_url(stats_links.games_played(year)),
                ),
            )
        )
    rows.append(make_row(f"Games ({year})", _cell(ctx.get("total_year_games"))))
    if ctx.get("all_finished_this_year_count"):
        rows.append(
            make_row("Finished", _cell(ctx.get("all_finished_this_year_count")))
        )
    rows.append(
        make_row(
            f"Finished ({year})",
            _cell(ctx.get("this_year_finished_this_year_count")),
        )
    )

    def _game_row(label, value, game):
        return make_row(
            label,
            Fragment(
                _cell(value),
                " (",
                GameLink(game.id, game.name),
                ")",
                _session_link(game.id, year, game.name),
            ),
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
            make_row(
                "First play",
                Fragment(
                    GameLink(first_game.id, first_game.name),
                    f" ({ctx.get('first_play_date')})",
                    _session_link(first_game.id, year, first_game.name),
                ),
            )
        )
    last_game = ctx.get("last_play_game")
    if last_game and last_game.id:
        rows.append(
            make_row(
                "Last play",
                Fragment(
                    GameLink(last_game.id, last_game.name),
                    f" ({ctx.get('last_play_date')})",
                    _session_link(last_game.id, year, last_game.name),
                ),
            )
        )
    return _kv_table(rows)


def _purchases_table(ctx) -> Node:
    year = ctx.get("year")
    rows = [
        make_row(
            "Total",
            _count_link(
                ctx.get("all_purchased_this_year_count"),
                filter_url(stats_links.purchases_total(year)),
            ),
        ),
        make_row(
            "Refunded",
            _count_link(
                f"{ctx.get('all_purchased_refunded_this_year_count')} "
                f"({ctx.get('refunded_percent')}%)",
                filter_url(stats_links.purchases_refunded(year)),
            ),
        ),
        make_row(
            "Dropped",
            _count_link(
                f"{ctx.get('dropped_count')} ({ctx.get('dropped_percentage')}%)",
                filter_url(stats_links.purchases_dropped(year)),
            ),
        ),
        make_row(
            "Unfinished",
            _count_link(
                f"{ctx.get('purchased_unfinished_count')} "
                f"({ctx.get('unfinished_purchases_percent')}%)",
                filter_url(stats_links.purchases_unfinished(year)),
            ),
        ),
        make_row(
            "Backlog Decrease",
            _count_link(
                ctx.get("backlog_decrease_count"),
                filter_url(stats_links.purchases_backlog_decrease(year)),
            ),
        ),
        make_row(
            f"Spendings ({ctx.get('total_spent_currency')})",
            f"{floatformat(ctx.get('total_spent'))} "
            f"({floatformat(ctx.get('spent_per_game'))}/game)",
        ),
    ]
    return _kv_table(rows)


def _two_col_table(header: str, items, name_key, value_fn, view_all_url=None) -> Node:
    items = list(items)
    display = items[:_LIST_CAP] if view_all_url else items
    rows = [make_row(name_key(item), value_fn(item)) for item in display]
    table = StyledTable(
        columns=[Column(header), Column("Playtime", align="right")],
        rows=rows,
    )
    if view_all_url and len(items) > _LIST_CAP:
        return Fragment(table, _view_all_button(len(items), view_all_url))
    return table


def _finished_table(purchases, view_all_url=None, total=None) -> Node:
    purchases = list(purchases)
    display = purchases[:_LIST_CAP] if view_all_url else purchases
    rows = [
        make_row(_purchase_name(p), date_filter(p.date_finished, "d/m/Y"))
        for p in display
    ]
    table = StyledTable(
        columns=[Column("Name"), Column("Date", align="right")], rows=rows
    )
    total = total if total is not None else len(purchases)
    if view_all_url and total > _LIST_CAP:
        return Fragment(table, _view_all_button(total, view_all_url))
    return table


def _priced_table(purchases, currency, view_all_url=None, total=None) -> Node:
    purchases = list(purchases)
    display = purchases[:_LIST_CAP] if view_all_url else purchases
    rows = [
        make_row(_purchase_name(p), floatformat(p.converted_price)) for p in display
    ]
    table = StyledTable(
        columns=[Column("Name"), Column(f"Price ({currency})", align="right")],
        rows=rows,
    )
    total = total if total is not None else len(purchases)
    if view_all_url and total > _LIST_CAP:
        return Fragment(table, _view_all_button(total, view_all_url))
    return table


def stats_content(ctx: StatsData) -> Node:
    year = ctx["year"]
    currency = ctx.get("total_spent_currency")
    # Build a navigation URL with an `__year__` placeholder the picker's JS
    # substitutes. Reverse a sentinel year, then swap it for the placeholder
    # (anchored on `stats/0` so the match is unambiguous).
    url_template = reverse("games:stats_by_year", args=[0]).replace(
        "stats/0", "stats/__year__"
    )
    # Each stats section is one card in the grid: a title above its table.
    cards: list[Node] = [
        _card("Playtime", _playtime_table(ctx)),
    ]

    months = list(ctx.get("month_playtimes") or [])
    if months:
        month_rows = [
            make_row(
                date_filter(m["month"], "F"),
                A(
                    href=filter_url(
                        stats_links.games_in_month(year, m["month"].month),
                        sort="-filtered_playtime",
                    ),
                    class_=_FILTER_LINK_CLASS,
                )[_dur(m["playtime"])],
            )
            for m in months
        ]
        cards.append(_card("Playtime per month", _kv_table(month_rows)))

    cards += [
        _card("Purchases", _purchases_table(ctx)),
        _card(
            "Games by playtime",
            _two_col_table(
                "Name",
                ctx.get("top_10_games_by_playtime") or [],
                lambda g: Fragment(
                    GameLink(g.id, g.name), _session_link(g.id, year, g.name)
                ),
                lambda g: _dur(g.total_playtime),
                view_all_url=filter_url(
                    stats_links.games_played(year), sort="-filtered_playtime"
                ),
            ),
        ),
        _card(
            "Platforms by playtime",
            _two_col_table(
                "Platform",
                ctx.get("total_playtime_per_platform") or [],
                lambda item: item["platform_name"] or "Unspecified",
                lambda item: A(
                    href=filter_url(
                        stats_links.sessions_for_platform(
                            item["platform_id"], year, item["platform_name"] or ""
                        )
                    ),
                    class_=_FILTER_LINK_CLASS,
                )[_dur(item["playtime"])],
            ),
        ),
    ]

    all_finished = list(ctx.get("all_finished_this_year") or [])
    if all_finished:
        cards.append(
            _card(
                "Finished",
                _finished_table(
                    all_finished,
                    view_all_url=filter_url(
                        stats_links.purchases_finished(year), sort="-finished"
                    ),
                    total=ctx.get("all_finished_this_year_count"),
                ),
            )
        )

    year_finished = list(ctx.get("this_year_finished_this_year") or [])
    if year_finished:
        cards.append(
            _card(
                f"Finished ({year} games)",
                _finished_table(
                    year_finished,
                    view_all_url=filter_url(
                        stats_links.purchases_finished_released(year), sort="finished"
                    ),
                    total=ctx.get("this_year_finished_this_year_count"),
                ),
            )
        )

    bought_finished = list(ctx.get("purchased_this_year_finished_this_year") or [])
    if bought_finished:
        cards.append(
            _card(
                f"Bought and Finished ({year})",
                _finished_table(
                    bought_finished,
                    view_all_url=filter_url(
                        stats_links.purchases_bought_and_finished(year), sort="finished"
                    ),
                ),
            )
        )

    unfinished = list(ctx.get("purchased_unfinished") or [])
    if unfinished:
        cards.append(
            _card(
                "Unfinished Purchases",
                _priced_table(
                    unfinished,
                    currency,
                    view_all_url=filter_url(stats_links.purchases_unfinished(year)),
                    total=ctx.get("purchased_unfinished_count"),
                ),
            )
        )

    grid = Div(class_="grid grid-cols-1 md:grid-cols-2 gap-6 items-start")[*cards]
    return ContentContainer(class_="dark:text-white")[
        PageHeading([ctx["title"]]),
        _year_nav(year, ctx.get("stats_dropdown_year_range"), url_template),
        grid,
    ]
