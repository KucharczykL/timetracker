"""A command's value objects fingerprint by type."""

import importlib
import pkgutil
from dataclasses import is_dataclass
from typing import ClassVar, TypeAliasType, get_args, get_origin, get_type_hints

import games.commands
from games.commands.purchase import UNDATED_PURCHASE, UNKNOWN_PRICE
from games.events.dispatch import Command
from games.events.idempotency import FingerprintedValue
from timetracker.temporal import TemporalValue

for module in pkgutil.iter_modules(games.commands.__path__):
    importlib.import_module(f"{games.commands.__name__}.{module.name}")


def _commands(base: type) -> list[type]:
    found = []
    for subclass in base.__subclasses__():
        found.append(subclass)
        found.extend(_commands(subclass))
    return found


def _reached(annotation: object, seen: set[type]) -> None:
    """Every class a field's type names."""
    if isinstance(annotation, TypeAliasType):
        _reached(annotation.__value__, seen)
        return
    for argument in get_args(annotation):
        _reached(argument, seen)
    if get_origin(annotation) is None and isinstance(annotation, type):
        if annotation in seen:
            return
        seen.add(annotation)
        #: Encoded by its own tag, not its fields.
        if annotation is TemporalValue:
            return
        if is_dataclass(annotation) or hasattr(annotation, "_fields"):
            for hint in get_type_hints(annotation).values():
                if get_origin(hint) is not ClassVar:
                    _reached(hint, seen)


def _value_classes() -> set[type]:
    seen: set[type] = set()
    for command in _commands(Command):
        for hint in get_type_hints(command).values():
            if get_origin(hint) is not ClassVar:
                _reached(hint, seen)
    return seen


def test_no_command_field_holds_a_named_tuple():
    """json writes a tuple itself, untagged."""
    named_tuples = {
        value.__qualname__
        for value in _value_classes()
        if issubclass(value, tuple) and hasattr(value, "_fields")
    }

    assert named_tuples == set()


def test_every_value_object_a_command_holds_states_a_word():
    unworded = {
        value.__qualname__
        for value in _value_classes()
        if is_dataclass(value)
        and not issubclass(value, FingerprintedValue)
        and value is not TemporalValue
    }

    assert unworded == set()


def test_value_objects_with_equal_fields_are_not_equal():
    assert UNKNOWN_PRICE != UNDATED_PURCHASE
    assert UNKNOWN_PRICE != (None, "")
