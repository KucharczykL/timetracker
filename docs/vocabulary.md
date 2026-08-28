# Vocabulary

The words this codebase refuses, and the words it uses instead. `make vale`
enforces them over every tracked `.md` file and over the comments and
docstrings in every tracked `.py` and `.ts` file. The rules live in
`.vale/styles/Timetracker/`; `make check` runs them.

A rule here governs prose. Code is out of scope: an identifier, a flag name, a
fenced block and an inline `code` span are all skipped, so `folder` and
`--no-count-replay` need no exception. That is also how this page can name the
words it refuses — each one below is written as code.

## Refused

### `fold` → replay, projection, recorded state

A projector **replays** events. The row it leaves is the **projection**, or
**what the events recorded**.

The word named that act and also named merging two values or two date ranges,
so it named neither. It also says nothing to a reader who has not met the term.
Commit `2a9e0d27` renamed 62 files; #676 and #677 put it back in 71 places
within two days, because the rename left nothing behind that could refuse it.
This page and the check are that thing.

| Instead of | Write |
|---|---|
| `the fold` | the replay, the projection |
| `the row its events folded to` | the row its events made |
| `the fold says 'p'` | the events say `p` |
| `mirror the fold` | mirror the row |
| `folds two ranges` | merges two ranges |

## Adding a rule

Add a `swap:` entry to `.vale/styles/Timetracker/Terminology.yml` and a section
here saying why the word is refused. A rule with no reason written down is a
rule the next person who wants the word reverts.

Purge the existing uses in the same commit. `make vale` fails on the first one
otherwise, which is the point.

## Not enforced here

The register rules — ASD-STE100 for a spec, seven words for a comment — are
judgement rather than pattern matching, and stay in review rather than in a
linter.
