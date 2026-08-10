"""The deliberately small regex dialect shared by Python and PostgreSQL."""

import re
from collections.abc import Iterable
from itertools import pairwise
from re import _constants as re_constants  # type: ignore[attr-defined]
from re import _parser as re_parser  # type: ignore[attr-defined]
from typing import Any, NoReturn

MAX_REGEX_PATTERN_LENGTH = 200
MAX_BOUNDED_REPEAT = 255


class RegexPatternError(ValueError):
    """A regex outside the supported cross-database subset."""


class _Parser:
    def __init__(self, pattern: str):
        self.pattern = pattern
        self.index = 0

    def parse(self) -> None:
        self._expression(end=None)
        if self.index != len(self.pattern):
            self._error("unexpected syntax")

    def _expression(self, end: str | None) -> None:
        self._sequence(end)
        while self._peek() == "|":
            self.index += 1
            self._sequence(end)

    def _sequence(self, end: str | None) -> None:
        if self._peek() in (None, "|", end):
            self._error("empty alternatives are not supported")
        while self._peek() not in (None, "|", end):
            self._atom()
            self._quantifier()

    def _atom(self) -> None:
        token = self._peek()
        if token == "(":
            self.index += 1
            self._expression(end=")")
            if self._peek() != ")":
                self._error("unclosed group")
            self.index += 1
            return
        if token == "[":
            self._character_class()
            return
        if token == "\\":
            self.index += 1
            escaped = self._peek()
            if escaped is None or escaped not in ".*+?()[]{}|\\":
                self._error("unsupported escape")
            self.index += 1
            return
        if token is None or token in ".^$*+?)]}{|":
            self._error("unsupported regex syntax")
        self.index += 1

    def _character_class(self) -> None:
        self.index += 1
        if self._peek() == "^":
            self.index += 1
        start = self.index
        characters: list[str] = []
        while self._peek() not in (None, "]"):
            token = self._peek()
            if token is None:
                self._error("unclosed character class")
            if not token.isascii() or not (token.isalnum() or token in " _-"):
                self._error("unsupported character class")
            characters.append(token)
            self.index += 1
        if self.index == start or self._peek() != "]":
            self._error("unclosed or empty character class")
        range_hyphens: list[int] = []
        for index, token in enumerate(characters):
            if token != "-" or index in (0, len(characters) - 1):
                continue
            if (
                not characters[index - 1].isalnum()
                or not characters[index + 1].isalnum()
            ):
                self._error("ambiguous character class range")
            range_hyphens.append(index)
        if any(right - left <= 2 for left, right in pairwise(range_hyphens)):
            self._error("ambiguous character class range")
        self.index += 1

    def _quantifier(self) -> None:
        token = self._peek()
        if token is not None and token in ("*", "+", "?"):
            self.index += 1
        elif token == "{":
            self.index += 1
            minimum = self._number()
            if self._peek() == "}":
                self.index += 1
                maximum = minimum
            elif self._peek() == ",":
                self.index += 1
                if self._peek() == "}":
                    self._error("unbounded repetitions are not supported")
                maximum = self._number()
                if self._peek() != "}":
                    self._error("malformed repetition")
                self.index += 1
            else:
                self._error("malformed repetition")
            if minimum > maximum or maximum > MAX_BOUNDED_REPEAT:
                self._error("invalid repetition bounds")
        if self._peek() in ("*", "+", "?", "{"):
            self._error("repeated quantifiers are not supported")

    def _number(self) -> int:
        start = self.index
        while (token := self._peek()) is not None and token.isdecimal():
            self.index += 1
        if start == self.index:
            self._error("missing repetition bound")
        return int(self.pattern[start : self.index])

    def _peek(self) -> str | None:
        if self.index == len(self.pattern):
            return None
        return self.pattern[self.index]

    def _error(self, message: str) -> NoReturn:
        raise RegexPatternError(message)


RegexTokens = Iterable[Any]
_REPEAT_OPS = (re_constants.MAX_REPEAT, re_constants.MIN_REPEAT)


def _sub_sequences(opcode: Any, args: Any) -> Iterable[RegexTokens]:
    if opcode in _REPEAT_OPS:
        yield args[2]
    elif opcode is re_constants.SUBPATTERN:
        yield args[3]
    elif opcode is re_constants.BRANCH:
        yield from args[1]
    elif opcode in (re_constants.ASSERT, re_constants.ASSERT_NOT):
        yield args[1]
    elif opcode is re_constants.ATOMIC_GROUP:
        yield args


def _contains_unbounded_repeat(tokens: RegexTokens) -> bool:
    return any(
        (opcode in _REPEAT_OPS and args[1] == re_constants.MAXREPEAT)
        or any(
            _contains_unbounded_repeat(child) for child in _sub_sequences(opcode, args)
        )
        for opcode, args in tokens
    )


def _has_nested_unbounded_repeat(tokens: RegexTokens) -> bool:
    return any(
        (
            opcode in _REPEAT_OPS
            and args[1] == re_constants.MAXREPEAT
            and _contains_unbounded_repeat(args[2])
        )
        or any(
            _has_nested_unbounded_repeat(child)
            for child in _sub_sequences(opcode, args)
        )
        for opcode, args in tokens
    )


def validate_regex_pattern(pattern: Any) -> None:
    """Reject syntax with no deliberately shared Python/PostgreSQL meaning."""
    if not isinstance(pattern, str):
        raise RegexPatternError(f"expected a regex string, got {pattern!r}")
    if len(pattern) > MAX_REGEX_PATTERN_LENGTH:
        raise RegexPatternError(
            f"regex pattern too long (max {MAX_REGEX_PATTERN_LENGTH} chars)"
        )
    if not pattern:
        raise RegexPatternError("empty regex patterns are not supported")
    _Parser(pattern).parse()
    try:
        parsed = re_parser.parse(pattern)
    except re.error as exc:
        raise RegexPatternError(f"invalid regex pattern: {exc}") from exc
    if _has_nested_unbounded_repeat(parsed):
        raise RegexPatternError("regex pattern is too complex (nested quantifiers)")
