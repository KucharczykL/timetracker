"""A refused confirmation says why, on the same page."""

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from games.views.removal import confirm_and_apply

pytestmark = pytest.mark.django_db

REFUSAL = "This edition is the last one."
SECOND_SENTENCE = "Reload the page and try again."


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


def test_a_refusal_keeps_every_sentence_it_carried(post_request):
    """`messages[0]` threw the rest away, and the join made it the question."""

    def refuse():
        raise ValidationError([REFUSAL, SECOND_SENTENCE])

    response = confirm_and_apply(
        post_request(),
        action=refuse,
        title="Remove edition",
        message="Remove it?",
        confirm_label="Remove",
        fallback="games:list_games",
    )
    body = response.content.decode()

    assert response.status_code == 409
    assert REFUSAL in body
    assert SECOND_SENTENCE in body
    assert f"{REFUSAL} Remove it?" not in body


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
