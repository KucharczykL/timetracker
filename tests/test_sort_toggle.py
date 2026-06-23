"""Pure-logic tests for the clickable-header sort targets (issue #73)."""

from common.sorting import SortTerm, collapse_sort, cycle_sort


def term(key: str, descending: bool = False) -> SortTerm:
    return SortTerm(key, descending)


class TestCollapseSort:
    """Plain-click: collapse to a single column, asc-first, flip-on-repeat."""

    def test_inactive_key_sorts_ascending(self):
        assert collapse_sort([term("created", True)], "name") == "name"

    def test_no_active_sorts_ascending(self):
        assert collapse_sort([], "name") == "name"

    def test_sole_ascending_flips_to_descending(self):
        assert collapse_sort([term("name")], "name") == "-name"

    def test_sole_descending_flips_to_ascending(self):
        assert collapse_sort([term("name", True)], "name") == "name"

    def test_secondary_term_collapses_to_ascending(self):
        # key active but not sole (multi-column) → collapse to just key asc
        active = [term("status"), term("name", True)]
        assert collapse_sort(active, "name") == "name"


class TestCycleSort:
    """Shift-click: append-at-end / flip-in-place / remove."""

    def test_absent_appends_ascending_at_end(self):
        assert cycle_sort([term("status")], "name") == "status,name"

    def test_appends_after_existing_terms_preserving_order(self):
        active = [term("status", True), term("year")]
        assert cycle_sort(active, "name") == "-status,year,name"

    def test_ascending_flips_in_place(self):
        active = [term("status"), term("name")]
        assert cycle_sort(active, "status") == "-status,name"

    def test_descending_removes_keeping_others(self):
        active = [term("status", True), term("name")]
        assert cycle_sort(active, "status") == "name"

    def test_removing_last_term_yields_empty(self):
        assert cycle_sort([term("name", True)], "name") == ""

    def test_full_cycle_absent_asc_desc_removed(self):
        active: list[SortTerm] = []
        after_add = cycle_sort(active, "name")
        assert after_add == "name"
        after_flip = cycle_sort([term("name")], "name")
        assert after_flip == "-name"
        after_remove = cycle_sort([term("name", True)], "name")
        assert after_remove == ""
