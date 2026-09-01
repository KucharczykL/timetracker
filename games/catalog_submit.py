"""One submit of the Game form.

The Game's own columns, its wikidata reference, its whole catalog
graph and the flat columns that shadow it, in one transaction. The
PlayerGame command stays outside: `run_in_transaction` opens the
transaction it retries and refuses to nest.
"""

from typing import TYPE_CHECKING, Final, NamedTuple

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from games.catalog_compat import LEGACY_IDENTITY_TAKEN
from games.catalog_form import CatalogGraphForm
from games.catalog_writes import DUPLICATE_EDITION_NAME
from games.external_references import sync_game_wikidata
from games.models import Game

if TYPE_CHECKING:
    from games.forms import GameForm

WIKIDATA_CONFLICT_MESSAGE = "This Wikidata entity ID already belongs to another game."
#: No pre-check wins a race. The database decided; this says so.
RACED = "Another change reached this game first. Nothing was saved; try again."


class ConstraintAnswer(NamedTuple):
    """What a constraint says, and where a person reads it."""

    sentence: str
    field: str | None


#: A refusal only the database can state, in words a person reads.
CONSTRAINT_ANSWERS: Final[dict[str, ConstraintAnswer]] = {
    "unique_library_game_name_platform_year": ConstraintAnswer(
        LEGACY_IDENTITY_TAKEN, None
    ),
    "unique_library_platformless_game_name_year": ConstraintAnswer(
        LEGACY_IDENTITY_TAKEN, None
    ),
    "unique_live_edition_name_per_game": ConstraintAnswer(DUPLICATE_EDITION_NAME, None),
    "unique_default_edition_per_game": ConstraintAnswer(RACED, None),
    "unique_default_release_per_edition": ConstraintAnswer(RACED, None),
    "unique_external_reference_provider_kind_key": ConstraintAnswer(
        WIKIDATA_CONFLICT_MESSAGE, "wikidata"
    ),
}

#: Declared on a model this form writes, and still out of its reach.
#: A constraint named here states why, and the guard test reads it.
UNREACHABLE_FROM_THE_GAME_FORM: Final[dict[str, str]] = {}


def answered_constraint(collision: IntegrityError) -> ConstraintAnswer | None:
    """What the database refused, if this form has words for it.

    An unmapped constraint gets none and rises as itself, the way
    `games/writes/answers.py` treats an unmapped conflict: a wrong
    sentence is worse than no sentence.
    """
    diagnostic = getattr(collision.__cause__, "diag", None)
    name = None if diagnostic is None else diagnostic.constraint_name
    return None if name is None else CONSTRAINT_ANSWERS.get(name)


@transaction.atomic
def save_game_columns(form: GameForm) -> Game:
    """The Game's own columns and its wikidata reference.

    No graph and no mirror: the graph is stated after this, and the
    mirror reads what the graph left.
    """
    game = form.save(commit=False)
    if not game._state.adding:
        persisted = Game.objects.select_for_update().get(pk=game.pk)
        if persisted.library_id != game.library_id:
            raise ValidationError("A persisted Game cannot change library owner.")
    if game.library_id is None:
        raise ValidationError("A private Game requires a library owner.")
    game.original_release_date = form.cleaned_data["original_release_date"]
    game.save()
    sync_game_wikidata(game=game)
    return game


@transaction.atomic
def save_game_and_graph(form: GameForm, graph: CatalogGraphForm) -> Game:
    """The Game and its whole graph, or neither of them.

    The mirror runs last, once, so a rename can no longer collide
    with the platform and year of a Release the same submit is
    replacing.
    """
    game = save_game_columns(form)
    graph.bind(game)
    graph.write()
    return game


def _game_form_refusal(form: GameForm, error: ValidationError) -> bool:
    """Put a refusal the Game's own fields caused back on them."""
    if hasattr(error, "message_dict") and set(error.message_dict) == {"provider_key"}:
        form.add_error("wikidata", WIKIDATA_CONFLICT_MESSAGE)
        return True
    if LEGACY_IDENTITY_TAKEN in error.messages:
        #: (name, platform, year) is unique per library, and the
        #: platform and the year come from the marked Release row.
        form.add_error(None, LEGACY_IDENTITY_TAKEN)
        return True
    return False


def submitted_game_or_form_error(
    form: GameForm, graph: CatalogGraphForm
) -> Game | None:
    """Write one submit, or put every refusal where it is read.

    `IntegrityError` is caught out here: inside the transaction the
    connection is unusable, thus the answer has to come after the
    rollback.
    """
    try:
        return save_game_and_graph(form, graph)
    except IntegrityError as collision:
        answer = answered_constraint(collision)
        if answer is None:
            raise
        form.add_error(answer.field, answer.sentence)
        return None
    except ValidationError as refusal:
        if _game_form_refusal(form, refusal):
            return None
        if graph.answer(refusal):
            return None
        #: `save_game_columns`'s two guards are programming errors,
        #: not things a person typed.
        raise
