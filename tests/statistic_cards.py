"""Read one statistic card out of a rendered page."""


def statistic_card(html: str, label: str) -> str:
    """The card whose label is `label`, bounded by its own grid.

    A figure states its second line as a sibling of its popover, so an
    assertion that reads only the popover reads only half the card. The
    last card of a grid ends at the grid, not at the end of the page.
    """
    grids = html.split('data-statistic-grid=""')
    for grid in grids[1:]:
        for card in grid.split('data-statistic-card=""')[1:]:
            end = card.find('data-statistic-card=""')
            body = card if end == -1 else card[:end]
            if f">{label}</p>" in body:
                return body[: body.find('data-statistic-grid=""')]
    raise AssertionError(f"no statistic card labelled {label!r}")
