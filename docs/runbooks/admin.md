# Runbook: Admin operations (R2.2, R2.3)

PRD FR-ADM-002, FR-ADM-003, FR-REG-003, FR-REG-006, FR-DQ-006/007; design in [../design/r2.md](../design/r2.md)
§3 and §4.3. All of this is in
**Admin** (Admins only), every change is in the audit log with before and after, and rule changes recompute the
figures in the background. Accounts and the audit log: [accounts.md](accounts.md).

## Jobs (Admin → Jobs)

| Job | Does | When |
|---|---|---|
| Reprocess from CDP files | Reads both CDPs' 1-minute files again for the chosen UTC days, replaces the stored minutes and recomputes the figures | After a share outage or a corrected file |
| Recompute figures | Recomputes the daily figures from the stored minutes, without reading files | After a rule change (queued automatically) |

- Days run newest first; the page shows progress, who started the job, its log, and a *Cancel* while it runs.
  Days already done stay done.
- Only one reprocess at a time. A whole history (about 317 days) takes about 21 minutes on staging.
- The command line still works (`simola reprocess`, `simola recompute`, [history.md](history.md)); those jobs show
  "cli" as who started them.

## Settings (Admin → Settings)

- **Availability colours:** green from / amber from (display only, not targets).
- **Waiting time for data:** a minute is judged this many minutes after it ends (1–15), so a file written a little
  late is not counted as missing. Past days are not affected.
- **Problems panel:** when each item appears (1–120 minutes).

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

## How the rest of SIMOLA follows

- The worker checks for registry changes before every rollup (every 30 s) and reloads the rules; recompute jobs
  always read them fresh.
- Each API process keeps the registry for up to 60 s, so a page may show the old rules for up to a minute.
- Flags are read from the database on every request (no cache): pages show a new flag at once, and its figures
  once the recompute is done.
