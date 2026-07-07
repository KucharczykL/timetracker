import unittest

from common.utils import label_with_details, paginate
from games.filters import FindFilter


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


class PaginateTest(unittest.TestCase):
    """paginate() slices any sliceable (a list here) via a resolved FindFilter."""

    def test_slices_to_per_page_and_reports_page(self):
        items = list(range(25))
        object_list, page_obj, elided = paginate(items, FindFilter(page=1, per_page=10))
        self.assertEqual(list(object_list), list(range(10)))
        assert page_obj is not None
        self.assertEqual(page_obj.number, 1)
        self.assertIsNotNone(elided)

    def test_per_page_zero_disables_pagination(self):
        items = list(range(25))
        object_list, page_obj, elided = paginate(items, FindFilter(per_page=0))
        self.assertEqual(list(object_list), items)
        self.assertIsNone(page_obj)
        self.assertIsNone(elided)

    def test_overshoot_page_clamps_to_last(self):
        items = list(range(25))
        _, page_obj, _ = paginate(items, FindFilter(page=999, per_page=10))
        assert page_obj is not None
        self.assertEqual(page_obj.number, page_obj.paginator.num_pages)
