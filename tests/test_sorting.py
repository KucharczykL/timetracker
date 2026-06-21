"""Tests for the list-view sorting system (games/sorting.py)."""

from games.sorting import SortSpec, SortTerm, parse_sort_terms

# A minimal map; parse_sort_terms only checks key membership, not spec internals.
SAMPLE_MAP = {"name": SortSpec("name"), "date": SortSpec("created_at")}


class TestParseSortTerms:
    def test_bare_key_is_ascending(self):
        parsed = parse_sort_terms("name", SAMPLE_MAP)
        assert parsed.terms == [SortTerm("name", False)]
        assert parsed.unknown == []

    def test_dash_prefix_is_descending(self):
        parsed = parse_sort_terms("-date", SAMPLE_MAP)
        assert parsed.terms == [SortTerm("date", True)]

    def test_multi_column_preserves_order(self):
        parsed = parse_sort_terms("date,-name", SAMPLE_MAP)
        assert parsed.terms == [SortTerm("date", False), SortTerm("name", True)]

    def test_unknown_key_is_reported_not_raised(self):
        parsed = parse_sort_terms("bogus", SAMPLE_MAP)
        assert parsed.terms == []
        assert parsed.unknown == ["bogus"]

    def test_mixed_valid_and_unknown(self):
        parsed = parse_sort_terms("-name,bogus", SAMPLE_MAP)
        assert parsed.terms == [SortTerm("name", True)]
        assert parsed.unknown == ["bogus"]

    def test_whitespace_and_empty_tokens_ignored(self):
        parsed = parse_sort_terms(" name , , -date ", SAMPLE_MAP)
        assert parsed.terms == [SortTerm("name", False), SortTerm("date", True)]

    def test_empty_string_yields_nothing(self):
        parsed = parse_sort_terms("", SAMPLE_MAP)
        assert parsed.terms == []
        assert parsed.unknown == []
