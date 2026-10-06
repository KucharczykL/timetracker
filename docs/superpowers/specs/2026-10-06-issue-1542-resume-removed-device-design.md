# Resume carries only a held device

Issue #1542.

## Rule

Resume starts a Timed session now on the game's latest live ordinary run.
`clone_session` (`games/writes/playersession.py`) reads the game's last
session itself. The view passes only the game.

The last session is the first row of `game_sessions` in `sort_instant`, `id`
descending order. This is the navbar's order. A bucket session counts. The
prerelease setting is not read.

`resumed_device` states the device and the emulated flag:

| Last session | Device | Emulated |
|---|---|---|
| Names a held device | That device | The last session's |
| Names a device that is not held | The default device | False |
| States no device | None | The last session's |
| Does not exist | The default device | False |

A device is held when this library has it, it is not removed, and its
access has not ended. `held_devices` (`games/reads/devices.py`) states this
rule. `default_device` (`UserLibraryPreferences`) applies the same rule.
Because of this, Resume never fills in a device that Add session does not
offer as a default.

When Resume does not carry a device of this library, the view shows a
notice: "Resumed on Desktop; Deck is no longer held." With no default
device, the notice is "Resumed with no device; Deck is no longer held."

The emulated flag describes the old device. When the device changes to the
default, the flag is false.

A device of another library is drift. Resume writes an ERROR record on the
`games` logger, as `device_field` does, and uses the default. The record
names the session and the game. The notice does not show the other
library's device name.

## Reason

`CreateSession` refuses a removed device through `library_device`. The
refusal tells the person to restore a device. The person did not choose
that device. Resume must not carry a device that the person cannot choose.

## Limits

The read happens before the dispatch lock. If a person removes the device
between the read and the dispatch, the command refuses with its own
sentence. That sentence is then correct. If the device's access ends in
that interval, the session names the ended device. A session can name an
ended device. The default device can also be removed in that interval. The
command then refuses with its own sentence.

The navbar lists only games that have a live session. Only a stale request
reaches the row "Does not exist".

## Tests

`tests/test_session_endpoints.py` covers each row of the table, each way a
device is not held (removed, ended, foreign), the notice, and the order
that selects the last session. `tests/test_prerelease_play.py` shows that
the prerelease setting does not change the last session.
