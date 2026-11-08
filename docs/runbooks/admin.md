# Runbook: Admin operations (R2.2–R2.5, R3.1–R3.2)

PRD FR-ADM-002, FR-ADM-003, FR-REG-003, FR-REG-006, FR-DQ-001..007, FR-REG-004/005; design in
[../design/r2.md](../design/r2.md) §3 and §4.3–4.5. All of this is in
**Admin** (Admins only), every change is in the audit log with before and after, and rule changes recompute the
figures in the background. Accounts and the audit log: [accounts.md](accounts.md).

## Jobs (Admin → Jobs)

| Job | Does | When |
|---|---|---|
| Reprocess from CDP files | Reads both CDPs' files again for the chosen UTC days. *1-minute data* replaces the stored minutes and recomputes the figures; *alarms* and *reports* add any alarm row or report line not stored yet and change no figure. All are ticked by default | After a share outage or a corrected file; once after R3.2 is deployed, *reports* only, from 24 December 2025 to today, to load the report history |
| Recompute figures | Recomputes the daily figures from the stored minutes, without reading files | After a rule change (queued automatically) |

- Days run newest first; the page shows progress, who started the job, its log, and a *Cancel* while it runs.
  Days already done stay done.
- Only one reprocess at a time. A whole history (about 317 days) takes about 21 minutes on staging.
- The command line still works (`simola reprocess [--sources minutes,alarms,reports]`, `simola recompute`,
  [history.md](history.md)); those jobs show "cli" as who started them.
- A reprocess of alarms only takes seconds: an alarm file exists only on days that had an alarm. Reports only:
  three small logs a day per CDP.

## Settings (Admin → Settings)

- **Availability colours:** green from / amber from (display only, not targets).
- **Waiting time for data:** a minute is judged this many minutes after it ends (1–15), so a file written a little
  late is not counted as missing. Past days are not affected.
- **Problems panel:** when each item appears (1–120 minutes).
- **Calibration "due soon":** how many days before its due date a calibration shows as due soon (1–180, default
  30).

Each section saves on its own. Nothing here changes stored minutes.

## Mandatory fields (Admin → Mandatory fields)

A component counts as available in a minute only when all of its mandatory fields have a value. Before saving, the
page shows this month's figure per site now and with the change. Saving:

- applies to **every period** since data began (OPEN-12);
- queues a full recompute (Admin → Jobs);
- is refused if a component would be left without a mandatory field it reports at its site (for example RVR with
  only ALS, which runway 22 does not have): SIMOLA could not load its registry otherwise.

The DCP rule (available when any field of its site has a value) is fixed.

## Components and in-service periods (Admin → Registry)

A component's in-service period (UTC, either end optional) limits its expected minutes: before *from* and after
*until* nothing is expected, so a sensor that is not yet installed, removed or being replaced does not lower
availability. Saving recomputes only the days between the old and the new dates.

## Records (Admin → Registry)

The registry page also holds the records (FR-REG-004):

- **Station:** WMO number (5 digits), airport name, coordinates, elevation, procurement year (1950 to this year),
  notes. Name and ICAO code stay as the registry has them.
- **Each site:** coordinates, elevation, threshold elevation, description.
- **Each sensor** (*Open* → Details): sensor type, manufacturer, model, part number, serial number, installed on
  (not in the future), firmware, notes.

Everyone sees these on the site pages, **except serial and part numbers, which only signed-in users see**. A save
replaces the whole record; every change is audited with before and after. Records never change a figure.

## Calibration (Admin → Calibration, or a sensor's Calibration tab)

Each sensor's calibrations: date (UTC, not in the future), performed by, certificate number, the date the
certificate was validated, notes, and the next due date, given as a date or as an interval of 1–120 months
(31 January + 1 month = 28 or 29 February). The status comes from the **latest** record and is worked out when a
page is opened, so it moves on by itself:

| Status | When |
|---|---|
| OK | due later than the "due soon" window |
| Due soon | due within the window (Settings), the due day included |
| Overdue | from the day after the due date; also a **minor** Problems item, which everyone sees |
| Unknown | no record yet |

**Certificate pending:** leave the validation date empty while the certificate is still being validated. The
sensor then shows "certificate pending" next to its status (calibration list, registry, site pages); enter the
date when the document is validated. It cannot be before the calibration date. The next due date still counts
from the calibration date.

DCPs are not calibrated. Records can be corrected or removed; a removed record leaves the history (the status falls
back to the one before it) but stays in the database and the audit log (PRD §9.6).

Signed-in users also see, in the board's component panel and the day view, **what changed this component's
figures** in the period: flags on it, decisions on its detections, mandatory-field and in-service changes, and
reprocess or recompute jobs over the period (FR-AUD-003).

### Loading many records at once

`simola import-records <file.json> --actor <name> [--dry-run]` (in the worker container) loads sensor records and
calibrations from a JSON file, for example what the station already knew before SIMOLA:

```json
{"components":   [{"site": "04", "type": "ATRH", "installed_on": "2025-12-23"}],
 "calibrations": [{"site": "04", "type": "ATRH", "date": "2025-12-27", "performed_by": "…",
                   "interval_months": 12, "validated_on": "2025-12-31", "notes": "…"}]}
```

- Every entry is checked with the same rules as the screens first; one refusal stops the import and nothing is
  written (the command lists every problem). `--dry-run` checks and counts, then writes nothing.
- A component entry changes only the fields it names. A calibration is skipped when the sensor already has one on
  that date, so running the same file twice adds nothing.
- Every change is in the audit log under `--actor`, like a change made in the screens. Records never change a
  figure, so nothing is recomputed.

## Manual flags (Admin → Flags, sensor charts, minute map)

A flag marks a UTC time range of one or more components as bad data. Flagged minutes count as lost for those
components only: SLA, the CDPs' uptime and the DCPs are never affected.

- **Where:** on a sensor chart (*Flag a range*, then drag across the bad data), in the minute map of a component's
  day (*Flag minutes*, then drag or click the first and last minute), or from scratch in Admin → Flags. Sky,
  weather and lightning views start from the whole chart window; adjust the times in the form.
- **What it needs:** components (never a DCP), from and until in UTC (the *until* minute is not included), a
  reason (sensor fault, maintenance, calibration, environmental, other) and a note of 3–500 characters.
- **Past only:** the range must end by the current minute. Flag work that is still going on once it is finished.
- **What it costs:** before saving, the form shows per component how many valid minutes will count as lost.
  Minutes already lost (no data, a missing field, another flag) keep their cause and are not counted twice; a
  minute under two flags belongs to the older one.
- **After saving:** the days it touches are recalculated (Admin → Jobs, usually well under a minute); the board says
  so until it is done. Charts shade the range with its reason, the minute map shows the minutes as *Flagged*, and
  the outage list shows *Flagged · reason*.
- **Who sees what:** everyone sees the time and the reason; the note and who flagged it are shown to signed-in users
  only.
- **Editing and removing:** both are recalculated and audited. A removed flag stays in the list (*Show removed
  flags*) and in the audit log; its minutes count as they did before.
- **For a long absence** (a sensor removed for weeks) set its in-service period instead; the form suggests it for
  ranges over 31 days.

**Staging until R1 is accepted:** no flags in December 2026 or in the two reference months. The acceptance recount
(`tools/recount.py --daily`) counts the raw files and knows nothing about flags. Test flags (UAT U4) go on another
month and are removed after the test; the recount then matches again.

## Validity rules (Admin → Validity rules)

A rule checks one measured field of a component type, at every site or at one site (a site's rule replaces the
all-sites rule of the same kind there, even when it is off):

| Rule | Suspect when | Parameters |
|---|---|---|
| Range | a value is below the minimum or above the maximum | min and/or max |
| Stuck | the same value lasts this many minutes or more | minutes (5–1440); values allowed to stay (0 for rain) |
| Spike | the change between valid minutes is larger than this | largest normal change; within N minutes (1–60) |

Missing values never fire a rule; a missing minute ends a stuck run and is never compared by a spike rule. Text
fields (present weather, sky, lightning) and gust events have no rules.

- **Proposed rules (OPEN-08):** `simola propose-rules` (in the worker container) works out each field's history
  and creates a range, a stuck and (for temperature, dew point, humidity, QNH, density altitude) a spike rule, all
  **off**. The rules page shows them in blue. Open one: the history box shows the usual range, the extremes, the
  longest unchanged run and the largest minute-to-minute change; the dry run shows what it would have raised over
  the last 30 days. Adjust, then tick *Approve and turn on*.
- **Every save is a new version, and only the newest is in effect.** The editor lists them newest first: "in
  effect", then "replaced <time>", each with what it changed (values, scope, turned on or off, approved). Saving
  stays disabled until something changes.
- **A new version replaces the old ones.** Their open suspects are withdrawn from the review queue (the editor says
  how many); confirmed and rejected detections keep the version that raised them, and confirmed ones keep counting.
  Turning a rule on, or changing one that is on, re-checks the whole history as a job (Admin → Jobs, *Run validity
  rules*); turning it off withdraws its open suspects too.
- **Deleting:** a rule that never raised anything (made by mistake) can be deleted; one that did can only be turned
  off, because its detections name it. Versions are never deleted.
- **Overlaps:** the editor warns when a site rule replaces the all-sites rule of its kind there (or when sites keep
  their own), and the dry run counts stretches other rules of the field already raised.
- **When rules run:** the worker checks the latest minutes every minute; a reprocess checks its days again.

## Review queue (Admin → Review queue)

A rule's hit is a **suspect**: it changes nothing. Open one to see the field's chart around it, what the rule saw
and what confirming would change; confirm (bad data) or reject (data is fine) with an optional note, or tick
several and decide them together. Decisions can be reversed later; each is in the audit log.

- **Confirmed on a mandatory field:** the component is unavailable for that stretch; the days are recalculated.
  Minutes already lost (no data, a missing field, a flag) are not counted twice; flags come first.
- **Confirmed on an optional field:** the field is marked bad; the figures do not change.
- **Rejected:** not raised again by the same rule version, even when the stretch grows.
- **Who sees what:** confirmed detections are shown to everyone (time and rule); suspects, rejected ones, notes and
  who decided are for signed-in users. Signed-in users also get a Problems item while suspects wait.

**Staging until R1 is accepted:** do not confirm detections in December 2026 or in the two reference months (the
acceptance recount counts the raw files). Rejecting is harmless.

## AWOS alarms (Alarms page; Admin → Alarm mapping)

The worker reads `alarm/091ALARM.<date>.dat` from both CDPs every minute (FR-ING-008). It reads every alarm file on
the shares when it starts and then hourly, so the history since 24 December 2025 loads by itself and a day missed
while the worker was down is caught up. The health page shows each CDP's alarm reader.

- **Each change once.** Each CDP runs its own alarm detection, so both usually log the same change, seconds apart
  (once 85 s apart). Rows with the same name, type, state, active flag and message from different CDPs within
  2 minutes of each other are one change, listed with both CDPs. Each CDP's rows are kept as read, so re-reading a
  file adds nothing.
- **Active.** The AWOS logs a raise far more reliably than a clear: an alarm is often raised again with no clear
  in between, and on 6 November 2026, 47 of the 75 alarm names had "active" as their latest change, some since
  December 2025. So an alarm counts as **active** only while its latest change says active and is at most
  **24 hours** old. Older ones are listed under *older alarms with no clear logged* on the Alarms page, and are not
  counted in the Problems panel.
- **Raised** marks a change that raised the alarm; an acknowledgement of an alarm already active is shown as
  *Acknowledged*. The per-day chart and the day view's minute outlines count raises only.
- **Who sees what.** The public sees only "N active AWOS alarms" in the Problems panel. The list, the history, the
  site pages' alarms and the day view's alarms are for signed-in users: one AFTN alarm message contains a network
  address.
- **Mapping.** A name is placed when it is first seen: the 75 names seen up to 6 November 2026 from their name
  (DCPA = Runway 04, DCPB = Middle, DCPC = Runway 22; the rest of the name gives the sensor; GPS, AFTN and the
  barometer-range alarm are the station; `RLS0_Missing` is Runway 04). A name not seen before arrives **not
  assigned** and is listed first under Admin → Alarm mapping. A change there applies to the whole history at once
  and is audited (`alarm_mapping_changed`).
- SIMOLA never acknowledges an alarm; that is done on the AWOS.

## METAR, MET REPORT and TAF (the reports page)

The worker reads `reports/METAR.<date>.log`, `METREPORT.<date>.log` and `TAF.<date>.log` from both CDPs every
minute: today's, and yesterday's for the first two hours of the day (FR-ING-009). It does not read older logs by
itself (FR-ING-010): after the R3.2 deploy, start one reprocess job with only *reports* ticked, from 24 December
2025 to today. The health page shows each CDP's report reader.

- **Each report once.** Each CDP logs the reports it sends, usually both, up to two minutes apart (the widest pair
  seen was 117 s). Lines with the same text from different CDPs within 2 minutes are one report, listed with both
  CDPs. A CDP that logs the same report twice sent it twice: both are kept. Each CDP's lines are kept as read, so
  re-reading a log adds nothing.
- **Different texts are different reports.** On some evenings the CDPs logged different METARs for the same time
  (e.g. 1 November 2026, 21:30–23:30: CDP1 an `AUTO` report, CDP2 another); both are listed, each with its CDP.
- **Never decoded** (FR-RPT-004): the text is shown and copied exactly as issued. The AWOS's notes after the `=`
  (runway in use, why a SPECI or SPECIAL was sent) are shown as labels beside it.
- **Public**, like the reports: the latest of each type, a UTC day's archive, and a search over at most 31 days.
- A line still being written (no line end yet), or a TAF without its `=` at the end of the log, is read on the next
  cycle. Lines that cannot be read are counted as parse warnings on the health page.

## How the rest of SIMOLA follows

- The worker checks for registry changes before every rollup (every 30 s) and reloads the rules; recompute jobs
  always read them fresh.
- Each API process keeps the registry for up to 60 s, so a page may show the old rules for up to a minute.
- Flags are read from the database on every request (no cache): pages show a new flag at once, and its figures
  once the recompute is done.
