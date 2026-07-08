from django.contrib.auth import get_user_model
from django.test import Client, SimpleTestCase, TestCase, override_settings

from games.dev_login import prefill_credentials


class PrefillCredentialsTest(SimpleTestCase):
    @override_settings(DEV_LOGIN_PREFILL="admin:secret")
    def test_valid_pair(self):
        self.assertEqual(prefill_credentials(), ("admin", "secret"))

    @override_settings(DEV_LOGIN_PREFILL="")
    def test_empty_is_off(self):
        self.assertIsNone(prefill_credentials())

    @override_settings(DEV_LOGIN_PREFILL="nocolon")
    def test_missing_colon_is_off(self):
        self.assertIsNone(prefill_credentials())

    @override_settings(DEV_LOGIN_PREFILL=":secret")
    def test_empty_username_is_off(self):
        self.assertIsNone(prefill_credentials())

    @override_settings(DEV_LOGIN_PREFILL="admin:")
    def test_empty_password_is_off(self):
        self.assertIsNone(prefill_credentials())

    @override_settings(DEV_LOGIN_PREFILL="admin:a:b")
    def test_splits_on_first_colon_only(self):
        self.assertEqual(prefill_credentials(), ("admin", "a:b"))


class LoginPrefillViewTest(TestCase):
    @override_settings(DEV_LOGIN_PREFILL="admin:admin")
    def test_prefills_username_and_password_and_sets_noindex(self):
        response = Client().get("/login/")
        html = response.content.decode()
        # username input + password input both carry value="admin"
        self.assertEqual(html.count('value="admin"'), 2)
        self.assertEqual(response["X-Robots-Tag"], "noindex")

    @override_settings(DEV_LOGIN_PREFILL="")
    def test_off_renders_no_password_value_and_no_header(self):
        response = Client().get("/login/")
        html = response.content.decode()
        # password field present but with no value attribute, and no username value
        self.assertIn('type="password"', html)
        self.assertNotIn('value="admin"', html)
        self.assertNotIn("X-Robots-Tag", response)

    @override_settings(DEV_LOGIN_PREFILL='admin:a"><img src=x onerror=alert(1)>')
    def test_prefill_value_is_html_escaped(self):
        html = Client().get("/login/").content.decode()
        # the raw injection must not appear unescaped
        self.assertNotIn("<img src=x", html)

    @override_settings(DEV_LOGIN_PREFILL="admin:admin")
    def test_post_still_authenticates(self):
        get_user_model().objects.create_superuser("admin", "", "admin")
        client = Client()
        response = client.post("/login/", {"username": "admin", "password": "admin"})
        self.assertEqual(response.status_code, 302)  # redirect on success
        self.assertIn("_auth_user_id", client.session)
