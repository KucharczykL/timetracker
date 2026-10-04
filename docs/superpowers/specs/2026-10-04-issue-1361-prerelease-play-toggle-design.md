# A toggle that hides prerelease play

Issue [#1361](https://github.com/KucharczykL/timetracker/issues/1361).
Wave: [Access and Purchases](2026-09-28-access-and-purchases-wave-design.md).
Builds on [#1354](2026-10-03-issue-1354-session-release-design.md).

## The fact

Prerelease play is a session or a historical playtime record whose
Release is of a `prerelease` Edition. `PRERELEASE_PLAY` in
`games/reads/prerelease_play.py` states it. A row that names no Release
is not prerelease play.

## The setting

`SHOW_PRERELEASE_PLAY` is a user setting in the registry. Its values are
the strings `show` and `hide` (`PrereleasePlay`). The default is `show`.
The settings page shows it as a select after "Dormant after". The
validator refuses every other value, and the reader raises on one. The value is text, not a bool: the live save writes the
resolved value back into the select, and a bool does not match its
option.

## The two scopes

| Sessions | Records | Rows |
|---|---|---|
| `library_sessions` | `library_records` | every live row |
| `shown_sessions` | `shown_records` | rows `shown_play` keeps |

`shown_play(library)` is `Q()` when the setting is `show`. When it is
`hide`, it excludes the keys of every prerelease Release (`NOT IN`). Django adds
`IS NOT NULL` inside the negation, so a row that names no Release stays.
The `NOT IN` shape costs less than the join `PRERELEASE_PLAY` makes.

The row paths follow the scopes. `readable_sessions` and
`readable_records` read every row; `listed_sessions` and
`listed_records` read shown rows.

## Who reads the shown scope

A figure, a list, and a count beside a link to a list read it:

- every playtime figure, the navbar's figures and its Sessions link,
  `played_years`;
- the session and day figures, games played, `total_year_games`;
- the filter context, so list filters, aggregates and `stats_links`
  targets agree with their figures;
- the Sessions, Historical and Game detail lists;
- the bulk scopes, `reviewable_sessions`, `organization_counts`.

A Games-list filter on session or record aggregates reads the shown
scope too. So "no sessions" matches a game played only on a demo, and a
bulk removal can take it. The removal preview counts every session, so
the person sees them before the act.

## Who reads every row

- A resolve or an edit: a person named the row. The bulk resolutions,
  the record form, the edit page.
- The API, lists included: a program reads it, not a screen. A caller
  narrows with `edition_kind`.
- An act and its preview: resume, clone, departure counts.
- The new run's seed (`game_tracked_between`, `game_session_days`):
  stored text does not follow a view setting.
- The run's numbering, completion and activity, the backlog,
  `played_releases`.

`outside_playthrough_dates` excuses prerelease play whatever the
setting says.

A reclassification copies the Release to the record, so hidden play
stays hidden.

## Cost

On the 2026-10-03 dump with every row naming a Release, `hide` keeps
every read inside the 20 ms budget. The largest is `stats_copies` at
18 ms; `compute_stats` takes 80–95 ms in both values.
