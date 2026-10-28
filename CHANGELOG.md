# Changelog

Notable changes to Procare Connect. Versions follow semantic versioning, and the release workflow sets `manifest.json`'s version from the release tag.

## [0.1.0] - 2026-10-28

First version.

### Added
- UI setup with the Procare parent email and password, reauth when the password stops working, and a polling interval option (15 to 180 minutes, 60 by default).
- Per child daily counters for bottles, bottle ounces, diapers (wet, BM), potty (pee, BM, tried), meals, naps and nap minutes, all resetting at local midnight.
- Last bottle, bottle ounces, diaper, potty, meal, nap end, sign-in, sign-out and activity times.
- An `at_daycare` presence sensor.
- An activity event entity that fires once per new activity, plus `nap_end` when a logged nap gets its end time.
- Diagnostics with counts and field names only.
