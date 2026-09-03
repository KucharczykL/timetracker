"""What two names have to share to be one name.

The database compares an Edition name by `Lower(Trim(name))`, and
`Platform.clean` compares two Platforms the same way. `str.casefold()`
is not that function — it reads `Straße` and `STRASSE` as one name
where the database reads two — so every side states the key here.

One character is beyond the key. `str.lower()` states the full case
mapping and the `builtin` provider the simple one, so `İ` reads as
`i` and a combining dot here and as a bare `i` there. Nothing in
Python states the provider's mapping, and `tests/test_name_key.py`
holds the difference as a strict xfail rather than as a silence.
"""

#: The comparison form of a name, never stored and never shown.
type NameKey = str


def name_key(value: str) -> NameKey:
    """What the database compares two names by."""
    return value.strip().lower()
