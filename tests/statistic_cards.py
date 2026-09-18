"""Read one statistic card out of a rendered page."""


def statistic_card(html: str, label: str) -> str:
    """The card whose label is `label`, from its element to the next.

    A figure states its second line as a sibling of its popover, so an
    assertion that reads only the popover reads only half the card.
    """
    cards = html.split('data-statistic-card=""')
    for card in cards[1:]:
        end = card.find('data-statistic-card=""')
        body = card if end == -1 else card[:end]
        if f">{label}</p>" in body:
            return body
    raise AssertionError(f"no statistic card labelled {label!r}")
