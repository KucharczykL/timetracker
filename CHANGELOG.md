## Unreleased

## New
* Render notes as Markdown
* Require login by default
* Add stats for dropped purchases, monthly playtimes
* Allow deleting purchases
* Add all-time stats
* Manage purchases
* Automatically convert purchase prices
* Add emulated property to sessions
* Add today's and last 7 days playtime stats to navbar

## Improved
* mark refunded purchases red on game overview
* increase session count on game overview when starting a new session
* game overview:
  * sort purchases also by date purchased (on top of date released)
  * improve header format, make it more appealing
  * ignore manual sessions when calculating session average
* stats: improve purchase name consistency
* session list: use display name instead of sort name
* unify the appearance of game links, and make them expand to full size on hover

## Fixed
* Fix title not being displayed on the Recent sessions page
* Avoid errors when displaying game overview with zero sessions

## 1.5.2 / 2024-01-14 21:27+01:00

## Improved
* game overview:
  * improve how editions and purchases are displayed
  * make it possible to end session from overview
* add purchase: only allow choosing purchases of selected edition
* session list:
  * starting and ending sessions is much faster/doest not reload the page
  * listing sessions is much faster

## 1.5.1 / 2023-11-14 21:10+01:00

## Improved
* Disallow choosing non-game purchase as related purchase
* Improve display of purchases

## 1.5.0 / 2023-11-14 19:27+01:00

## New
* Add stat for finished this year's games
* Add purchase types:
  * Game (previously all of them were this type)
  * DLC
  * Season Pass
  * Battle Pass

## Fixed
* Order purchases by date on game view

## 1.4.0 / 2023-11-09 21:01+01:00

### New
* More fields are now optional. This is to make it easier to add new items in bulk.
  * Game: Wikidata ID
  * Edition: Platform, Year
  * Purchase: Platform
  * Platform: Group
  * Session: Device
* New fields:
  * Game: Year Released
    * To record original year of release
    * Upon migration, this will be set to a year of any of the game's edition that has it set
  * Purchase: Date Finished
* Editions are now unique combination of name and platform
* Add more stats:
  * All finished games
  * All finished 2023 games
  * All finished games that were purchased this year
  * Sessions (count)
  * Days played
  * Finished (count)
  * Unfinished (count)
  * Refunded (count)
  * Backlog Decrease (count)
* New workflow:
  * Adding Game, Edition, Purchase, and Session in a row is now much faster

### Improved
* game overview: simplify playtime range display
* new session: order devices alphabetically
* ignore English articles when sorting names
  * added a new sort_name field that gets automatically created
* automatically fill certain values in forms:
  * new game: name and sort name after typing
  * new edition: name, sort name, and year when selecting game
  * new purchase: platform when selecting edition

## 1.3.0 / 2023-11-05 15:09+01:00

### New
* Add Stats to the main navigation
* Allow selecting year on the Stats page

### Improved
* Make some pages redirect back instead to session list

### Improved
* Make navigation more compact

### Fixed
* Correctly limit sessions to a single year for stats

## 1.2.0 / 2023-11-01 20:18+01:00

### New
* Add yearly stats page (https://git.kucharczyk.xyz/lukas/timetracker/issues/15)

### Enhancements
* Add a button to start session from game overview

## 1.1.2 / 2023-10-13 16:30+02:00

### Enhancements
* Durations are formatted in a consisent manner across all pages

### Fixes
* Game Overview: display duration when >1 hour instead of displaying 0

## 1.1.1 / 2023-10-09 20:52+02:00

### New
* Add notes section to game overview

### Enhancements
* Make it possible to add any data on the game overview page

## 1.1.0 / 2023-10-09 00:01+02:00

### New
* Add game overview page (https://git.kucharczyk.xyz/lukas/timetracker/issues/8)
* Add helper buttons next to datime fields
* Add copy button on Add session page to copy times between fields
* Change fonts to IBM Plex

### Enhancements
* Improve form appearance
* Focus important fields on forms
* Use the same form when editing a session as when adding a session
* Change recent session view to current year instead of last 30 days
* Add a hacky way not to reload a page when starting or ending a session (https://git.kucharczyk.xyz/lukas/timetracker/issues/52)
* Improve session list (https://git.kucharczyk.xyz/lukas/timetracker/issues/53)

### Fixes

* Fix session being wrongly considered in progress if it had a certain amount of manual hours (https://git.kucharczyk.xyz/lukas/timetracker/issues/58)
* Fix bug when filtering only manual sessions (https://git.kucharczyk.xyz/lukas/timetracker/issues/51)


## 1.0.3 / 2023-02-20 17:16+01:00

* Add wikidata ID and year for editions
* Add icons for game, edition, purchase filters
* Allow filtering by game, edition, purchase from the session list
* Allow editing filtered entities from session list

## 1.0.2 / 2023-02-18 21:48+01:00

* Add support for device info (https://git.kucharczyk.xyz/lukas/timetracker/issues/49)
* Add support for purchase ownership information (https://git.kucharczyk.xyz/lukas/timetracker/issues/48)
* Add support for purchase prices
* Add support for game editions (https://git.kucharczyk.xyz/lukas/timetracker/issues/28)

## 1.0.1 / 2023-01-30 22:17+01:00

* Make it possible to edit sessions (https://git.kucharczyk.xyz/lukas/timetracker/issues/46)
* Show markers on smaller graphs to make it clearer which dates the session belong to
* Show only last 30 days on the homepage (https://git.kucharczyk.xyz/lukas/timetracker/issues/47)

## 1.0.0 / 2023-01-20 19:54+01:00

* Breaking
  * Due to major re-arranging and re-naming of the folder structure, tables also had to be renamed.
* Fixed
  * Sort form fields alphabetically (https://git.kucharczyk.xyz/lukas/timetracker/issues/39, https://git.kucharczyk.xyz/lukas/timetracker/issues/40)
  * Start session button starts different game than it says (#44)

## 0.2.5 / 2023-01-18 17:01+01:00

* New
  * When adding session, pre-select game with the last session
* Fixed
  * Start session now button would take up 100% width, leading to accidental clicks (https://git.kucharczyk.xyz/lukas/timetracker/issues/37)
* Removed
  * Session model property `last` is already implemented by Django method `last()`, thus it was removed (https://git.kucharczyk.xyz/lukas/timetracker/issues/38)

## 0.2.4 / 2023-01-16 19:39+01:00

* Fixed
  * When filtering by game, the "Filtering by (...)" text would erroneously list an unrelated platform
  * Playtime graph would display timeline backwards
  * Playtime graph with many dates would overlap (https://git.kucharczyk.xyz/lukas/timetracker/issues/34)
  * Manually added times (= without end timestamp) would make graphs look ugly and noisy (https://git.kucharczyk.xyz/lukas/timetracker/issues/35)

## 0.2.3 / 2023-01-15 23:13+01:00

* Allow filtering by platform and game on session list (https://git.kucharczyk.xyz/lukas/timetracker/issues/32)
* Order session by newest as preparation for https://git.kucharczyk.xyz/lukas/timetracker/issues/33

## 0.2.2 / 2023-01-15 17:59+01:00

* Display playtime graph on session list (https://git.kucharczyk.xyz/lukas/timetracker/issues/29)
* Fix error when showing session list with no sessions (https://git.kucharczyk.xyz/lukas/timetracker/issues/31)

## 0.2.1 / 2023-01-13 16:53+01:00

* List number of sessions when filtering on session list
* Start sessions of last purchase from list (https://git.kucharczyk.xyz/lukas/timetracker/issues/19)

## 0.2.0 / 2023-01-09 22:42+01:00

* Show playtime total on session list (https://git.kucharczyk.xyz/lukas/timetracker/issues/6)
* Make formatting durations more robust, change default duration display to "X hours" (https://git.kucharczyk.xyz/lukas/timetracker/issues/26)

## 0.1.4 / 2023-01-08 15:45+01:00

* Fix collectstaticfiles causing error when restarting container (https://git.kucharczyk.xyz/lukas/timetracker/issues/23)

## 0.1.3 / 2023-01-08 15:23+01:00

* Fix CSRF error (https://git.kucharczyk.xyz/lukas/timetracker/pulls/22)

## 0.1.2 / 2023-01-07 22:05+01:00

* Switch to Uvicorn/Gunicorn + Caddy (https://git.kucharczyk.xyz/lukas/timetracker/pulls/4)

## 0.1.1 / 2023-01-05 23:26+01:00
* Order by timestamp_start by default
* Add pre-commit hook to update version
* Improve the newcomer experience by guiding through each step
* Fix errors with empty database
* Fix negative playtimes being considered positive
* Add %d for days to common.util.time.format_duration
* Set up tests, add tests for common.util.time
* Display total hours played on homepage
* Add format_duration to common.util.time
* Allow deleting sessions
* Redirect after adding game/platform/purchase/session
* Fix display of duration_manual
* Fix display of duration_calculated, display durations less than a minute
* Make the "Finish now?" button on session list work
* Hide navigation bar items if there are no games/purchases/sessions
* Set default version to "git-main" to indicate development environment
* Add homepage, link to it from the logo
* Make it possible to add a new platform
* Save calculated duration to database if both timestamps are set
* Improve session listing
* Set version in the footer to fixed, fix main container height
