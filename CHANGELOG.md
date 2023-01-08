## Unreleased

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