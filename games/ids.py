"""Roles a bare UUID plays."""

import uuid

#: A catalog game's key.
type GameId = uuid.UUID
#: One act's events share it.
type CorrelationId = uuid.UUID
#: A tracked game's key.
type PlayerGameId = uuid.UUID
type PlaythroughId = uuid.UUID
type HistoricalPlaytimeId = uuid.UUID
type PlayerSessionId = uuid.UUID
type EditionId = uuid.UUID
type ReleaseId = uuid.UUID
#: A device's key.
type DeviceId = uuid.UUID
#: A platform's key.
type PlatformId = uuid.UUID
