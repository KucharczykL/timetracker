import pytest
from django.db import IntegrityError, transaction

from games.models import Edition, Game, Release

pytestmark = pytest.mark.django_db


def test_default_markers_allow_one_default_and_multiple_nondefaults(owned_library):
    game = Game.objects.create(library=owned_library, name="Defaults")
    default_edition = Edition.objects.create(game=game, is_default=True)
    Edition.objects.create(game=game)
    Edition.objects.create(game=game)
    Release.objects.create(edition=default_edition, is_default=True)
    Release.objects.create(edition=default_edition)
    Release.objects.create(edition=default_edition)

    assert game.editions.filter(is_default=True).get() == default_edition
    assert default_edition.releases.filter(is_default=True).count() == 1
    assert Edition._meta.get_field("is_default").editable is False
    assert Release._meta.get_field("is_default").editable is False

    with pytest.raises(IntegrityError), transaction.atomic():
        Edition.objects.create(game=game, is_default=True)
    with pytest.raises(IntegrityError), transaction.atomic():
        Release.objects.create(edition=default_edition, is_default=True)
