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
access has not ended. `default_device` (`UserLibraryPreferences`) applies
the same rule. Thus Resume never fills in a device that Add session does
not offer as a default.

The emulated flag describes the old device. When the device changes to the
default, the flag is false.

A device of another library is drift. Resume writes an ERROR record on the
`games` logger, as `device_field` does, and uses the default.

## Reason

`CreateSession` refuses a removed device through `library_device`. The
refusal tells the person to restore a device. The person did not choose
that device. Resume must not carry a device that the person cannot choose.

## Limits

The read occurs before the dispatch lock. If a person removes the device
between the read and the dispatch, the command refuses with its own
sentence. That sentence is then correct. If the device's access ends in
that interval, the session names the ended device. A session can name an
ended device.

The navbar lists only games that have a live session. Thus only a stale
request gets to the row "Does not exist".

## Tests

`tests/test_session_endpoints.py` covers each row that is not held: a
removed device, an ended device, a foreign device with its ERROR record,
and the fallback to a live default device.
