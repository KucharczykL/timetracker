# Issue #1489 plan: stated wrappers compare by type

Spec: `docs/superpowers/specs/2026-10-04-issue-1489-stated-wrappers-nominal-design.md`.

## Task 1: pin today's digests (red-free baseline)

- `tests/test_endpoint_fingerprints.py`: add `describe_session` and
  `describe_session_unset` to `COMMANDS` (`DescribeSession` with
  `StatedDevice(DEVICE)`/`StatedRelease(RELEASE)`, and with both `None`),
  digests recorded before the change:
  - stated: `8f5efaca331b487ad0f730be7a6c9e85ab77a7b907d3f06bcb497b77e436994f`
    (session `...0001`, device `...0002`, release `...0003` under the
    `0190a000-0000-7000-8000-` prefix; adapt to the file's own constants
    and recompute on main if they differ).
  - unset: `a7d74537cc8a81aa78103ec5c895d479f005ff90183acf4a1058de4a5918f915`.
- Module docstring: "Commands keep their recorded fingerprints."
- Run on main code: green.

## Task 2: nominal equality (red)

- `tests/test_playersession_command.py` (or a new small test): assert
  `StatedDevice(x) != StatedRelease(x)`, `StatedDevice(x) != (x,)`, and that
  unpacking raises `TypeError`.
- `tests/test_event_idempotency.py`: a dataclass instance encodes as its
  field list (digest equals the tuple's); a dataclass class is refused.

## Task 3: implement (green)

- `games/commands/playersession.py`: both classes become
  `@dataclass(frozen=True, slots=True)`; drop `NamedTuple` import if unused.
- `games/events/idempotency.py` `_encode_command_value`: after the
  `TemporalValue` branch, `is_dataclass(value) and not isinstance(value,
  type)` → `[getattr(value, field.name) for field in fields(value)]`.
  Name the return type (`EncodedValue = TaggedValue | list[Any]`); docstring
  says a dataclass carries no type word, on purpose.
- Gotcha: `json` calls `default` again on each returned element, so a
  UUID field still encodes tagged.

## Task 4: gate

- `make format`, `make lint-fix`, `make format-check`, `make vale`.
- `make check` under the shared lock.
