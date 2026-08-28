"""The one entry point for recording a change to a library: a named command,
an actor allowed to issue it, and the library it acts on.

It composes the append, idempotency, and retry modules beside it, and is the
only thing that should.

A command is a frozen dataclass whose fields *are* its canonical input, so the
idempotency fingerprint cannot fall out of step with what the command actually
does. It names itself with a member of a closed vocabulary, and that name is
part of the fingerprint -- without it, one key reused across two command types
whose fields coincide would replay one as the other.

There is more than one vocabulary. `CommandName` is the application's and holds
real commands only; the doubles that exercise dispatch declare their own. The
registry keys on the name, so two vocabularies cannot claim one name.

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
import uuid
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, fields, is_dataclass
from enum import StrEnum
from typing import Any, ClassVar, NamedTuple, cast

from django.contrib.auth.models import User

from games.events.append import AppendResult, LockedStream, SourceMetadata
from games.events.idempotency import (
    IdempotencyKey,
    ReplayedAppend,
    UnchangedAppend,
    idempotent_append,
)
from games.events.retry import run_in_transaction
from games.events.vocabulary import NewEvent, Unchanged
from games.events.wiring import DEFAULT_WIRING, EventWiring
from games.models import LibraryEvent, UserLibrary
from timetracker.uuidv7 import parse_uuidv7

#: Where a command class was defined, as (module, qualified name).
type DefinitionSite = tuple[str, str]  # ("games.commands.session", "CreateSession")

#: A command's stable domain symbol.
type CommandNameValue = str  # "library.playergame.track"

#: Read off the column, so the argument check and the constraint cannot drift.
IDEMPOTENCY_KEY_MAX_LENGTH: int = cast(
    int, LibraryEvent._meta.get_field("idempotency_key").max_length
)


class CommandVocabulary(StrEnum):
    """A closed set of command names.

    There is more than one. Members are stable domain symbols rather than
    Python paths, so moving or renaming a class cannot invalidate idempotency
    keys already issued under it. Requiring a member of *some* vocabulary still
    refuses a bare string typo, while leaving the production allowlist free of
    names only a test uses.
    """


class CommandName(CommandVocabulary):
    """Every command the application can run.

    The readable inventory: one grep, and no entry that is not a thing the
    system does. A test double names itself from its own vocabulary.
    """

    PLAYERGAME_TRACK = "library.playergame.track"
    PLAYERGAME_SET_STATUS = "library.playergame.set_status"
    PLAYERGAME_SET_MASTERED = "library.playergame.set_mastered"
    PLAYERGAME_SET_EXCLUDED_FROM_UNFINISHED = (
        "library.playergame.set_excluded_from_unfinished"
    )
    PLAYERGAME_ARCHIVE = "library.playergame.archive"
    PLAYERGAME_RESTORE = "library.playergame.restore"
    PLAYERGAME_RECORD_FACTS = "library.playergame.record_facts"


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


class CommandOutcome(StrEnum):
    """What one dispatch did.

    Three members rather than two booleans: a boolean pair describes four
    states where three exist.
    """

    APPENDED = "appended"
    REPLAYED = "replayed"
    UNCHANGED = "unchanged"


class SequenceRange(NamedTuple):
    """The stream sequences one append occupied, first and last included."""

    first: int
    last: int


@dataclass(frozen=True, slots=True)
class CommandResult:
    """What one dispatch did, whether or not it was the dispatch that did it.

    `outcome` collapses the append/replay/unchanged union at this boundary, so
    a caller branches on what happened rather than on which class it got. The
    events themselves do not escape: projections run inside the command's
    transaction, and a read taken after the lock is released is a different
    read.
    """

    stream_id: uuid.UUID
    outcome: CommandOutcome
    #: None exactly when the outcome is UNCHANGED: nothing was appended, so
    #: there is no range to name.
    sequences: SequenceRange | None
    #: A sentence only for a build that ran and returned Unchanged. Absent for
    #: an appended outcome, a replayed one, and a no-op whose key was already
    #: claimed. Nothing user-facing may depend on it.
    reason: str | None
    correlation_id: uuid.UUID


class CommandNotPermitted(Exception):
    """The actor may not issue commands against this library.

    Not a `CommandConflict`: nobody was in the way, and no number of retries
    turns one library's owner into another's.
    """


class CommandRejected(Exception):
    """Current state does not permit the action.

    Raised by a command's `build`, which is the only place that can tell. Also
    not a `CommandConflict`, and distinct from `CommandNotPermitted`: this is
    about what was asked rather than about who asked.
    """


def authorize(actor: User, library: UserLibrary) -> None:
    """Refuse anyone but the library's own active owner.

    Staff appears nowhere. An administrator-assisted repair is an explicit act
    with its own entry point, never a privilege ordinary dispatch honours.
    """
    if not actor.is_active:
        raise CommandNotPermitted("An inactive account cannot issue commands.")
    #: Says nothing about the library or its owner: a refusal is not a place to
    #: learn who else exists.
    if library.user_id != actor.pk:
        raise CommandNotPermitted("That library belongs to another account.")


def resolve_correlation_id(correlation_id: uuid.UUID | None) -> uuid.UUID:
    """Generate the correlation ID, or check the one the caller brought.

    Events store it in a `UUIDv7Field` over a domain with a version check, so
    an unchecked v4 would surface as a raw integrity error from inside the
    append rather than as a complaint about the argument.
    """
    if correlation_id is None:
        return uuid.uuid7()
    return parse_uuidv7(correlation_id)


def validate_idempotency_key(key: IdempotencyKey) -> None:
    """Reject a key the events table would reject, while the caller can still
    be told which argument was wrong."""
    if not key:
        raise ValueError("A command names itself with a non-empty idempotency key.")
    if len(key) > IDEMPOTENCY_KEY_MAX_LENGTH:
        raise ValueError(
            f"An idempotency key is at most {IDEMPOTENCY_KEY_MAX_LENGTH} "
            f"characters; this one is {len(key)}."
        )


_COMMAND_REGISTRY: dict[CommandNameValue, DefinitionSite] = {}


class Command(ABC):
    """One intent, expressed as a value.

    Concrete commands are frozen dataclasses. Their fields are hashed into the
    idempotency fingerprint, so a command holds only what identifies it: a model
    instance has no canonical form and is refused, meaning a command carries a
    UUID and re-fetches inside `build`, where it has the library to scope the
    lookup.
    """

    command_name: ClassVar[CommandVocabulary]

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        #: Usable here despite ABCMeta computing __abstractmethods__ after
        #: type.__new__: that attribute is a getset on type rather than an
        #: inherited one, so isabstract falls through to scanning members.
        if inspect.isabstract(cls):
            return

        name = getattr(cls, "command_name", None)
        if not isinstance(name, CommandVocabulary):
            raise TypeError(
                f"{cls.__qualname__} declares no command_name. Every concrete "
                "command names itself with a member of a CommandVocabulary."
            )

        #: The rebuilt class carries a bare __qualname__.
        #:
        #: dataclass(slots=True) cannot add slots in place, so it rebuilds the
        #: class and fires this a second time. One definition site registering
        #: twice is that rebuild; a second site is a real collision. The rebuild
        #: keeps __name__ and drops the `<locals>` prefix from __qualname__, so
        #: keying on the qualified name makes a command declared inside a
        #: function collide with itself.
        definition_site = (cls.__module__, cls.__name__)
        registered = _COMMAND_REGISTRY.get(name.value)
        if registered is not None and registered != definition_site:
            raise TypeError(
                f"{cls.__qualname__} claims {name.value!r}, already owned by "
                f"{registered[0]}.{registered[1]}."
            )
        _COMMAND_REGISTRY[name.value] = definition_site

    @abstractmethod
    def build(self, context: CommandContext) -> Sequence[NewEvent] | Unchanged:
        """Validate against current state and describe what happened.

        Two questions, in order. Does the state the caller asks for already
        hold? Return `Unchanged`: to do nothing is to reach it. Can it be
        reached from here? A no raises `CommandRejected`.
        """


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


def dispatch(
    command: Command,
    *,
    actor: User,
    library: UserLibrary,
    idempotency_key: IdempotencyKey,
    correlation_id: uuid.UUID | None = None,
    source_metadata: SourceMetadata | None = None,
    wiring: EventWiring = DEFAULT_WIRING,
) -> CommandResult:
    """Record what `command` describes, once, in `library`, as `actor`.

    Everything that can refuse the command refuses it before any database work:
    a dispatch that cannot commit must not take `SELECT ... FOR UPDATE` on a
    stream head and make that library's real writers wait behind it, and must
    not spend a transaction or a retry budget getting there.
    """
    authorize(actor, library)
    validate_idempotency_key(idempotency_key)
    #: Once per dispatch, so every attempt of a retried command shares one.
    resolved_correlation_id = resolve_correlation_id(correlation_id)
    command_input = canonical_command_input(command)

    def build(stream: LockedStream) -> Sequence[NewEvent] | Unchanged:
        #: The stream is required by this signature and deliberately dropped:
        #: withholding it is what stops a command appending on its own and
        #: leaving events outside the range its key replays.
        #: The context is built here, per attempt, so a rolled-back attempt
        #: cannot hand its model instances to the next one.
        return command.build(CommandContext(library=library, actor=actor))

    def run() -> AppendResult | ReplayedAppend | UnchangedAppend:
        return idempotent_append(
            library,
            idempotency_key=idempotency_key,
            command_input=command_input,
            build=build,
            actor=actor,
            correlation_id=resolved_correlation_id,
            source_metadata=source_metadata,
            wiring=wiring,
        )

    outcome = run_in_transaction(run, policy=wiring.retry_policy)
    if isinstance(outcome, UnchangedAppend):
        return CommandResult(
            stream_id=outcome.stream_id,
            outcome=CommandOutcome.UNCHANGED,
            sequences=None,
            reason=outcome.reason,
            correlation_id=resolved_correlation_id,
        )
    return CommandResult(
        stream_id=outcome.stream_id,
        outcome=(
            CommandOutcome.REPLAYED
            if isinstance(outcome, ReplayedAppend)
            else CommandOutcome.APPENDED
        ),
        sequences=SequenceRange(outcome.first_sequence, outcome.last_sequence),
        reason=None,
        correlation_id=resolved_correlation_id,
    )
