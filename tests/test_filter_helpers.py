"""Unit tests for filter JSON parsing helpers."""

from django.test import SimpleTestCase

from common.components.filters import _parse_range, _parse_bool_nullable


class ParseRangeTest(SimpleTestCase):
    def test_empty_dict(self):
        self.assertEqual(_parse_range({}, "field"), ("", ""))

    def test_missing_key(self):
        self.assertEqual(_parse_range({"other": 1}, "field"), ("", ""))

    def test_null_value(self):
        self.assertEqual(_parse_range({"field": None}, "field"), ("", ""))

    def test_non_dict_value(self):
        """A non-dict field value is coerced to ("", "")."""
        self.assertEqual(_parse_range({"field": "not_a_dict"}, "field"), ("", ""))

    def test_value_only(self):
        self.assertEqual(_parse_range({"field": {"value": "10"}}, "field"), ("10", ""))

    def test_value_and_value2(self):
        self.assertEqual(
            _parse_range({"field": {"value": "10", "value2": "20"}}, "field"),
            ("10", "20"),
        )

    def test_empty_strings(self):
        self.assertEqual(
            _parse_range({"field": {"value": "", "value2": ""}}, "field"), ("", "")
        )

    def test_integer_values_become_strings(self):
        self.assertEqual(
            _parse_range({"field": {"value": 5, "value2": 15}}, "field"),
            ("5", "15"),
        )


class ParseBoolNullableTest(SimpleTestCase):
    def test_missing_key(self):
        self.assertIsNone(_parse_bool_nullable({}, "field"))

    def test_null_value(self):
        self.assertIsNone(_parse_bool_nullable({"field": None}, "field"))
        self.assertIsNone(_parse_bool_nullable({"field": {}}, "field"))

    def test_boolean_values(self):
        self.assertTrue(_parse_bool_nullable({"field": {"value": True}}, "field"))
        self.assertFalse(_parse_bool_nullable({"field": {"value": False}}, "field"))

    def test_string_values(self):
        self.assertTrue(_parse_bool_nullable({"field": {"value": "true"}}, "field"))
        self.assertTrue(_parse_bool_nullable({"field": {"value": "1"}}, "field"))
        self.assertFalse(_parse_bool_nullable({"field": {"value": "false"}}, "field"))
        self.assertFalse(_parse_bool_nullable({"field": {"value": "0"}}, "field"))
