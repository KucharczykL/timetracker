# The Playthrough API

The `/api/playthrough` router answers about the `Playthrough` projection. No
route reads `games_playevent`, and no schema names it.

## The path names a run

`GET /{id}`, `PATCH /{id}` and `DELETE /{id}` take the run's own key. `POST /`
takes a `game_id`. `GET /` takes no key. A legacy row id answers 404.

## Two scopes

| the routes | read |
|---|---|
| `GET /`, `GET /{id}` | `library_runs(library)` |
| `PATCH /{id}`, `DELETE /{id}` | the library's runs, whatever the mark |

`library_runs` in `games/reads/playthrough_runs.py` holds the live ordinary
runs of a live tracked game. It is the scope every read surface states, so the
API lists what the list page lists.

A write resolves wider. `RemovePlaythrough` answers `Unchanged` for a run
already removed, and a scope that hides that run answers 404 instead. The
commands own every refusal; the route only finds the row.

`GET /` orders `-created_at, id`, which is the list page's order, and reads
`select_related("player_game__game")`, because the body names the game.
`limit` is 100 by default and `0` is unbounded. `offset` is 0 by default. A
negative value of either is refused, because a Django slice takes no negative
index.

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
value names, and an absent bound is unbounded. A null marker is an act that
never happened. A null date beside a marker that is not null is a day nobody
knows.

`days_to_finish` counts both ends. It states nothing where a bound is absent,
and nothing for a completion that precedes a start.

An empty `name` is not filled in. The display number belongs to the list it is
counted across, and no body states one.

## The written value

`POST /` and `PATCH /{id}` state the grammar the body reads. Each endpoint
field is `Annotated[TemporalValue | None, BeforeValidator(...),
PlainSerializer(...)]`. The validator builds the value from the string, and
`TemporalValueParseError` is a `ValueError`, so a refused spelling answers 422.
A bare `TemporalValue` annotation cannot do this: pydantic reads the dataclass
and asks for its eight fields.

`RunDraft` carries `TemporalValue | None` for each endpoint. A `PATCH` states
the whole run, so a key the request leaves out is seeded from the run itself.
The stated keys are read off `model_fields_set`, because a serialized payload
holds canonical strings and the commands take values.

`name`, `start_note` and `completion_note` are read-only. `DescribePlaythrough`
and the two corrections state all three, but no screen does, and the API does
not lead the screens.

## Not stated here

- a name or an act note from a request
- a form that states a value richer than a day
- the purchase Finished cell and the `finished` sorts: #1026
- taking `games_playevent` away: #771
