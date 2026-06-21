import unittest

from common.utils import label_with_details


class LabelWithDetailsTest(unittest.TestCase):
    def test_all_parts_present(self):
        self.assertEqual(
            label_with_details("Mario", "Steam", 2020), "Mario (Steam, 2020)"
        )

    def test_some_parts_falsy(self):
        self.assertEqual(label_with_details("Mario", None, 2020), "Mario (2020)")
        self.assertEqual(label_with_details("Mario", "Steam", None), "Mario (Steam)")

    def test_all_parts_falsy(self):
        self.assertEqual(label_with_details("Mario", None, "", 0), "Mario")

    def test_no_details(self):
        self.assertEqual(label_with_details("Mario"), "Mario")

    def test_custom_separator(self):
        self.assertEqual(
            label_with_details("Mario", "a", "b", separator=" / "), "Mario (a / b)"
        )
