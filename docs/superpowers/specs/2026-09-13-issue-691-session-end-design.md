# End a running Timed session

A Timed `PlayerSession` can hold a start and no end. One command states that
end. Part of the [session delivery wave](2026-09-12-session-wave-design.md),
over the
[PlayerSession aggregate](2026-09-13-issue-689-playersession-aggregate-design.md).

## The verb

The act uses one word in three places: the command `EndSession`, the event type
`library.playersession.ended`, and the builder `playersession_ended()`. The
columns are `ended_at` and `ended_at_zone`.

## The event

The payload holds two keys. `ended_at` is canonical instant text.
`ended_at_zone` is text or null. The payload is not `TimingPayload`. That union
states a whole mode, and it serves whole statements. An end is a partial act. It
states two columns. The other six stay as the creation wrote them.

The payload holds no `day_zone`. The row holds that zone. Strict validation
refuses an unknown key, thus each key is a fact that a person can state. A
second spelling of the zone is not such a fact.

`effective_time` holds the end instant, read in the row's `day_zone`. The
generated `effective_day` column reads the start. For a session that goes over
midnight, the two days stay different. The event gives the date of the act. The
row gives the date of the session. A reader of the trail must not assume that
all events of one session hold one day.

## The command

`EndSession` holds `session_id`, `ended_at`, and `ended_at_zone`. The zone has
no default value. Null is a zone that nobody stated, and a caller states it.

`__post_init__` does two operations before the fingerprint. It makes a blank
zone null. It refuses an instant that has no offset. Dispatch makes the
fingerprint from the input first, thus a rule about the shape of the input must
run before it.

`build` finds the row with `_live_session`. That helper finds this library's
row, then calls `_live_run` for the run, then refuses a removed session. The
call to `_live_run` also proves that the run is this library's.

`_timed_start` refuses the mode before it reads the start. A Duration-only row
holds no instants. A Corrected row holds an end already. Then `build` refuses an
end on a row that states one, an end before the start, and a zone that the two
tzdata sets do not both read. Each refusal carries a message and a sentence.

A restatement of the same instant in the same zone answers `Unchanged`. The same
instant in a different zone is a refusal, because the zone is a stated fact.

An end equal to the start is correct. Removal is the remedy for a session that
must not exist.

The zone check is the only guard. `ended_at_zone` feeds no generated column, and
one constraint refuses a blank value alone. An unknown name violates nothing and
stays in the row.

## The handler

`_ended` calls `amend` for the two columns. `amend` is an UPDATE over the
columns given to it, and it refuses a row that does not exist. It reads no mode.
The command read the mode under the lock of the stream head, and the CHECK
constraints hold thereafter.

A replay keeps the order of the sequence, thus the creation always comes before
the end.
