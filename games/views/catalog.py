"""Add, state and remove a private Game's Editions and Releases.

Every write goes through `games/catalog_writes.py`; nothing here
touches a model. A shared Game is not reachable: it has no owning
library, so `owned_or_404` refuses it before a form is built.
"""

from functools import partial
from typing import cast
from uuid import UUID

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect

from common.components import AddForm, Fragment, ModuleScript
from common.date_time_presentation import date_time_presentation_for_request
from common.layout import render_page
from games.catalog_compat import write_and_mirror
from games.catalog_writes import remove_edition, remove_release
from games.forms import EditionForm, ReleaseForm
from games.models import Edition, Game, Release
from games.ownership import owned_or_404
from games.views.removal import confirm_and_remove
from games.views.returns import return_url


def _owned_game(request: HttpRequest, game_id: UUID) -> Game:
    library = cast(User, request.user).library
    return owned_or_404(Game.objects.for_library(library), library, id=game_id)


def _owned_edition(request: HttpRequest, edition_id: UUID) -> Edition:
    library = cast(User, request.user).library
    return owned_or_404(
        Edition.objects.for_library(library).select_related("game"),
        library,
        id=edition_id,
    )


def _owned_release(request: HttpRequest, release_id: UUID) -> Release:
    library = cast(User, request.user).library
    return owned_or_404(
        Release.objects.for_library(library).select_related("edition__game"),
        library,
        id=release_id,
    )


def _back_to(request: HttpRequest, game: Game) -> str:
    return return_url(
        request,
        fallback="games:view_game",
        fallback_args=(game.pk, game.url_slug),
    )


def _edition_page(
    request: HttpRequest, form: EditionForm, game: Game, title: str
) -> HttpResponse:
    if request.method == "POST" and form.is_valid() and form.write() is not None:
        return redirect(_back_to(request, game))
    return render_page(request, AddForm(form, request=request), title=title)


def _release_page(
    request: HttpRequest, form: ReleaseForm, game: Game, title: str
) -> HttpResponse:
    if request.method == "POST" and form.is_valid() and form.write() is not None:
        return redirect(_back_to(request, game))
    return render_page(
        request,
        AddForm(form, request=request),
        title=title,
        #: A widget renders to text, thus its Media never bubbles.
        scripts=Fragment(
            ModuleScript("dist/elements/search-select.js"),
            ModuleScript("dist/elements/temporal-field.js"),
        ),
    )


@login_required
def add_edition(request: HttpRequest, game_id: UUID) -> HttpResponse:
    game = _owned_game(request, game_id)
    library = cast(User, request.user).library
    form = EditionForm(request.POST or None, library=library, game=game)
    return _edition_page(request, form, game, "Add edition")


@login_required
def edit_edition(request: HttpRequest, edition_id: UUID) -> HttpResponse:
    edition = _owned_edition(request, edition_id)
    library = cast(User, request.user).library
    form = EditionForm(
        request.POST or None,
        library=library,
        game=edition.game,
        instance=edition,
    )
    return _edition_page(request, form, edition.game, "Edit edition")


@login_required
def remove_edition_view(request: HttpRequest, edition_id: UUID) -> HttpResponse:
    edition = _owned_edition(request, edition_id)
    library = cast(User, request.user).library
    game = edition.game
    return confirm_and_remove(
        request,
        edition,
        title="Remove edition",
        message=f"Remove the {edition.display_name} edition of {game.name}?",
        fallback="games:view_game",
        fallback_args=(game.pk, game.url_slug),
        action=partial(
            write_and_mirror,
            game,
            partial(remove_edition, edition=edition, library=library),
        ),
    )


@login_required
def add_release(request: HttpRequest, edition_id: UUID) -> HttpResponse:
    edition = _owned_edition(request, edition_id)
    library = cast(User, request.user).library
    form = ReleaseForm(
        request.POST or None,
        library=library,
        presentation=date_time_presentation_for_request(request),
        edition=edition,
    )
    return _release_page(request, form, edition.game, "Add release")


@login_required
def edit_release(request: HttpRequest, release_id: UUID) -> HttpResponse:
    release = _owned_release(request, release_id)
    library = cast(User, request.user).library
    form = ReleaseForm(
        request.POST or None,
        library=library,
        presentation=date_time_presentation_for_request(request),
        edition=release.edition,
        instance=release,
    )
    return _release_page(request, form, release.edition.game, "Edit release")


@login_required
def remove_release_view(request: HttpRequest, release_id: UUID) -> HttpResponse:
    release = _owned_release(request, release_id)
    library = cast(User, request.user).library
    game = release.edition.game
    return confirm_and_remove(
        request,
        release,
        title="Remove release",
        message=f"Remove this release of {release.edition.display_name}?",
        fallback="games:view_game",
        fallback_args=(game.pk, game.url_slug),
        action=partial(
            write_and_mirror,
            game,
            partial(remove_release, release=release, library=library),
        ),
    )
