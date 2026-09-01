"""A refused confirmation says why, on the same page."""

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from games.views.removal import confirm_and_apply

pytestmark = pytest.mark.django_db

REFUSAL = "This edition is the last one."


@pytest.fixture
def post_request(rf):
    user = get_user_model().objects.create_user(username="refused", password="p")

    def post():
        request = rf.post("/anything/")
        request.user = user
        return request

    return post


def test_a_refused_action_re_renders_the_confirmation(post_request):
    def refuse():
        raise ValidationError(REFUSAL)

    response = confirm_and_apply(
        post_request(),
        action=refuse,
        title="Remove edition",
        message="Remove it?",
        confirm_label="Remove",
        fallback="games:list_games",
    )

    assert response.status_code == 409
    assert REFUSAL in response.content.decode()


def test_an_accepted_action_still_redirects(post_request):
    response = confirm_and_apply(
        post_request(),
        action=lambda: None,
        title="Remove edition",
        message="Remove it?",
        confirm_label="Remove",
        fallback="games:list_games",
    )

    assert response.status_code == 302
