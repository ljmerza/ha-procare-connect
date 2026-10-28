# Procare Connect

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/docs/faq/custom_repositories)
[![Validate](https://github.com/ljmerza/ha-procare-connect/actions/workflows/validate.yaml/badge.svg)](https://github.com/ljmerza/ha-procare-connect/actions/workflows/validate.yaml)
[![Tests](https://github.com/ljmerza/ha-procare-connect/actions/workflows/tests.yaml/badge.svg)](https://github.com/ljmerza/ha-procare-connect/actions/workflows/tests.yaml)
[![Release](https://img.shields.io/github/v/release/ljmerza/ha-procare-connect)](https://github.com/ljmerza/ha-procare-connect/releases)

Home Assistant custom integration that turns your kids' daycare day from Procare Connect into sensors and events. You get daily counts for bottles, diapers, potty, meals and naps, the time of each last one, whether each child is signed in, and an event entity that fires for every new activity so you can build automations and notifications off it.

It reads activity data only. Photos and videos aren't downloaded or exposed at all.

> [!IMPORTANT]
> This is an unofficial integration and isn't affiliated with or endorsed by Procare Solutions. It talks to the same private web API the Procare parent portal uses, which isn't documented and can change or break at any time. It only reads data your own parent account can already see.

> [!WARNING]
> Procare's [Terms and Conditions](https://www.procaresoftware.com/terms-of-use/procare-solutions-terms-of-use/) (updated June 2026, section 6.1) don't allow extracting data from their services with automated tools without Procare's written consent. This integration does that for your own account, so using it is your call and your risk. Procare can suspend or close an account that breaks section 6.1 without warning. It polls once an hour by default and never more than every 15 minutes to stay light on Procare's servers.

## Install

### HACS

[![Open your Home Assistant instance and open this repository in HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=ljmerza&repository=ha-procare-connect&category=integration)

Or add it by hand

1. In HACS open **⋮ → Custom repositories** and add `https://github.com/ljmerza/ha-procare-connect` with category **Integration**.
2. Install **Procare Connect** and restart Home Assistant.

Requires Home Assistant 2026.3 or newer.

### Manual

Copy `custom_components/procare_connect` into `<config>/custom_components/procare_connect` and restart Home Assistant.

## Setup

**Settings → Devices & services → Add integration → Procare Connect**, then sign in with the email and password you use for the Procare parent app or website. Each child on the account gets a device named `<first name> daycare`.

If Procare starts rejecting the saved password, Home Assistant asks you to sign in again from the integration card.

If your account belongs to more than one school, only the default school is read.

## Options

**Polling interval** sets how often Procare is checked for new activities, 15 to 180 minutes (60 by default). It polls around the clock. If Procare answers with a rate limit the integration backs off on its own, up to 30 minutes, and goes back to the normal interval once a poll works again.

## Entities

Entity ids below are for a child named Alex.

### Daily counters

These start over at local midnight. They use `state_class: total` with a `last_reset` at the start of the day, so long-term statistics work and a count can go down when the daycare deletes an activity.

| Entity | What it counts |
|---|---|
| `sensor.alex_daycare_bottles_today` | Bottles |
| `sensor.alex_daycare_bottle_oz_today` | Ounces from bottles, what the child drank when staff recorded it, otherwise what was served |
| `sensor.alex_daycare_diapers_today` | Diaper changes |
| `sensor.alex_daycare_wet_diapers_today` | Wet diapers (`BM & Wet` counts as wet and BM) |
| `sensor.alex_daycare_bm_diapers_today` | BM diapers |
| `sensor.alex_daycare_potty_today` | Potty visits |
| `sensor.alex_daycare_potty_pee_today` | Potty visits with pee |
| `sensor.alex_daycare_potty_bm_today` | Potty visits with a BM |
| `sensor.alex_daycare_potty_tried_today` | Potty visits marked tried |
| `sensor.alex_daycare_meals_today` | Meals and snacks |
| `sensor.alex_daycare_naps_today` | Naps, including one still going |
| `sensor.alex_daycare_nap_minutes_today` | Minutes of finished naps |

### Last times

Timestamps stay unknown until the first one of the day.

| Entity | Value |
|---|---|
| `sensor.alex_daycare_last_bottle` | Time of the last bottle |
| `sensor.alex_daycare_last_bottle_oz` | Ounces of the last bottle |
| `sensor.alex_daycare_last_diaper` | Time of the last diaper change |
| `sensor.alex_daycare_last_potty` | Time of the last potty visit |
| `sensor.alex_daycare_last_meal` | Time of the last meal, with `meal_type`, `desc` and `quantity` attributes |
| `sensor.alex_daycare_last_nap_ended` | When the last nap ended |
| `sensor.alex_daycare_sign_in_time` | First sign-in of the day |
| `sensor.alex_daycare_sign_out_time` | Last sign-out of the day |
| `sensor.alex_daycare_last_activity` | Time of the latest activity of any kind |
| `binary_sensor.alex_daycare_at_daycare` | On while Procare says the child is signed in |

### Activity event

`event.alex_daycare_activity` fires once for each new activity. Event types are `bottle`, `diaper`, `potty`, `nap`, `nap_end`, `sign_in`, `sign_out`, `meal`, `learning`, `mood`, `medication`, `incident`, `note` and `other`. Procare logs diapers and potty as one bathroom type, so the integration splits them by the activity's own type.

`nap_end` fires when a nap that was already logged gets its end time. Staff often log a nap when it starts and fill in the end later (and sometimes never do).

Every event has `kid`, `activity_type`, `time`, `summary`, `comment` and `staff`. Some types add more.

| Event type | Extra attributes |
|---|---|
| `bottle` | `served_oz`, `consumed_oz`, `bottle_type` |
| `diaper` | `bathroom_type`, `sub_type`, `diaper_cream` |
| `potty` | `bathroom_type`, `sub_type` |
| `nap`, `nap_end` | `start`, `end`, `minutes` |
| `meal` | `meal_type`, `desc`, `quantity` |
| `learning` | `text` |
| `sign_in`, `sign_out` | `section` (the classroom) |

Example automation that sends a notification for every diaper change

```yaml
triggers:
  - trigger: state
    entity_id: event.alex_daycare_activity
    not_to:
      - unavailable
      - unknown
conditions:
  - condition: state
    entity_id: event.alex_daycare_activity
    attribute: event_type
    state: diaper
actions:
  - action: notify.mobile_app_phone
    data:
      message: "{{ state_attr('event.alex_daycare_activity', 'kid') }} diaper {{ state_attr('event.alex_daycare_activity', 'sub_type') }}"
```

### Which activities count as new

The first poll after Home Assistant starts (or after the integration reloads) only learns what's already there, so you don't get a burst of the whole day's events. After that each activity fires once, oldest first. At midnight the list of seen activities starts over, so the first activity in the morning fires as usual.

## Children added or removed

A child added to the Procare account shows up as a new device on the next poll. A child that's no longer on the account has its device removed. If Procare ever returns an empty list of children that poll counts as failed and nothing gets removed. You can also delete a leftover device by hand from its device page.

## Known limitations

- It uses an unofficial API. If Procare changes it, things stop working until the integration is updated.
- Your school and Home Assistant should be in the same time zone, because "today" is Home Assistant's local day.
- Activities logged while Home Assistant is down still show up in the counters, but they don't fire events, because the first poll after a restart only catches up.
- Only the default school on the account is read.
- New activities show up within one polling interval, not instantly.

## Diagnostics

**Settings → Devices & services → Procare Connect → ⋮ → Download diagnostics** gives counts by activity type, the field names Procare sent and the polling status. It never includes names, ids, comments, staff, classrooms, URLs or your login, so it's safe to attach to an issue.

## Development

```bash
uv venv --python 3.14 .venv
VIRTUAL_ENV=.venv uv pip install -r requirements_test.txt ruff==0.15.10
.venv/bin/pytest
.venv/bin/ruff check custom_components tests script
```

`requirements_test_min.txt` runs the same tests against Home Assistant 2026.3, the oldest supported version. The snapshot tests only run on the version in `requirements_test.txt`.

All test data is made up. `tests/test_fixtures_clean.py` fails if a fixture or snapshot has a real-looking URL, email, id or token. To build a fixture from a real response, save it under `captures/` (gitignored) and run it through `script/scrub_fixture.py`, which keeps only known fields and swaps every name, id, comment and URL for a fake one. Put private words you never want committed (your kids' names, your school, staff names) in `.scrub-denylist`, also gitignored, and both the scrubber and the tests check for them.

`script/probe.py` makes 3 read-only requests with your login and prints only the shape of the responses. Don't use it to test a wrong password, because repeated failed logins can lock the account.

The icon is generated by `script/render_icon.py`.

## License

MIT
