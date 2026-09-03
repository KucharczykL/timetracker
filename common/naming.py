"""What two names have to share to be one name.

The database compares an Edition name by `Lower(Trim(name))`, and
`Platform.clean` compares two Platforms the same way. `str.casefold()`
is not that function — it reads `Straße` and `STRASSE` as one name
where the database reads two — so every side states the key here.
"""

#: The comparison form of a name, never stored and never shown.
type NameKey = str


def name_key(value: str) -> NameKey:
    """What the database compares two names by."""
    return value.strip().lower()
