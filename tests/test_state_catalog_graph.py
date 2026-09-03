"""One call states a whole Game's graph.

Every refusal is checked against the desired end state, before
anything is written, and carries the caller's own name for the row.
"""

import pytest
from django.core.exceptions import ValidationError

from games.catalog_writes import (
    DUPLICATE_EDITION_NAME,
    FOREIGN_GAME,
    FOREIGN_PLATFORM,
    FOREIGN_ROW,
    LAST_EDITION,
    REMOVED_EDITION,
    REMOVED_GAME,
    REMOVED_RELEASE,
    REPEATED_ROW,
    SHARED_GAME,
    TWO_DEFAULT_EDITIONS,
    TWO_DEFAULT_RELEASES,
    EditionState,
    GraphRefused,
    ReleaseState,
    state_catalog_graph,
)
from games.models import Edition, Game, Platform, Release
from games.removal import remove
from timetracker.temporal import TemporalValue

pytestmark = pytest.mark.django_db


@pytest.fixture
def other_library(django_user_model):
    return django_user_model.objects.create_user(username="second-owner").library


@pytest.fixture
def game(owned_library, stated_graph):
    return stated_graph(Game(library=owned_library, name="Deus Ex"), owned_library)


def one(key="edition-0", **fields) -> EditionState:
    """One Edition state, defaulting to a lone marked row."""
    fields.setdefault("is_default", True)
    fields.setdefault(
        "releases", (ReleaseState(key=f"{key}-release-0", is_default=True),)
    )
    return EditionState(key=key, **fields)


def state(game, library, *editions):
    return state_catalog_graph(game=game, library=library, editions=list(editions))


def test_a_shared_game_is_read_only(owned_library):
    shared = Game.objects.create(library=None, name="Shared")

    with pytest.raises(ValidationError) as refused:
        state(shared, owned_library, one())

    assert SHARED_GAME in refused.value.messages


def test_another_library_s_game_is_refused(other_library, game):
    with pytest.raises(ValidationError) as refused:
        state(game.game, other_library, one())

    assert FOREIGN_GAME in refused.value.messages


def test_a_removed_game_goes_back_first(owned_library, game):
    remove(game.game)

    with pytest.raises(ValidationError) as refused:
        state(game.game, owned_library, one())

    assert REMOVED_GAME in refused.value.messages


def test_a_named_edition_that_is_removed_is_refused(owned_library, game):
    """The caller read the row before the lock; storage decides."""
    remove(game.edition)

    with pytest.raises(GraphRefused) as refused:
        state(game.game, owned_library, one(edition=game.edition))

    assert REMOVED_EDITION in refused.value.messages
    assert refused.value.key == "edition-0"


def test_a_named_release_that_is_removed_is_refused(owned_library, game):
    remove(game.release)

    with pytest.raises(GraphRefused) as refused:
        state(
            game.game,
            owned_library,
            one(
                edition=game.edition,
                releases=(
                    ReleaseState(
                        key="edition-0-release-0",
                        release=game.release,
                        is_default=True,
                    ),
                ),
            ),
        )

    assert REMOVED_RELEASE in refused.value.messages
    assert refused.value.key == "edition-0-release-0"


def test_another_game_s_edition_is_refused(owned_library, game, stated_graph):
    theirs = stated_graph(Game(library=owned_library, name="Theirs"), owned_library)

    with pytest.raises(GraphRefused) as refused:
        state(game.game, owned_library, one(edition=theirs.edition))

    assert FOREIGN_ROW in refused.value.messages
    assert refused.value.key == "edition-0"


def test_another_edition_s_release_is_refused(owned_library, game, stated_graph):
    theirs = stated_graph(Game(library=owned_library, name="Theirs"), owned_library)

    with pytest.raises(GraphRefused) as refused:
        state(
            game.game,
            owned_library,
            one(
                edition=game.edition,
                releases=(
                    ReleaseState(
                        key="edition-0-release-0",
                        release=theirs.release,
                        is_default=True,
                    ),
                ),
            ),
        )

    assert FOREIGN_ROW in refused.value.messages
    assert refused.value.key == "edition-0-release-0"


def test_another_library_s_platform_is_refused(owned_library, other_library, game):
    theirs = Platform.objects.create(library=other_library, name="Theirs")

    with pytest.raises(GraphRefused) as refused:
        state(
            game.game,
            owned_library,
            one(
                releases=(
                    ReleaseState(
                        key="edition-0-release-0", platform=theirs, is_default=True
                    ),
                )
            ),
        )

    assert FOREIGN_PLATFORM in refused.value.messages
    assert refused.value.key == "edition-0-release-0"


def test_two_surviving_editions_may_not_state_one_name(owned_library, game):
    with pytest.raises(GraphRefused) as refused:
        state(
            game.game,
            owned_library,
            one(name="Original"),
            one(key="edition-1", name="original", is_default=False),
        )

    assert DUPLICATE_EDITION_NAME in refused.value.messages
    assert refused.value.key == "edition-1"


def test_two_names_the_constraint_separates_may_both_stand(owned_library, game):
    """`casefold()` read `Straße` and `STRASSE` as one name; the database does not."""
    written = state(
        game.game,
        owned_library,
        one(edition=game.edition, name="Straße"),
        one(key="edition-1", name="STRASSE", is_default=False),
    )

    assert sorted(entry.edition.name for entry in written.editions) == [
        "STRASSE",
        "Straße",
    ]


def test_a_name_an_unmentioned_edition_holds_is_refused(owned_library, game):
    """A row nobody states still holds its own name."""
    Edition.objects.create(game=game.game, name="Original")

    with pytest.raises(GraphRefused) as refused:
        state(game.game, owned_library, one(edition=game.edition, name="Original"))

    assert DUPLICATE_EDITION_NAME in refused.value.messages
    assert refused.value.key == "edition-0"


def test_a_game_keeps_an_edition(owned_library, game):
    with pytest.raises(GraphRefused) as refused:
        state(game.game, owned_library, one(edition=game.edition, removed=True))

    assert LAST_EDITION in refused.value.messages
    #: Every stated row is one the caller removed, and a sentence on
    #: a row the page has hidden is a sentence nobody reads.
    assert refused.value.key is None


def test_a_game_keeps_an_edition_nobody_stated(owned_library, game):
    """An unmentioned live Edition is an Edition the Game keeps."""
    Edition.objects.create(game=game.game, name="Original")

    state(game.game, owned_library, one(edition=game.edition, removed=True))

    assert Edition.objects.alive().filter(game=game.game).count() == 1


def test_two_stated_default_editions_are_refused(owned_library, game):
    with pytest.raises(GraphRefused) as refused:
        state(
            game.game,
            owned_library,
            one(name="First"),
            one(key="edition-1", name="Second"),
        )

    assert TWO_DEFAULT_EDITIONS in refused.value.messages
    assert refused.value.key == "edition-1"


def test_two_stated_default_releases_are_refused(owned_library, game):
    with pytest.raises(GraphRefused) as refused:
        state(
            game.game,
            owned_library,
            one(
                releases=(
                    ReleaseState(key="edition-0-release-0", is_default=True),
                    ReleaseState(key="edition-0-release-1", is_default=True),
                )
            ),
        )

    assert TWO_DEFAULT_RELEASES in refused.value.messages
    assert refused.value.key == "edition-0-release-1"


def test_nothing_is_written_when_the_set_is_refused(owned_library, game):
    """The refusal comes before the first write."""
    with pytest.raises(ValidationError):
        state(
            game.game,
            owned_library,
            one(edition=game.edition, name="Renamed"),
            one(key="edition-1", name="Renamed", is_default=False),
        )

    game.edition.refresh_from_db()
    assert game.edition.name == ""
    assert Edition.objects.filter(game=game.game).count() == 1


# --- what a statement writes -------------------------------------------------


def live_releases(edition: Edition) -> list[Release]:
    return list(Release.objects.alive().filter(edition=edition).order_by("pk"))


def test_a_binned_release_does_not_eat_its_re_add(owned_library, stated_graph):
    """The case that started this: one submit, two rows, one pair."""
    amiga = Platform.objects.create(library=owned_library, name="Amiga")
    graph = stated_graph(
        Game(library=owned_library, name="Elite"),
        owned_library,
        platform=amiga,
        release_date=TemporalValue.from_year(1984),
    )

    state(
        graph.game,
        owned_library,
        one(
            edition=graph.edition,
            releases=(
                ReleaseState(
                    key="edition-0-release-0", release=graph.release, removed=True
                ),
                ReleaseState(
                    key="edition-0-release-1",
                    platform=amiga,
                    release_date=TemporalValue.from_year(1984),
                    is_default=True,
                ),
            ),
        ),
    )

    graph.release.refresh_from_db()
    live = live_releases(graph.edition)
    assert graph.release.removed_at is not None
    assert [row.pk for row in live] != [graph.release.pk]
    assert len(live) == 1
    assert live[0].is_default is True


def test_a_binned_edition_does_not_eat_a_re_add_of_its_name(owned_library, game):
    original = Edition.objects.create(game=game.game, name="Original")

    state(
        game.game,
        owned_library,
        EditionState(key="edition-0", edition=original, name="Original", removed=True),
        one(key="edition-1", name="Original"),
    )

    original.refresh_from_db()
    live = Edition.objects.alive().filter(game=game.game, name="Original")
    assert original.removed_at is not None
    assert live.count() == 1
    assert live.get().pk != original.pk


def test_two_editions_exchange_names_in_one_statement(owned_library, game):
    """A name being given up is freed before it is taken."""
    beta = Edition.objects.create(game=game.game, name="Beta")
    Edition.objects.filter(pk=game.edition.pk).update(name="Alpha")

    state(
        game.game,
        owned_library,
        EditionState(key="edition-0", edition=game.edition, name="Beta"),
        EditionState(key="edition-1", edition=beta, name="Alpha", is_default=True),
    )

    game.edition.refresh_from_db()
    beta.refresh_from_db()
    assert (game.edition.name, beta.name) == ("Beta", "Alpha")


def test_the_default_edition_leaves_when_a_sibling_takes_the_mark(owned_library, game):
    """Today `DEFAULT_EDITION_HELD`; the statement carries the answer."""
    sibling = Edition.objects.create(game=game.game, name="Sibling")

    state(
        game.game,
        owned_library,
        EditionState(key="edition-0", edition=game.edition, removed=True),
        EditionState(key="edition-1", edition=sibling, name="Sibling", is_default=True),
    )

    game.edition.refresh_from_db()
    sibling.refresh_from_db()
    assert game.edition.removed_at is not None
    assert sibling.is_default is True


def test_the_default_release_leaves_when_a_sibling_takes_the_mark(owned_library, game):
    sibling = Release.objects.create(edition=game.edition, is_default=False)

    state(
        game.game,
        owned_library,
        one(
            edition=game.edition,
            releases=(
                ReleaseState(
                    key="edition-0-release-0", release=game.release, removed=True
                ),
                ReleaseState(
                    key="edition-0-release-1", release=sibling, is_default=True
                ),
            ),
        ),
    )

    game.release.refresh_from_db()
    sibling.refresh_from_db()
    assert game.release.removed_at is not None
    assert sibling.is_default is True


def test_a_removed_edition_keeps_its_releases(owned_library, game):
    """Each read tests its ancestors' marks, so restoring brings them back."""
    sibling = Edition.objects.create(game=game.game, name="Sibling")
    Release.objects.create(edition=sibling)

    state(
        game.game,
        owned_library,
        EditionState(key="edition-0", edition=game.edition, is_default=True),
        EditionState(key="edition-1", edition=sibling, name="Sibling", removed=True),
    )

    assert Release.objects.filter(edition=sibling, removed_at__isnull=True).count() == 1


def test_a_row_nobody_mentions_is_left_alone(owned_library, game):
    """Absence is not removal: #782's importer states what it knows."""
    untouched = Edition.objects.create(game=game.game, name="Untouched")

    state(game.game, owned_library, one(edition=game.edition, name="Stated"))

    untouched.refresh_from_db()
    assert untouched.removed_at is None
    assert untouched.name == "Untouched"


def test_the_first_surviving_row_takes_an_unstated_mark(owned_library, game):
    """Nothing standing and nothing stated: the first row takes it."""
    written = state(
        game.game,
        owned_library,
        EditionState(key="edition-0", edition=game.edition, removed=True),
        EditionState(
            key="edition-1",
            releases=(ReleaseState(key="edition-1-release-0"),),
        ),
        EditionState(key="edition-2", name="Second"),
    )

    first = written.editions[0]
    assert first.edition.is_default is True
    assert first.releases[0].release.is_default is True
    assert written.editions[1].edition.is_default is False


def test_an_unstated_mark_leaves_the_standing_default_where_it_is(owned_library, game):
    """A partial statement does not move a mark it says nothing about."""
    sibling = Edition.objects.create(game=game.game, name="Sibling")

    state(
        game.game,
        owned_library,
        EditionState(key="edition-0", edition=sibling, name="Sibling"),
    )

    game.edition.refresh_from_db()
    sibling.refresh_from_db()
    assert (game.edition.is_default, sibling.is_default) == (True, False)


def test_the_written_graph_hands_every_row_back_under_its_key(owned_library, game):
    written = state(
        game.game,
        owned_library,
        one(
            edition=game.edition,
            releases=(
                ReleaseState(
                    key="edition-0-release-0", release=game.release, is_default=True
                ),
                ReleaseState(key="edition-0-release-1"),
            ),
        ),
    )

    entry = written.editions[0]
    assert written.game.pk == game.game.pk
    assert entry.key == "edition-0"
    assert entry.edition.pk == game.edition.pk
    assert [key for key, _ in entry.releases] == [
        "edition-0-release-0",
        "edition-0-release-1",
    ]


def test_a_removed_row_is_not_handed_back(owned_library, game):
    sibling = Release.objects.create(edition=game.edition)

    written = state(
        game.game,
        owned_library,
        one(
            edition=game.edition,
            releases=(
                ReleaseState(
                    key="edition-0-release-0", release=game.release, is_default=True
                ),
                ReleaseState(key="edition-0-release-1", release=sibling, removed=True),
            ),
        ),
    )

    assert [key for key, _ in written.editions[0].releases] == ["edition-0-release-0"]


def test_a_stated_removal_of_a_row_already_gone_is_satisfied(owned_library, game):
    """The end state is what a statement names, and it is already true."""
    sibling = Release.objects.create(edition=game.edition)
    remove(sibling)
    sibling.refresh_from_db()
    stamped = sibling.removed_at

    state(
        game.game,
        owned_library,
        one(
            edition=game.edition,
            releases=(
                ReleaseState(
                    key="edition-0-release-0", release=game.release, is_default=True
                ),
                ReleaseState(key="edition-0-release-1", release=sibling, removed=True),
            ),
        ),
    )

    sibling.refresh_from_db()
    assert sibling.removed_at == stamped


def test_a_stated_removal_of_an_edition_already_gone_is_satisfied(owned_library, game):
    sibling = Edition.objects.create(game=game.game, name="Sibling")
    remove(sibling)
    sibling.refresh_from_db()
    stamped = sibling.removed_at

    state(
        game.game,
        owned_library,
        one(edition=game.edition),
        EditionState(key="edition-1", edition=sibling, name="Sibling", removed=True),
    )

    sibling.refresh_from_db()
    assert sibling.removed_at == stamped


def test_a_removed_edition_s_removed_release_goes_out_with_it(owned_library, game):
    """Putting the Edition back brings back only the rows nobody removed."""
    sibling = Edition.objects.create(game=game.game, name="Sibling")
    kept = Release.objects.create(edition=sibling)
    going = Release.objects.create(edition=sibling)

    state(
        game.game,
        owned_library,
        one(edition=game.edition),
        EditionState(
            key="edition-1",
            edition=sibling,
            name="Sibling",
            removed=True,
            releases=(
                ReleaseState(key="edition-1-release-0", release=kept),
                ReleaseState(key="edition-1-release-1", release=going, removed=True),
            ),
        ),
    )

    kept.refresh_from_db()
    going.refresh_from_db()
    assert (kept.removed_at, going.removed_at is None) == (None, False)


def test_two_states_may_not_name_one_stored_edition(owned_library, game):
    with pytest.raises(GraphRefused) as refused:
        state(
            game.game,
            owned_library,
            one(edition=game.edition, name="First"),
            one(key="edition-1", edition=game.edition, name="Second", is_default=False),
        )

    assert REPEATED_ROW in refused.value.messages
    assert refused.value.key == "edition-1"


def test_two_states_may_not_name_one_stored_release(owned_library, game):
    with pytest.raises(GraphRefused) as refused:
        state(
            game.game,
            owned_library,
            one(
                edition=game.edition,
                releases=(
                    ReleaseState(
                        key="edition-0-release-0", release=game.release, is_default=True
                    ),
                    ReleaseState(key="edition-0-release-1", release=game.release),
                ),
            ),
        )

    assert REPEATED_ROW in refused.value.messages
    assert refused.value.key == "edition-0-release-1"


def test_a_statement_wide_refusal_names_no_row(owned_library, game):
    """A caller shows it above the rows, rather than raising a page."""
    remove(game.game)

    with pytest.raises(GraphRefused) as refused:
        state(game.game, owned_library, one(edition=game.edition))

    assert REMOVED_GAME in refused.value.messages
    assert refused.value.key is None
