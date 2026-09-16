"""The preset picker removes through the API; Undo posts here."""

from functools import partial
from typing import cast
from uuid import UUID

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.http import HttpRequest, HttpResponse
from django.views.decorators.http import require_POST

from games.models import FilterPreset
from games.ownership import owned_or_404
from games.removal import restore
from games.views.removal import restore_and_return


@login_required
@require_POST
def restore_preset(request: HttpRequest, preset_id: UUID) -> HttpResponse:
    """Undo: the row is removed, so the plain manager resolves it."""
    library = cast(User, request.user).library
    preset = owned_or_404(
        FilterPreset.objects.filter(library=library), library, id=preset_id
    )
    return restore_and_return(
        request,
        action=partial(restore, preset),
        restored="Preset restored.",
        fallback="games:list_games",
    )
