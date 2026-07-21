# Source Badge Status Design

## Goal

Explain the highlighted source-badge tone without relying on color perception.

## Design

Source badge tooltips continue to describe the current source in their existing
`Source` row. Every unlocked badge whose current source is not `default` adds:

> **Status:** Non-default source (default source: “Default”)

The neutral `Default` badge needs no extra status row. Locked badges retain their
existing `Locked` explanation because their warning tone has a separate meaning.
When live saving changes a badge between default and non-default sources, the
browser adds or removes the status row together with the existing label, source
description, and tone update.

## Verification

Server-rendered component tests cover when the status row is present. Frontend
tests cover adding and removing it after save responses, and the settings browser
test confirms the non-default explanation is available without a page reload.
