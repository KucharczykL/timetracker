"""Posting one act through the runner, as a page does."""

import html as html_module
import json

from django.urls import reverse

from games.bulk_actions import BulkAction
from games.views.bulk import (
    CHOICE_FIELD,
    PROGRESS_FIELD,
    STATEMENT_FIELD,
    TOKEN_FIELD,
)


def selection(*rows) -> str:
    """The statement a selection line posts."""
    return json.dumps({"mode": "some", "keys": sorted(str(row.pk) for row in rows)})


def posted(response) -> dict[str, str]:
    """The hidden fields the confirmation would submit."""
    markup = response.content.decode()
    fields: dict[str, str] = {}
    for name in (TOKEN_FIELD, PROGRESS_FIELD, CHOICE_FIELD):
        marker = f'name="{name}" value="'
        if marker in markup:
            start = markup.index(marker) + len(marker)
            fields[name] = html_module.unescape(
                markup[start : markup.index('"', start)]
            )
    return fields


def act_url(action: BulkAction) -> str:
    return reverse("games:run_bulk_action", args=[action.name])


def press(client, action: BulkAction, *rows, follow: bool = False):
    """Confirm the act, then post the confirmation.

    The two POSTs one press makes: the runner tells them apart by the
    token the confirmation carries.
    """
    url = act_url(action)
    confirmation = client.post(url, {STATEMENT_FIELD: selection(*rows)})
    return client.post(url, posted(confirmation), follow=follow)
