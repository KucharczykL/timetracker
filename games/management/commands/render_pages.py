"""Render every read-only page as one user, to files.

The instrument of a before-and-after rehearsal: run it at two
commits against one database and diff the directories. It reads
the route table through `READ_ONLY`, so a route added later is
rendered without an edit here.
"""

import re
from collections.abc import Iterator
from pathlib import Path
from typing import NamedTuple

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.test import Client, override_settings
from django.urls import NoReverseMatch, reverse
from django.utils.html import escape

from common.components.custom_elements import FILTER_MODE_MODELS
from common.layout import VERSION_STAMP_CLASS
from common.returns import UrlName
from games.models import Game, Purchase, UserLibrary
from games.reads.playtime import played_years
from games.views.returns import READ_ONLY

#: `ALLOWED_HOSTS` admits `testserver` under the test runner only.
HOST = "localhost"

#: One page holds the whole list.
UNPAGINATED = "?per_page=0"

LIST_ROUTES: frozenset[UrlName] = frozenset(
    {
        "games:list_devices",
        "games:list_games",
        "games:list_historical_playtime",
        "games:list_platforms",
        "games:list_playthroughs",
        "games:list_purchases",
        "games:list_sessions",
    }
)

#: Every token in a page: the hidden input and any
#: `...csrf="..."` attribute; then the footer's build stamp.
_CSRF_TOKEN = re.compile(r'((?:name="csrfmiddlewaretoken" value|[\w-]*csrf)=")[^"]*(")')
_VERSION_FOOTER = re.compile(
    rf'(class="{re.escape(escape(VERSION_STAMP_CLASS))}">)[^<]*(</footer>)'
)


class RenderedUrl(NamedTuple):
    name: UrlName
    url: str
    file_name: str


def _file_name(url: str) -> str:
    return url.strip("/").replace("/", "_").replace("?", "_") + ".html"


def _rendered(name: UrlName, url: str) -> RenderedUrl:
    return RenderedUrl(name, url, _file_name(url))


class RenderPlan(NamedTuple):
    urls: list[RenderedUrl]
    #: Named in READ_ONLY, mounted only under DEBUG.
    unmounted: list[UrlName]


def render_plan(user: User) -> RenderPlan:
    """Every read-only route, once or once per row."""
    library: UserLibrary = user.library
    unmounted: list[UrlName] = []
    return RenderPlan(list(_urls(library, unmounted)), unmounted)


def _urls(library: UserLibrary, unmounted: list[UrlName]) -> Iterator[RenderedUrl]:
    for name in sorted(READ_ONLY):
        if name in LIST_ROUTES:
            yield _rendered(name, reverse(name) + UNPAGINATED)
        elif name == "games:view_game":
            for game in Game.objects.for_library(library).order_by("pk"):
                yield _rendered(name, game.get_absolute_url())
        elif name == "games:view_purchase":
            for purchase in Purchase.objects.for_library(library).order_by("pk"):
                yield _rendered(name, reverse(name, args=[purchase.pk]))
        elif name == "games:stats_by_year":
            for year in played_years(library):
                yield _rendered(name, reverse(name, args=[year]))
        elif name == "games:filter_builder":
            for model in FILTER_MODE_MODELS.values():
                yield _rendered(name, reverse(name, args=[model]))
        else:
            try:
                yield _rendered(name, reverse(name))
            except NoReverseMatch:
                unmounted.append(name)


def normalise(html: str) -> str:
    """What differs between two renders of one page on one database."""
    html = _CSRF_TOKEN.sub(r"\1CSRF\2", html)
    return _VERSION_FOOTER.sub(r"\1VERSION\2", html)


class NotOk(NamedTuple):
    url: str
    status: int


class RenderReport(NamedTuple):
    pages: int
    not_ok: list[NotOk]
    unmounted: list[UrlName]


def render_pages(user: User, out: Path) -> RenderReport:
    """Write one file per URL: the status first, the page after."""
    client = Client(SERVER_NAME=HOST)
    client.force_login(user)
    plan = render_plan(user)
    pages = 0
    not_ok: list[NotOk] = []
    #: The debug toolbar stamps per-request timings into a page.
    with override_settings(INTERNAL_IPS=[]):
        for rendered in plan.urls:
            response = client.get(rendered.url)
            body = normalise(response.content.decode())
            (out / rendered.file_name).write_text(f"{response.status_code}\n{body}")
            pages += 1
            if response.status_code != 200:
                not_ok.append(NotOk(rendered.url, response.status_code))
    return RenderReport(pages, not_ok, plan.unmounted)


class Command(BaseCommand):
    help = "Render every read-only page as one user into a directory of files."

    def add_arguments(self, parser):
        parser.add_argument("--user", required=True, help="Render as this username.")
        parser.add_argument(
            "--out", required=True, type=Path, help="An empty or absent directory."
        )

    def handle(self, *args, **options):
        try:
            user = User.objects.get(username=options["user"])
        except User.DoesNotExist as error:
            raise CommandError(f"No user {options['user']!r}.") from error
        #: call_command passes a str; argparse a Path.
        out = Path(options["out"])
        if out.exists() and any(out.iterdir()):
            raise CommandError(f"{out} is not empty; name an empty directory.")
        out.mkdir(parents=True, exist_ok=True)
        report = render_pages(user, out)
        self.stdout.write(
            f"Rendered {report.pages} page(s) into {out}; "
            f"{len(report.not_ok)} answered other than 200."
        )
        for url, status in report.not_ok:
            self.stdout.write(f"  {status} {url}")
        for name in report.unmounted:
            self.stdout.write(f"  {name} is not mounted here; nothing rendered.")
