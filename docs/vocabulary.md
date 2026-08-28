# Vocabulary

The words this codebase refuses, and the words it uses instead. `make vale`
enforces them over every tracked `.md` file and over the comments and
docstrings in every tracked `.py` and `.ts` file. The rules live in
`.vale/styles/Timetracker/`; `make check` runs them.

A rule here governs prose. Code is out of scope: an identifier, a flag name, a
fenced block and an inline `code` span are all skipped, so `folder` and
`--no-count-replay` need no exception. That is also how this page can name the
words it refuses — each one below is written as code.

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

## Adding a rule

Put the settled meaning in `.vale/styles/Timetracker/Terminology.yml` as
patterns that need a neighbouring domain word, and the bare word in
`DiscouragedTerms.yml`. Add a section here saying why the word is refused. A
rule with no reason written down is a rule the next person who wants the word
reverts.

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
