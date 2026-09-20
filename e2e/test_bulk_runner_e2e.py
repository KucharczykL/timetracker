"""A batch walks its own chunks, with nobody pressing Continue."""

import json
from datetime import date, timedelta
from urllib.parse import quote

from django.urls import reverse
from playwright.sync_api import Page, expect
from session_rows import duration_only_row, tracked_run
from tracked_games import create_tracked_game

from games.models import HistoricalPlaytime, PlayerSession


def _login(page: Page, live_server) -> None:
    page.goto(f"{live_server.url}{reverse('login')}")
    page.fill('input[name="username"]', "tester")
    page.fill('input[name="password"]', "secret123")
    page.click('button:has-text("Login")')
    page.wait_for_url(f"{live_server.url}/tracker**")


#: The tray that posts this statement is #712's. Until it lands, the
#: browser states the same thing the same way: one POST of a selection
#: to the act's route, from the page the act returns to.
_POST_THE_SELECTION = """
(stated) => {
  const token = document.querySelector('input[name="csrfmiddlewaretoken"]');
  if (!token) throw new Error("no csrf input on the origin page");
  const form = document.createElement("form");
  form.method = "post";
  form.action = stated.url;
  for (const [name, value] of [
    ["csrfmiddlewaretoken", token.value],
    ["selection", stated.selection],
  ]) {
    const field = document.createElement("input");
    field.type = "hidden";
    field.name = name;
    field.value = value;
    form.append(field);
  }
  document.body.append(form);
  form.submit();
}
"""


def test_a_batch_carries_itself_from_one_chunk_to_the_next(
    live_server, page: Page, e2e_user, e2e_library, monkeypatch
):
    """Three rows, one a chunk, and one press.

    The budget is nothing, so each request acts on a single row and the
    two that follow are the element's doing. Stop is not pressed here:
    the element posts as soon as it connects, so which of the two wins a
    real race is a race. That Stop keeps the element quiet is a vitest,
    and that the route ends a batch is `tests/test_bulk_runner.py`.
    """
    monkeypatch.setattr("games.views.bulk.CHUNK_BUDGET", timedelta(0))
    game = create_tracked_game(e2e_library, "Outer Wilds")
    run = tracked_run(e2e_library, game)
    sessions = [
        duration_only_row(run, date(2026, 3, day), timedelta(hours=9))
        for day in (5, 6, 7)
    ]
    errors: list[str] = []
    page.on(
        "console",
        lambda message: (
            errors.append(message.text) if message.type == "error" else None
        ),
    )
    _login(page, live_server)

    origin = reverse("games:library")
    page.goto(f"{live_server.url}{origin}")
    act = reverse("games:run_bulk_action", args=["session.reclassify"])
    page.evaluate(
        _POST_THE_SELECTION,
        {
            "url": f"{live_server.url}{act}?origin={quote(origin)}",
            "selection": json.dumps(
                {"mode": "some", "keys": [str(row.pk) for row in sessions]}
            ),
        },
    )

    page.get_by_role("button", name="Record as historical playtime").click()

    #: Server-rendered, and the last thing the batch does, so the rows
    #: are committed by the time it shows.
    expect(page.get_by_text("3 of 3 done.")).to_be_visible()
    page.wait_for_url(f"{live_server.url}{origin}")
    assert PlayerSession.objects.alive().count() == 0
    assert HistoricalPlaytime.objects.alive().count() == 3
    assert errors == []
