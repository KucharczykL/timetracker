"""Opener-stated facts, fixed instead of asked."""

import logging
from collections.abc import Mapping
from typing import Any, ClassVar, cast

from django import forms
from django.core.exceptions import ValidationError
from django.forms.utils import pretty_name
from django.http import Http404, QueryDict
from django.utils.choices import flatten_choices

from timetracker.uuidv7 import UUIDv7ParseError, parse_uuidv7

logger = logging.getLogger("games.opener_facts")

type FieldName = str  # "game"
type Statement = str  # "Main game"
type RefusalSentence = str
type OpenerFacts = Mapping[str, str] | QueryDict

LOGGED_VALUE_LENGTH = 80


def refusal_sentence(label: str) -> RefusalSentence:
    """The sentence after a refused fact's control."""
    return f"The link named a {label.lower()} this form cannot use. Pick one."


class OpenerFactsMixin(forms.BaseForm):
    """Fix the declared fields an opener's query names."""

    opener_fields: ClassVar[tuple[FieldName, ...]] = ()

    stated_facts: dict[FieldName, object]
    statements: dict[FieldName, Statement | None]
    refused_facts: dict[FieldName, RefusalSentence]
    _bound_fields_cache: dict[str, forms.BoundField]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.stated_facts = {}
        self.statements = {}
        self.refused_facts = {}
        super().__init__(*args, **kwargs)

    def state_opener_facts(self, facts: OpenerFacts | None) -> None:
        """Call once fields are built, before any ``self[name]``."""
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
        self.stated_facts[name] = value
        self.statements[name] = statement

    def _state_one(self, name: FieldName, values: list[str]) -> None:
        field = self.fields[name]
        raw = values[0] if len(values) == 1 else ""
        if not raw:
            self._refuse(name, values)
            return
        if isinstance(field, forms.ModelChoiceField):
            self._state_row(name, field, raw)
            return
        try:
            value = field.clean(raw)
        except ValidationError:
            self._refuse(name, raw)
            return
        self.fix_field(name, value, statement=_choice_statement(field, raw, value))

    def _state_row(
        self, name: FieldName, field: forms.ModelChoiceField, raw: str
    ) -> None:
        try:
            key = parse_uuidv7(raw)
        except UUIDv7ParseError:
            self._refuse(name, raw)
            return
        if field.queryset is None:
            raise RuntimeError(f"{type(self).__name__}.{name} has no queryset.")
        row = field.queryset.filter(pk=key).first()
        if row is not None:
            self.fix_field(name, row, statement=field.label_from_instance(row))
        elif self.is_bound:
            # Gone since opened; the picker answers.
            self.refused_facts[name] = self._refusal(name)
        else:
            self._log(name, raw, "names no row this form offers")
            raise Http404("The link names a row this library does not hold.")

    def _refuse(self, name: FieldName, raw: object) -> None:
        self._log(name, raw, "is malformed")
        self.refused_facts[name] = self._refusal(name)

    def _refusal(self, name: FieldName) -> RefusalSentence:
        return refusal_sentence(str(self.fields[name].label or pretty_name(name)))

    def _log(self, name: FieldName, raw: object, reason: str) -> None:
        logger.warning(
            "Opener fact %s.%s=%s %s.",
            type(self).__name__,
            name,
            repr(raw)[:LOGGED_VALUE_LENGTH],
            reason,
        )


def _choice_statement(field: forms.Field, raw: str, value: object) -> Statement:
    if isinstance(field, forms.ChoiceField):
        pairs: list[tuple[object, object]] = list(
            flatten_choices(cast(Any, field.choices))
        )
        labels = {str(key): str(label) for key, label in pairs}
        return str(labels.get(raw, value))
    return str(value)
