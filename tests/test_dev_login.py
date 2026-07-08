from django.test import SimpleTestCase, override_settings

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
