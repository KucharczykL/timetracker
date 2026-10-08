"""The login form refuses a wrong password."""

from django.urls import reverse


def test_a_wrong_password_renders_the_refusal(client, django_user_model):
    django_user_model.objects.create_user(username="reader", password="right")

    response = client.post(
        reverse("login"), {"username": "reader", "password": "wrong"}
    )

    assert response.status_code == 200
    assert "Please enter a correct username and password" in response.content.decode()
    assert "_auth_user_id" not in client.session
