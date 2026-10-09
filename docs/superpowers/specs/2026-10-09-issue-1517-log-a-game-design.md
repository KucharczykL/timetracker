# Log a game in one modal

Issue #1517, part of #1521. The modal adds a game to the library and edits what the library states about it. Route `games:log_game` at `log/`, `ORIGIN_AWARE`. Game detail's Played menu opens it with `facts={"game": id}`, which locks the game.

## Fields

The modal shows Game, Status, Platform, Started on and Finished on. Two buttons open nested modals: "Add playtime…" and "Mastered and note…". Each nested modal is a `ModalDialog` inside the form, so its fields post with the form. Done, ×, Escape and the backdrop close it and keep its fields. A button that holds a value reads "Playtime added" or "Mastered and note set".

## Prefill

`held_facts` (`games/reads/log_game.py`) reads the status, the newest live ordinary run, its endpoints and note, the mastered flag, and a platform. The platform is the newest session's Release, else the newest record's, else the newest copy's. Each value posts a seen field. A field equal to its seen value states nothing. A `seen_game` that differs from the picked game writes nothing and re-renders the page.

A navbar pick dispatches `form-dialog:reload` with `log/?prefill_game=<id>`. `<form-dialog>` fetches that page, replaces its body and takes a new baseline. `?prefill_game=` is an editable prefill; an opener fact locks.

## Writes

`log_game` (`games/writes/log_game.py`) writes one `LogStatement` under one correlation id, in this order: track, copy, run, playtime, mastered, status. Each key carries the form's `submission` token and the step's `attempt`. Unkeyed steps stay idempotent: a repeat answers `Unchanged`.

- **Copy.** A live copy on the platform names its Release. A changed platform with no copy records an Unknown copy, through `release_on`, or on a shared game's standing Release. No platform records no copy. `platform_refusal` refuses a platform no Release can land on, before any write.
- **Run.** A changed day states or corrects its endpoint. A cleared day voids it (`void_run_endpoint`); the status stays. A game with no run gets one from `record_run`.
- **Status.** A changed word is stated last. Otherwise each act implies its status. A historical record implies Played over Unplayed, through `status_implied_over`.

`EntryAccess.UNKNOWN` is not owned. Copy figures, the access badge and a refund's end of access leave it out.

## Refusals

A refusal re-renders the post. Each written step takes its seen values from the stored state. A refusal that kept anything raises `attempt`, so the retry keys apart from the first press. A refusal that wrote the playtime clears its duration fields.

A refused press that wrote something says what it kept: the line reads "Saved: …" and names each written step, such as the game in the library, a playthrough or a release. An error on a hidden field shows form-wide, because the hidden field cannot show it. A row gone mid-press refuses that step.

## Follow-up issues

- #1603: × reverts a nested modal.
- #1604: Platform lists only the game's platforms.
- #1519: copy details, purchases, and a run picker that replaces the newest-run rule.
- #1596, #1595, #1597, #1598.
