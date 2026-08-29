# Vocabulary

The words this codebase refuses, and the words it uses instead. `make vale`
enforces them over every tracked `.md` file and over the comments and
docstrings in every tracked `.py` and `.ts` file. The rules live in
`.vale/styles/Timetracker/`; `make check` runs them.

A rule here governs prose. Code is out of scope: an identifier, a flag name, a
fenced block and an inline `code` span are all skipped, so `folder` and
`--no-count-replay` need no exception. That is also how this page can name the
words it refuses — each one below is written as code.

Two paths are held to the earlier rules but not the removal ones:
`CHANGELOG.md` and `docs/superpowers/`. A changelog entry describes a release
that shipped under the word it used, and a design record has to name the words
a codebase gave up. Neither can be edited into the present tense.

## Two levels

A word is refused for one meaning and merely imprecise for the rest, so the
check answers at two levels.

- **error** — the settled meaning, named by the words around it. There is one
  right replacement, the message says it, and the build fails.
- **warning** — every other use. Printed, not fatal. The word may be the right
  one; a pattern cannot tell, and only a reader can.

Vale matches patterns, not meanings, so the split is an approximation. It is
measured rather than assumed: over the uses that #676 and #677 introduced, 16
of 20 domain uses reach error level and the other 4 fall through to warning,
while all 6 of the ordinary uses from before commit `2a9e0d27` stay warnings.
The tuning target is that second number — an ordinary use must never be told to
say `replay`, because that advice would be wrong. A domain use that only warns
still gets read.

## Refused

### `fold` → replay, projection, recorded state

A projector **replays** events. The row it leaves is the **projection**, or
**what the events recorded**.

The word named that act and also named merging two values or two date ranges,
so it named neither. It also says nothing to a reader who has not met the term.
Commit `2a9e0d27` renamed 62 files; #676 and #677 put it back in 71 places
within two days, because the rename left nothing behind that could refuse it.
This page and the check are that thing.

Error when the sentence names the domain — an event, a stream, a projector, or
the row, projection, status or state it writes:

| Instead of | Write |
|---|---|
| `the fold` | the replay, the projection |
| `the row its events folded to` | the row its events made |
| `the fold says 'p'` | the events say `p` |
| `mirror the fold` | mirror the row |
| `folds the events` | replays the events |

Warning everywhere else, where the plainer word depends on what is joined:

| Instead of | Write |
|---|---|
| `folds two ranges` | merges two ranges |
| `folded into the label` | included in the label |
| `folding them into one branch` | combining them into one branch |

### `tombstone` → remove

A user **removes** a record. The row stays, `removed_at` says when, and
`restore` puts it back.

The word named a husk: a row emptied of everything but its name, kept so a
foreign key had something to point at. #944 ended that shape. Nothing is
emptied now, so nothing is a `tombstone`, and a word for a thing that no longer
exists can only describe the current code by accident.

Error when the sentence names a row or a record:

| Instead of | Write |
|---|---|
| `a tombstoned row` | a removed row |
| `write a tombstone` | remove the record |
| `the tombstone keeps the name` | the removed row keeps its name |

Warning everywhere else. The word has no other sense in this codebase, so a
warning here means a sentence the pattern could not read.

### `archive` → remove

Same act, second name. `PlayerGame.archived_at` and the `ArchivePlayerGame`
command said `archive` while every screen said delete, and neither word was
the one a user read. #944 renamed the column, the command and the event to
`remove`, because one act may have only one word.

Error when the sentence names a row or a record:

| Instead of | Write |
|---|---|
| `archive the game` | remove the game |
| `an archived purchase` | a removed purchase |

Warning everywhere else: a tar file is an `archive`, and Postgres has an
`archive` mode. Neither is a record in a library.

### `delete` → remove, purge, destroy

`delete` is Django's word. `Model.delete()` deletes, a branch is deleted, a
file is deleted. None of those is a library's act.

- A user **removes** a record and may **restore** it.
- **Purge** is the whole library at once, and it is the only act that destroys.
- **Destroy** describes what a shell or a script does to a row, which no screen
  can do.

Error only next to a record noun — row, record, game, session, purchase,
preset, play event, device, platform — or in `permanently delete`:

| Instead of | Write |
|---|---|
| `deleting a game` | removing a game |
| `permanently delete` | purge |
| `the deleted row` | the removed row |

Not warned as a bare word. Hundreds of correct uses name `.delete()`, a
deleted file or a deleted branch, and a rule that flagged them all would be
read as noise and then ignored.

### `heal` → name the act

Two unrelated acts wore this word, and it described neither.

- The write path **tracks the game first**, then states the fact.
  `RecordPlayerGameFacts` is refused when the library tracks no such game, so
  `record_facts` tracks it and dispatches once more.
- A stale stored value is **corrected on the next read**. A saved sort key or
  page size that no longer resolves falls back to the default, and an
  unreadable settings table degrades to no overrides until the read after it.

Neither is a wound closing. The metaphor stood in for the whole shape of each
act, so a reader who had not met it learned nothing, and one who had met it
pictured a body. There is no single replacement, and that is the point: say
what the code creates, or say what it corrects.

Error when the sentence names the domain — a case, a record, a stored value,
or the write path that answers it:

| Instead of | Write |
|---|---|
| `the write path heals this case` | the write path tracks the game first |
| `heals an untracked game` | tracks the game, then states the fact |
| `the heal and its retry` | tracking and the retry |
| `self-heals on the next read` | the next read tries again |

Warning everywhere else, because only a reader knows what was missing and what
was merely stale. `health` and `healthy` are not matched: Vale bounds every
token, so the pattern needs a word ending where those two continue.

## Adding a rule

Put the settled meaning in a rule file under `.vale/styles/Timetracker/` as
patterns that need a neighbouring domain word, and the bare word in a second
file at warning level. One pair of files per word family, because the error
message names the one replacement and each family has its own. Add a section
here saying why the word is refused. A rule with no reason written down is a
rule the next person who wants the word reverts.

Go's regular expressions have no lookahead, so the broad pattern cannot exclude
the narrow one and both report the same words. `scripts/run-vale.mjs` drops a
warning that an error already covers, which is why it reads Vale's JSON rather
than its plain output.

Purge the existing uses in the same commit. `make vale` fails on the first one
that reaches error level, which is the point.

## Not enforced here

The register rules — ASD-STE100 for a spec, seven words for a comment — are
judgement rather than pattern matching, and stay in review rather than in a
linter.
