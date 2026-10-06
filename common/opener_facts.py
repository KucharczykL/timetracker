"""Opener-stated facts, fixed instead of asked."""

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, ClassVar, Protocol, cast, runtime_checkable

from django import forms
from django.core.exceptions import ValidationError
from django.forms.utils import pretty_name
from django.http import QueryDict
from django.utils.choices import flatten_choices

from timetracker.uuidv7 import UUIDv7ParseError, parse_uuidv7

logger = logging.getLogger("games.opener_facts")

type FieldName = str  # "game"
type Statement = str  # "Main game"
type RefusalSentence = str  # "The link named a game … Pick one."
#: Keyed by prefixed html name, e.g. "library-add-game".
type OpenerFacts = Mapping[str, str] | QueryDict

LOGGED_VALUE_LENGTH = 80


@dataclass(frozen=True, slots=True)
class Fixed:
    """A field fixed to ``value``."""

    value: object
    #: None: implied, no row.
    statement: Statement | None


@dataclass(frozen=True, slots=True)
class Refused:
    """A fact the form could not use."""

    sentence: RefusalSentence


type FactState = Fixed | Refused
type FormFacts = Mapping[FieldName, FactState]


@runtime_checkable
class StatesFacts(Protocol):
    """What ``FormFields`` reads off a form."""

    @property
    def facts(self) -> FormFacts: ...


def form_facts(form: forms.BaseForm) -> FormFacts:
    """A form's facts; none without the mixin."""
    return form.facts if isinstance(form, StatesFacts) else {}


def refusal_sentence(label: str) -> RefusalSentence:
    """The sentence after a refused fact's control."""
    return f"The link named a {label.lower()} this form cannot use. Pick one."


class OpenerFactsMixin(forms.BaseForm):
    """Fix the declared fields an opener's query names."""

    opener_fields: ClassVar[tuple[FieldName, ...]] = ()

    _facts: dict[FieldName, FactState]
    _facts_read: bool
    _bound_fields_cache: dict[str, forms.BoundField]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._facts = {}
        self._facts_read = False
        super().__init__(*args, **kwargs)

    @property
    def facts(self) -> FormFacts:
        return MappingProxyType(self._facts)

    def stated[T](self, name: FieldName, kind: type[T]) -> T | None:
        """The fixed value of ``name``, if fixed."""
        fact = self._facts.get(name)
        if not isinstance(fact, Fixed):
            return None
        if not isinstance(fact.value, kind):
            raise TypeError(
                f"{type(self).__name__}.{name} holds {type(fact.value).__name__}, "
                f"not {kind.__name__}."
            )
        return fact.value

    def state_opener_facts(self, facts: OpenerFacts | None) -> None:
        """Call once fields are built, before any ``self[name]``."""
        if self._facts_read:
            raise RuntimeError(f"{type(self).__name__} read its facts twice.")
        self._facts_read = True
        if facts is None:
            return
        for name in self.opener_fields:
            if name in self._bound_fields_cache:
                raise RuntimeError(
                    f"{type(self).__name__}.{name} was read before its "
                    "opener fact; its BoundField caches the old initial."
                )
            key = self.add_prefix(name)
            if key not in facts:
                continue
            values = (
                facts.getlist(key) if isinstance(facts, QueryDict) else [facts[key]]
            )
            self._state_one(name, values)

    def fix_field(
        self, name: FieldName, value: object, *, statement: Statement | None = None
    ) -> None:
        """Fix ``name``; no statement, no row."""
        self.initial[name] = value
        self.fields[name].disabled = True
        self._facts[name] = Fixed(value, statement)

    def _state_one(self, name: FieldName, values: list[str]) -> None:
        field = self.fields[name]
        #: Empty or repeated: malformed.
        raw = values[0] if len(values) == 1 else ""
        if not raw:
            self._refuse(name, values, "is malformed")
            return
        if isinstance(field, forms.ModelChoiceField):
            self._state_row(name, field, raw)
            return
        try:
            value = field.clean(raw)
        except ValidationError:
            self._refuse(name, raw, "is malformed")
            return
        self.fix_field(name, value, statement=_choice_statement(field, raw, value))

    def _state_row(
        self, name: FieldName, field: forms.ModelChoiceField, raw: str
    ) -> None:
        try:
            key = parse_uuidv7(raw)
        except UUIDv7ParseError:
            self._refuse(name, raw, "is malformed")
            return
        if field.queryset is None:
            raise RuntimeError(f"{type(self).__name__}.{name} has no queryset.")
        row = field.queryset.filter(pk=key).first()
        if row is None:
            self._refuse(name, raw, "names no row this form offers")
            return
        self.fix_field(name, row, statement=field.label_from_instance(row))

    def _refuse(self, name: FieldName, raw: object, reason: str) -> None:
        logger.warning(
            "Opener fact %s.%s=%s %s.",
            type(self).__name__,
            name,
            repr(raw)[:LOGGED_VALUE_LENGTH],
            reason,
        )
        label = str(self.fields[name].label or pretty_name(name))
        self._facts[name] = Refused(refusal_sentence(label))


def _choice_statement(field: forms.Field, raw: str, value: object) -> Statement:
    if isinstance(field, forms.ChoiceField):
        pairs: list[tuple[object, object]] = list(
            flatten_choices(cast(Any, field.choices))
        )
        labels = {str(key): str(label) for key, label in pairs}
        return str(labels.get(raw, value))
    return str(value)
