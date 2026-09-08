# The Playthrough API

The `/api/playthrough` router answers about the `Playthrough` projection. No
route reads `games_playevent`, and no schema names it.

## The path names a run

The three routes that take a key take the run's own. A list of runs cannot
state a legacy row id: a run `TrackGame` states names no row, and neither does
a run added to a game that already holds one. `POST /` takes a `game_id`, and
`GET /` takes no key at all.

This moves the identity out of #771, which the wave gave it while the router
still read rows. The move is forced by the list, so #1015 carries it, and
#771 is left the table alone. It is a breaking change for any client that
holds a legacy id: every such id answers 404. No client in this repository
holds one; the tests that do are named below.

## Two scopes

| the routes | read |
|---|---|
| `GET /`, `GET /{id}` | `library_runs(library)` |
| `PATCH /{id}`, `DELETE /{id}` | the library's runs, whatever the mark |

`library_runs` in `games/reads/playthrough_runs.py` holds the live ordinary
runs of a live tracked game. It is the scope every read surface states, so the
API lists what the list page lists.

A write resolves wider on purpose. `RemovePlaythrough` answers `Unchanged` for
a run already removed, which is what #906 asks of a repeat, and a scope that
hides the removed run would answer 404 instead. The commands own every
refusal; the route only finds the row. The scope states `library` beside
`player_game__library`, as `_editable_runs` does in `games/views/playthrough.py`,
and states no kind: nothing writes a second kind today.

`GET /` orders `-created_at, id`, which is the list page's order — its default
sort is `-created`, and `apply_sort` tiebreaks on the key ascending. No index
covers a library-wide order, because `playthrough_display_order` is prefixed by
`player_game`. It reads `select_related("player_game__game")`, because the body
names the game.

`limit` is 100 by default, `0` is unbounded as on `GET /presets/`, and a
negative value is refused. `offset` is 0 by default and refuses a negative
value too. Presets refuse nothing; here Django's slice cannot take a negative
index, so the refusal is stated rather than clamped.

## The body

One schema answers both reads.

| field | states |
|---|---|
| `id` | the run |
| `game`, `game_id` | the catalog game's name and key |
| `name` | the stated name; empty where the row states none |
| `note` | the run's note |
| `started`, `completed` | each endpoint's canonical value |
| `started_lower`, `started_upper` | the earliest and latest day the start can name |
| `completed_lower`, `completed_upper` | the same two days for the completion |
| `start_recorded_at`, `completion_recorded_at` | the instant each act was recorded |
| `start_note`, `completion_note` | the note of each act |
| `days_to_finish` | the days the run touched |
| `created_at` | the creation event's instant |

An endpoint states a day, a month, a year, a decade, a range, or a qualifier
beside one. The canonical string states all of them: `2024-05`, `202X`,
`2024-01/..`, `2026-03-04~`. The two bound columns state the interval that
value names, and an absent bound is unbounded. The marker beside them carries
the act: a null marker is an act that never happened, and a null date beside a
marker that is not null is a day nobody knows.

An empty `name` is not filled in. The display number belongs to the list it is
counted across, and no body states one.

## Three read values change

1. `updated_at` is gone. The projection records none, and the two markers are
   not one: an act recorded later says nothing about the note beside it.
2. `days_to_finish` counts both ends. The legacy column subtracted the days,
   with a same-day run special-cased to 1, so every multi-day run now reads one
   higher: 1 January to 4 January read 3 and now reads 4.
3. It answers nothing where a bound is absent, and nothing for a completion
   before a start. The legacy `0` and the legacy negative number are both gone.

## The written value

`POST /` and `PATCH /{id}` state the same grammar the body reads. The field is
`Annotated[TemporalValue | None, BeforeValidator(...), PlainSerializer(...)]`.
The validator builds the value from the string, and `TemporalValueParseError`
is a `ValueError`, so a refused spelling answers 422. A bare
`TemporalValue` annotation cannot do this: pydantic reads the dataclass and
asks for its eight fields.

`RunDraft` carries `TemporalValue | None` for each endpoint, and its second
field is `completed`, as the filter, the sorts and the saved presets say.
`_stated_day` goes. The commands take a `TemporalValue` already, so no command
changes.

`_draft_from` in `games/views/playthrough.py` is the one converter for both
form views. It states `TemporalValue.from_day(day)` for a day and `None` for
none, because the form's two fields are not required and `from_day(None)`
raises.

`PATCH` states the whole run, so a key the request leaves out is seeded from
the run itself: `run.started`, `run.completed`, `run.note`. It was seeded from
`restatable_days` before, which also refused a run richer than a day. Both go
here. `restatable_days` stays for the form views, which are still day-shaped
and still refuse such a run.

`name`, `start_note` and `completion_note` are read-only. `DescribePlaythrough`
and the two corrections state all three, but no screen does, and the API does
not lead the screens.

## What the cutover takes with it

`games/reads/playthrough_provenance.py` maps a legacy row id to its run. The
API is its one caller in `games/`, so the module goes here rather than with
#771, and `test_one_module_reads_the_bridge` in
`tests/test_playthrough_api_writes.py` goes with it. Seven test modules call
`run_for_row` to find the run a legacy row became; each reads the game's runs
instead.

`AutoPlayEventIn` is a `ModelSchema` over `PlayEvent` that no route names, and
`tests/test_session_playhistory_identity.py` asserts its two generated fields
as the one direct check of a `ModelSchema` over a cutover model. Both go, and
the module keeps its remaining cases; no `ModelSchema` covers `PlayEvent` or
`Session` after this, which is what the surrounding cases already state.

After both, `games/api.py` imports nothing from the legacy table.

CLAUDE.md states that the path id is the legacy row's and that `runs_for_rows`
stays for the API. Both lines are corrected. The wave document records the
identity move on #1015 and the smaller #771.

## Verification

- every value shape reads back as itself: a day, a month, a year, a decade, a
  range, a qualified day, an unknown day, and an act that never happened. The
  last two are read off a run `TrackGame` states, which reaches neither
  endpoint;
- a `PATCH` of a month states the month, and a second identical `PATCH` states
  nothing more;
- a `PATCH` that names one key leaves the other endpoint and the note as the
  run states them, richer than a day included;
- the day-shaped form states a day through the widened draft, and a blank day
  states none;
- the list holds no removed run, no run of a removed or untracked game, and no
  foreign library's run. `GET`, `PATCH` and `DELETE` each answer 404 for a
  foreign run, against a run this time, not a row id that names nothing;
- a second `DELETE` of one run answers 204, as it does today;
- `limit`, `limit=0`, a negative `limit`, `offset`, and a negative `offset`;
- the list reads a constant number of queries for a page of many runs.

## Rollback

The change is code alone. No migration, no new event type, and no event shape
that replay has not already recorded. Reverting restores the legacy bodies,
because the events were the record before this issue. A client that stored a
legacy id does not get it back; it reads the run's id again from the list.

## Out of scope

- stating a name or an act note from a request: no screen states one
- a form that states a value richer than a day: the two views convert a day
- an endpoint stated by a `PATCH` that names neither: both acts are stated
  whenever a run is written, which #687 settled
- the purchase Finished cell and the `finished` sorts: #1026
- the replay-parity gate over both families: #688
- taking `games_playevent` away: #771
