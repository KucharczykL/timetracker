"""Unit tests for filter JSON parsing helpers."""

from django.test import SimpleTestCase

from common.components.filters import _parse_bool, _parse_range


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


class ParseBoolTest(SimpleTestCase):
    def test_empty_dict(self):
        self.assertFalse(_parse_bool({}, "field"))

    def test_missing_key(self):
        self.assertFalse(_parse_bool({"other": 1}, "field"))

    def test_null_value(self):
        self.assertFalse(_parse_bool({"field": None}, "field"))

    def test_non_dict_value(self):
        """A non-dict field value is coerced to False."""
        self.assertFalse(_parse_bool({"field": "not_a_dict"}, "field"))

    def test_false_value(self):
        self.assertFalse(_parse_bool({"field": {"value": False}}, "field"))

    def test_true_value(self):
        self.assertTrue(_parse_bool({"field": {"value": True}}, "field"))

    def test_truthy_string(self):
        """Non-empty strings are truthy — bool("yes") is True."""
        self.assertTrue(_parse_bool({"field": {"value": "yes"}}, "field"))

    def test_missing_value_in_field(self):
        self.assertFalse(_parse_bool({"field": {}}, "field"))
