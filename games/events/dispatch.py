"""The kernel's front door: a named command, an actor allowed to issue it, and
the library it acts on.

A command is a frozen dataclass whose fields *are* its canonical input, so the
idempotency fingerprint cannot fall out of step with what the command actually
does. It names itself with a member of a closed allowlist, and that name is part
of the fingerprint -- without it, one key reused across two command types whose
fields coincide would replay one as the other.

Two properties of the registry below follow from keying it on a definition site
rather than on class identity, and are limits rather than oversights:

- Two distinct classes sharing a module and qualified name -- defined in two
  branches of an `if`, or inside a parametrized test -- replace each other
  silently.
- Subclassing a *concrete* command is impossible: the subclass inherits its
  name and registers under it from a different qualified name, which is the
  collision case. Commands compose by sharing an abstract base.
"""

import inspect
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, fields, is_dataclass
from enum import StrEnum
from typing import Any, ClassVar

from django.contrib.auth.models import User

from games.events.append import NewEvent
from games.models import UserLibrary

#: Where a command class was defined, as (module, qualified name).
type DefinitionSite = tuple[str, str]  # ("games.commands.session", "CreateSession")


class CommandName(StrEnum):
    """Every command the system can run.

    A closed allowlist rather than a free string: the type rejects an unlisted
    name before anything runs, and the vocabulary of the audit trail is one
    grep. Members are stable domain symbols, not Python paths, so moving or
    renaming a class cannot invalidate idempotency keys already issued under it.
    """

    #: Placeholders exercising the kernel until real commands exist.
    TEST_KERNEL_BASIC = "test.kernel.basic"
    TEST_KERNEL_TWIN = "test.kernel.twin"
    TEST_KERNEL_TEMPORAL = "test.kernel.temporal"
    TEST_KERNEL_UNSHAPED = "test.kernel.unshaped"
    TEST_KERNEL_FLAKY = "test.kernel.flaky"


@dataclass(frozen=True, slots=True)
class CommandContext:
    """What a command may look at while deciding which events to emit.

    The library scopes every query the command makes; the actor is there for a
    command that records who acted.

    **The locked stream is deliberately absent.** Its `append` is public, so a
    command holding it could append directly *and* return events -- and the
    idempotency record would cover only the second range, leaving the first
    committed inside the stream but outside what the key replays.
    """

    library: UserLibrary
    actor: User


_COMMAND_REGISTRY: dict[CommandName, DefinitionSite] = {}


class Command(ABC):
    """One intent, expressed as a value.

    Concrete commands are frozen dataclasses. Their fields are hashed into the
    idempotency fingerprint, so a command holds only what identifies it: a model
    instance has no canonical form and is refused, meaning a command carries a
    UUID and re-fetches inside `build`, where it has the library to scope the
    lookup.
    """

    command_name: ClassVar[CommandName]

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        #: Usable here despite ABCMeta computing __abstractmethods__ after
        #: type.__new__: that attribute is a getset on type rather than an
        #: inherited one, so isabstract falls through to scanning members.
        if inspect.isabstract(cls):
            return

        name = getattr(cls, "command_name", None)
        if not isinstance(name, CommandName):
            raise TypeError(
                f"{cls.__qualname__} declares no command_name. Every concrete "
                "command names itself with a CommandName member."
            )

        definition_site = (cls.__module__, cls.__qualname__)
        registered = _COMMAND_REGISTRY.get(name)
        #: dataclass(slots=True) cannot add slots in place, so it rebuilds the
        #: class and fires this a second time. One definition site registering
        #: twice is that rebuild; a second site is a real collision.
        if registered is not None and registered != definition_site:
            raise TypeError(
                f"{cls.__qualname__} claims {name.value!r}, already owned by "
                f"{registered[0]}.{registered[1]}."
            )
        _COMMAND_REGISTRY[name] = definition_site

    @abstractmethod
    def build(self, context: CommandContext) -> Sequence[NewEvent]:
        """Validate against current state and describe what happened."""


def canonical_command_input(command: Command) -> dict[str, Any]:
    """The input a command's idempotency fingerprint is taken over.

    The dataclass check is not only a guard: `Command` is an ABC, so it also
    narrows the type `fields()` will accept.
    """
    if not is_dataclass(command):
        raise TypeError(
            f"{type(command).__qualname__} is not a dataclass. A command's "
            "fields are its canonical input, so it has none to fingerprint."
        )

    #: Shallow, never asdict(): that recurses, so a TemporalValue field would
    #: be destructured into its private layout before idempotency's
    #: canonicalizer could reduce it to its canonical string. Equal values
    #: would still hash equally, leaving the fingerprint quietly dependent on
    #: a layout nobody thinks of as part of the contract.
    return {
        "command": command.command_name.value,
        "fields": {
            field.name: getattr(command, field.name) for field in fields(command)
        },
    }
