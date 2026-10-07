"""One submit of the Game form.

The columns, the graph, the external references and the mirrors, in
one transaction. The PlayerGame command stays outside:
`run_in_transaction` refuses to nest.
"""

from typing import TYPE_CHECKING, Final, NamedTuple

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from games.catalog_addons import AddonRefused, state_addon
from games.catalog_compat import LEGACY_IDENTITY_TAKEN, MirroredIdentity
from games.catalog_form import CatalogGraphForm
from games.catalog_writes import DUPLICATE_EDITION_NAME
from games.external_references import mirror_game_wikidata
from games.models import Game
from games.reference_form import ReferenceSetForm
from games.writes.answers import absent_as_404

if TYPE_CHECKING:
    from games.forms import GameForm

#: No pre-check wins a race. The database decided.
RACED = "Another change reached this game first. Nothing was saved; try again."
#: A save writes every column, thus a stale form would put a removed
#: Game back with no event saying so.
REMOVED_SINCE_READ = (
    "This game was removed while you were editing it. Nothing was saved."
)


class ConstraintAnswer(NamedTuple):
    """What a constraint says, and where."""

    sentence: str
    field: str | None


#: A refusal only the database can state.
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
}

#: Declared on a model this form writes, and out of reach.
#: A constraint named here states why; the guard test reads it.
_ANSWERED_BY_THE_REFERENCE_SERVICE = (
    "`state_external_references` writes in a savepoint of its own "
    "and reads the constraint the database names, thus this "
    "arrives as a `ReferencesRefused` naming the box that stated "
    "it, never as an `IntegrityError`."
)
_REFUSED_BY_THE_REFERENCE_FORM = (
    "`ReferenceSetForm` names one supported provider per box and "
    "normalises its key, and the service picks the target column "
    "by entity kind, thus no write reaches this check."
)
_REFUSED_BY_STATE_ADDON = (
    "`state_addon` refuses first and names the field, thus no save reaches this check."
)
_A_SELECT_OVER_THE_WORDS = (
    "The field is a select over the same words, thus no save reaches this check."
)
UNREACHABLE_FROM_THE_GAME_FORM: Final[dict[str, str]] = {
    "external_reference_kind_matches_target": _REFUSED_BY_THE_REFERENCE_FORM,
    "external_reference_supported_provider": _REFUSED_BY_THE_REFERENCE_FORM,
    "external_reference_canonical_provider_key": _REFUSED_BY_THE_REFERENCE_FORM,
    "game_kind_word": _A_SELECT_OVER_THE_WORDS,
    "game_parent_exactly_for_addons": _REFUSED_BY_STATE_ADDON,
    "game_not_its_own_parent": _REFUSED_BY_STATE_ADDON,
    "edition_kind_word": _A_SELECT_OVER_THE_WORDS,
    "unique_external_reference_provider_kind_key": _ANSWERED_BY_THE_REFERENCE_SERVICE,
    "unique_live_game_reference_per_provider": _ANSWERED_BY_THE_REFERENCE_SERVICE,
    "unique_live_edition_reference_per_provider": _ANSWERED_BY_THE_REFERENCE_SERVICE,
    "unique_live_release_reference_per_provider": _ANSWERED_BY_THE_REFERENCE_SERVICE,
    "unique_live_platform_reference_per_provider": _ANSWERED_BY_THE_REFERENCE_SERVICE,
}


def answered_constraint(collision: IntegrityError) -> ConstraintAnswer | None:
    """What the database refused, in readable words.

    An unmapped constraint gets none and rises as itself, as
    `games/writes/answers.py` treats an unmapped conflict: a wrong
    sentence is worse than none.
    """
    diagnostic = getattr(collision.__cause__, "diag", None)
    name = None if diagnostic is None else diagnostic.constraint_name
    return None if name is None else CONSTRAINT_ANSWERS.get(name)


@transaction.atomic
def save_game_columns(form: GameForm, identity: MirroredIdentity) -> Game:
    """The Game's own columns.

    The name and the flat pair go in one write. The unique
    constraint reads all three, thus a rename that moves its own
    platform never stands beside the pair it is replacing.
    """
    game = form.save(commit=False)
    #: First: locks both rows in key order.
    #: Locking the Game alone first could deadlock.
    state_addon(
        game,
        kind=form.cleaned_data["kind"],
        parent=form.cleaned_data["parent"],
        library=form.library,
    )
    if not game._state.adding:
        persisted = Game.objects.select_for_update().get(pk=game.pk)
        if persisted.library_id != game.library_id:
            raise ValidationError("A persisted Game cannot change library owner.")
        #: The form read this Game while it was live, and `save()`
        #: writes every column, `removed_at` among them. A Game
        #: removed since would come back with no event saying so.
        if persisted.removed_at is not None:
            raise ValidationError(REMOVED_SINCE_READ)
    if game.library_id is None:
        raise ValidationError("A private Game requires a library owner.")
    game.original_release_date = form.cleaned_data["original_release_date"]
    game.platform = identity.platform
    game.year_released = identity.year_released
    game.save()
    return game


@transaction.atomic
def save_game_and_graph(
    form: GameForm, graph: CatalogGraphForm, references: ReferenceSetForm
) -> Game:
    """The Game, its graph and its references."""
    game = save_game_columns(form, graph.mirrored_identity())
    graph.bind(game)
    graph.write()
    references.bind(game)
    references.write()
    #: The reference states it; the column follows.
    mirror_game_wikidata(game)
    return game


def _game_form_refusal(form: GameForm, error: ValidationError) -> bool:
    """A refusal the Game's own fields caused."""
    if isinstance(error, AddonRefused):
        form.add_error(error.field, error.messages[0])
        return True
    if REMOVED_SINCE_READ in error.messages:
        form.add_error(None, REMOVED_SINCE_READ)
        return True
    if LEGACY_IDENTITY_TAKEN in error.messages:
        #: (name, platform, year) is unique per library, and the
        #: platform and year come from the marked Release row.
        form.add_error(None, LEGACY_IDENTITY_TAKEN)
        return True
    return False


def submitted_game_or_form_error(
    form: GameForm, graph: CatalogGraphForm, references: ReferenceSetForm
) -> Game | None:
    """Write one submit, or answer every refusal.

    `IntegrityError` is caught out here: inside the transaction the
    connection is unusable, thus the answer follows the rollback.
    """
    with absent_as_404("game"):
        try:
            return save_game_and_graph(form, graph, references)
        except IntegrityError as collision:
            answer = answered_constraint(collision)
            if answer is None:
                raise
            form.add_error(answer.field, answer.sentence)
            return None
        except ValidationError as refusal:
            if references.answer(refusal):
                return None
            if _game_form_refusal(form, refusal):
                return None
            if graph.answer(refusal):
                return None
            #: The two column guards are programming errors.
            raise
