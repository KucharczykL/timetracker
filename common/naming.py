"""What two names have to share to be one name.

The database compares an Edition name by `Lower(Trim(name))`, and
`Platform.clean` compares two Platforms the same way. `str.casefold()`
is not that function — it reads `Straße` and `STRASSE` as one name
where the database reads two — so every side states the key here.

One character is beyond the key. `str.lower()` states the full case
mapping and the `builtin` provider the simple one, so `İ` reads two
ways. `tests/test_name_key.py` holds that as a strict xfail.
"""

#: What `Trim()` takes off: one ASCII space.
#:
#: It compiles to `btrim(value)`, whose default set is that one
#: character. Bare `strip()` takes every Unicode space with it, so
#: a name ending in a tab would key equal here and unequal there.
TRIMMED = " "

#: The comparison form of a name, never stored and never shown.
type NameKey = str


def name_key(value: str) -> NameKey:
    """What the database compares two names by."""
    return value.strip(TRIMMED).lower()
