"""Read the purchase rows a rendered list prints."""


def row_order(body, purchases):
    """The purchases in the order the body prints them."""
    positions = {
        purchase.pk: body.index(f'id="purchase-row-{purchase.pk}"')
        for purchase in purchases
        if f'id="purchase-row-{purchase.pk}"' in body
    }
    return [pk for pk, _ in sorted(positions.items(), key=lambda pair: pair[1])]
