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
        # password field present but with NO value= attribute at all
        self.assertIn('type="password"', html)
        # Extract the password <input> tag and assert it has no value= attribute.
        import re

        password_tag_match = re.search(r'<input[^>]*type="password"[^>]*>', html)
        self.assertIsNotNone(password_tag_match, "password input tag not found")
        password_tag = password_tag_match.group(0)
        self.assertNotIn("value=", password_tag)
        self.assertNotIn("X-Robots-Tag", response)

    @override_settings(DEV_LOGIN_PREFILL='admin:a"><img src=x onerror=alert(1)>')
    def test_prefill_value_is_html_escaped(self):
        html = Client().get("/login/").content.decode()
        # the raw injection must not appear unescaped
        self.assertNotIn("<img src=x", html)
        # but the payload WAS rendered (in escaped form) — prove it
        self.assertIn("onerror=alert(1)", html)

    @override_settings(DEV_LOGIN_PREFILL="admin:admin")
    def test_post_still_authenticates(self):
        get_user_model().objects.create_superuser("admin", "", "admin")
        client = Client()
        response = client.post("/login/", {"username": "admin", "password": "admin"})
        self.assertEqual(response.status_code, 302)  # redirect on success
        self.assertIn("_auth_user_id", client.session)


from django.core.management import call_command


class DevLoginCommandTest(TestCase):
    def test_creates_usable_superuser_idempotently(self):
        call_command("devlogin")
        call_command("devlogin")  # second run must not error
        User = get_user_model()
        user = User.objects.get(username="admin")
        self.assertTrue(user.is_superuser)
        self.assertTrue(Client().login(username="admin", password="admin"))

    @override_settings(DEV_LOGIN_PREFILL="dev:pw")
    def test_uses_prefill_credentials_when_set(self):
        call_command("devlogin")
        self.assertTrue(Client().login(username="dev", password="pw"))
