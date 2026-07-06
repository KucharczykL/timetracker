"""Unit tests for filter criterion-blob parsing helpers (the ``_*_from_field``
layer ``field_widget`` prefills widgets from)."""

from django.test import SimpleTestCase

from common.components.filters import _bool_from_field, _range_from_field


class RangeFromFieldTest(SimpleTestCase):
    def test_non_dict_value(self):
        """A non-dict criterion blob is coerced to ("", "")."""
        self.assertEqual(_range_from_field("not_a_dict"), ("", ""))  # type: ignore[arg-type]
        self.assertEqual(_range_from_field(None), ("", ""))  # type: ignore[arg-type]

    def test_empty_dict(self):
        self.assertEqual(_range_from_field({}), ("", ""))

    def test_value_only(self):
        self.assertEqual(_range_from_field({"value": "10"}), ("10", ""))

    def test_value_and_value2(self):
        self.assertEqual(
            _range_from_field({"value": "10", "value2": "20"}), ("10", "20")
        )

    def test_less_than_maps_to_max(self):
        self.assertEqual(
            _range_from_field({"value": "10", "modifier": "LESS_THAN"}), ("", "10")
        )

    def test_integer_values_become_strings(self):
        self.assertEqual(_range_from_field({"value": 5, "value2": 15}), ("5", "15"))


class BoolFromFieldTest(SimpleTestCase):
    def test_missing_or_null(self):
        self.assertIsNone(_bool_from_field("not_a_dict"))  # type: ignore[arg-type]
        self.assertIsNone(_bool_from_field({}))
        self.assertIsNone(_bool_from_field({"value": None}))

    def test_boolean_values(self):
        self.assertTrue(_bool_from_field({"value": True}))
        self.assertFalse(_bool_from_field({"value": False}))

    def test_string_values(self):
        self.assertTrue(_bool_from_field({"value": "true"}))
        self.assertTrue(_bool_from_field({"value": "1"}))
        self.assertFalse(_bool_from_field({"value": "false"}))
        self.assertFalse(_bool_from_field({"value": "0"}))
