"""Which tables a SQL statement writes, read from its text."""

import re

type TableName = str  # e.g. "games_playergame"

#: A statement opening with these writes.
_WRITE_KEYWORDS = frozenset({"INSERT", "UPDATE", "DELETE", "COPY", "TRUNCATE", "MERGE"})

#: A CTE hides its writes behind the first keyword.
_CTE_KEYWORD = "WITH"

#: Whitespace and comments before the first keyword.
_LEADING_NOISE = re.compile(r"(?:\s|/\*.*?\*/|--[^\n]*(?:\n|$))*", re.DOTALL)

#: The first word of a statement.
_KEYWORD = re.compile(r"\w+")

#: The first identifier: the table written.
_WRITE_TARGET = re.compile(
    r"""
    \b
    (?: INSERT \s+ INTO
      | UPDATE
      | DELETE \s+ FROM
      | TRUNCATE (?: \s+ TABLE )?
      | COPY
      | MERGE \s+ INTO
    )
    \s+ (?: ONLY \s+ )?
    (?P<table> [^\s(]+ )
    """,
    re.IGNORECASE | re.VERBOSE,
)

#: One identifier, quoted or bare, optionally schema-qualified.
_IDENTIFIER = r'(?:"(?:[^"]|"")+"|\w+)'
_QUALIFIED_NAME = re.compile(rf"{_IDENTIFIER}(?:\s*\.\s*{_IDENTIFIER})?")

#: A whole `TRUNCATE` list; anything the list does not cover is unreadable.
_TRUNCATE = re.compile(
    rf"""
    TRUNCATE
    (?: \s+ TABLE )?
    (?: \s+ ONLY )?
    \s+
    (?P<tables> {_QUALIFIED_NAME.pattern} \s* \*?
                (?: \s* , \s* {_QUALIFIED_NAME.pattern} \s* \*? )* )
    (?: \s+ (?P<behaviour> CASCADE | RESTRICT ) )?
    \s* ;? \s*
    """,
    re.IGNORECASE | re.VERBOSE,
)


def write_targets(statement: str) -> tuple[TableName, ...]:
    """Every table written; unreadable means refused.

    Public because the benchmark counts the same statements the guards
    refuse, and two parsers for one job would drift.
    """
    leading = _LEADING_NOISE.match(statement)
    start = leading.end() if leading is not None else 0
    keyword = _KEYWORD.match(statement, start)
    word = keyword.group(0).upper() if keyword is not None else ""
    if word == _CTE_KEYWORD:
        #: The scan is slow; most CTEs only read.
        upper = statement.upper()
        if not any(keyword in upper for keyword in _WRITE_KEYWORDS):
            return ()
        return tuple(
            _bare_name(match["table"])
            for match in _WRITE_TARGET.finditer(statement, start)
        )
    if word == "TRUNCATE":
        return _truncate_targets(statement, start)
    if word not in _WRITE_KEYWORDS:
        return ()
    match = _WRITE_TARGET.match(statement, start)
    if match is None:
        return ("",)
    return (_bare_name(match["table"]),)


def _truncate_targets(statement: str, start: int) -> tuple[TableName, ...]:
    """Every name in a `TRUNCATE` list; `CASCADE` empties tables unnamed."""
    match = _TRUNCATE.fullmatch(statement, start)
    if match is None:
        return ("",)
    if (match["behaviour"] or "").upper() == "CASCADE":
        return ("",)
    return tuple(_bare_name(name) for name in _QUALIFIED_NAME.findall(match["tables"]))


def _bare_name(identifier: str) -> TableName:
    """`pg_temp."Games_X__shadow";` -> `games_x__shadow`.

    Lower case: PostgreSQL lowers an unquoted name, so both spellings name
    one table.
    """
    return identifier.rsplit(".", maxsplit=1)[-1].rstrip(";").strip('"').lower()
