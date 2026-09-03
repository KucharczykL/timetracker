"""A refused confirmation says why, on the same page."""

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from games.views.removal import confirm_and_apply
from games.writes.answers import CONFLICT_STATUS, CommandFailed

pytestmark = pytest.mark.django_db

REFUSAL = "This edition is the last one."
DEFECT = "This field is required."


@pytest.fixture
def post_request(rf):
    user = get_user_model().objects.create_user(username="refused", password="p")

    def post():
        request = rf.post("/anything/")
        request.user = user
        return request

    return post


def confirm(request, action):
    """One confirmation, so a test states only what it refuses with."""
    return confirm_and_apply(
        request,
        action=action,
        title="Remove edition",
        message="Remove it?",
        confirm_label="Remove",
        fallback="games:list_games",
    )


def test_a_refused_action_re_renders_the_confirmation(post_request):
    def refuse():
        raise CommandFailed(REFUSAL, CONFLICT_STATUS)

    response = confirm(post_request(), refuse)

    assert response.status_code == CONFLICT_STATUS
    assert REFUSAL in response.content.decode()


def test_the_refusal_stands_apart_from_the_question(post_request):
    """Joining the two made the reason read as the question itself."""

    def refuse():
        raise CommandFailed(REFUSAL, CONFLICT_STATUS)

    body = confirm(post_request(), refuse).content.decode()

    assert REFUSAL in body
    assert "Remove it?" in body
    assert f"{REFUSAL} Remove it?" not in body


def test_the_status_is_the_one_the_refusal_states(post_request):
    """A refusal carries its own, because the answers disagree."""

    def refuse():
        raise CommandFailed(REFUSAL, 422)

    assert confirm(post_request(), refuse).status_code == 422


def test_a_model_that_refuses_underneath_the_act_is_a_defect(post_request):
    """`_AFTER_STAMP` saves siblings, and one of those may `clean()`.

    Reading that as a refusal would state a form's field wording as
    the reason a removal was refused, and answer 409 for a defect.
    """

    def break_underneath():
        raise ValidationError(DEFECT)

    with pytest.raises(ValidationError):
        confirm(post_request(), break_underneath)


def test_an_accepted_action_still_redirects(post_request):
    assert confirm(post_request(), lambda: None).status_code == 302
