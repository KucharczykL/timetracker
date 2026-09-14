"""One report for every gated pass."""

import json
import sys
from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import NamedTuple, Protocol

from games.backfill.mismatch import Mismatch, MismatchEntry

#: Named in the failure sentence, so a lost stdout still says what broke.
NAMED_IN_FAILURE = 3


class ReportPrefixes(NamedTuple):
    """The machine line's prefix, and the human line's."""

    machine: str
    human: str


type Summary = Mapping[str, int]


class TextSink(Protocol):
    """Where a line goes: sys.stderr, or a command's wrapper."""

    def write(self, text: str, /) -> object: ...


def emit_report[CodeT: StrEnum](
    summary: Summary,
    mismatches: Sequence[Mismatch[CodeT]],
    *,
    prefixes: ReportPrefixes,
    summary_keys: Sequence[str],
    stdout: TextSink | None = None,
    stderr: TextSink | None = None,
) -> list[MismatchEntry]:
    """Print the machine line and the human lines; answer the entries."""
    #: Resolved now, so a capturing test sees them.
    stdout = sys.stdout if stdout is None else stdout
    stderr = sys.stderr if stderr is None else stderr
    entries = sorted(
        (mismatch.as_dict() for mismatch in mismatches),
        key=lambda entry: (entry["code"], entry["subject"], entry["detail"]),
    )
    payload = {"schema_version": 1, "summary": summary, "mismatches": entries}
    #: stderr: travels with the traceback.
    print(
        prefixes.machine + json.dumps(payload, sort_keys=True, separators=(",", ":")),
        file=stderr,
    )
    #: Every summary key prints, listed or not.
    keys = [*summary_keys, *(key for key in summary if key not in summary_keys)]
    print(
        prefixes.human + " " + " ".join(f"{key}={summary.get(key, 0)}" for key in keys),
        file=stdout,
    )
    for entry in entries:
        print(
            f"  {entry['code']} subject={entry['subject']} {entry['detail']}",
            file=stdout,
        )
    return entries


def failure_sentence(entries: Sequence[MismatchEntry], *, subject: str) -> str | None:
    """The first few mismatches named, and the rest counted."""
    if not entries:
        return None
    named = "; ".join(
        f"{entry['code']} {entry['subject']}: {entry['detail']}"
        for entry in entries[:NAMED_IN_FAILURE]
    )
    remainder = len(entries) - NAMED_IN_FAILURE
    if remainder > 0:
        named += f"; and {remainder} more"
    return f"{subject} failed with {len(entries)} mismatch(es): {named}"
