# Log a game in one modal

Issue #1517, part of #1521. The "Log a game" modal adds a game to the
library and edits what the library states about it. Route
`games:log_game` at `log/`, `ORIGIN_AWARE`. The navbar's "Log game"
opens it; Game detail's Played menu opens it with `facts={"game": id}`,
which locks the game.

## Fields

The modal shows Game, Status, Platform, Started on and Finished on. Two
buttons open nested modals: "Add playtime…" (session or historical
playtime) and "Mastered and note…". Each nested modal is a `ModalDialog`
inside the form (`FormFieldGroup.container`), so its fields post with
the form. Done, ×, Escape and the backdrop close it and keep its fields.
A button that holds a value reads "Playtime added" or "Mastered and note
set". The submit reads "Create log" for an untracked game and "Save" for
a tracked one.

## Prefill

`held_facts` (`games/reads/log_game.py`) reads the status, the newest
live ordinary run, its two endpoints and note, the mastered flag, and a
platform: the newest session's Release, else the newest record's, else
the newest copy's. Each value posts again as `<name>_seen`. A field
equal to its seen value states nothing. Seen values name their game. A
`seen_game` that differs from the picked game writes nothing and
re-renders the page. A refusal re-renders the seen values from the post.

A navbar pick of a game dispatches `form-dialog:reload` with
`log/?prefill_game=<id>`. `<form-dialog>` fetches that page, replaces
its body and takes a new baseline. `prefill_<field>` is an editable
prefill; an opener fact locks.

## Writes

`log_game` (`games/writes/log_game.py`) writes one `LogStatement` under
one correlation id, in this order: track, copy, run, playtime, mastered,
status. Each key carries the form's `submission` token, so a second
press writes nothing twice. Unkeyed steps (track, restate and voids)
stay idempotent, because a repeat answers `Unchanged`. `attempt` keys
the playtime; a re-render drops a written playtime and raises `attempt`.
A refused press that wrote something says what it kept. The line reads
"Saved: …" and names each written step.

- **Copy.** A live copy on the platform names its Release. A changed
  platform with no copy records a copy with access Unknown and format
  Unknown, through `release_on`, or on a shared game's standing Release.
  No platform records no copy. `platform_refusal` refuses, before any
  write, a platform no Release can land on. `release_on` refuses a
  prerelease default Edition.
- **Run.** A changed day corrects its endpoint. A cleared day voids it
  (`void_run_endpoint`); the status stays. A game with no run gets one
  from `record_run`, keyed.
- **Status.** A changed word is stated last. Otherwise each act implies
  its status. A historical record implies Played over Unplayed here,
  through `status_implied_over`.

`EntryAccess.UNKNOWN` is not owned. Copy figures, the access badge and a
refund's end of access leave it out.

## Follow-up issues

- #1603: × reverts a nested modal.
- #1604: Platform lists only the game's platforms.
- #1519: copy details, purchases, and a run picker that replaces the
  newest-run rule.
- #1596, #1595, #1597, #1598.
