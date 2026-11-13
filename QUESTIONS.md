# SIMOLA — Clarification Questions and Decisions (Stage 3)

Companion to the existing-system assessment (`ASSESSMENT.md`, private and not published). Answers were collected from the product owner in a guided walkthrough on **2026-11-04**. These answers are the input for the PRD draft. They become final when the PRD is approved.

**Status legend:** ✅ Answered · 🔶 Answered, but a detail is still open · ❓ Open

---

## Decision summary

| ID | Topic | Decision | Status |
|---|---|---|---|
| A1 | MVP scope | AWOS CAT.III with corrected SLA/OLA, login, security and ops fixes, **AWOS ALARM viewer**, **METAR/METREPORT/TAF raw viewer** — **plus validity rules engine, manual bad-data flagging, metadata & calibration registry** (see A3) | ✅ |
| A2 | Long-term systems | All in scope after MVP: **AWOS CAT.I Tambelan**, **AWS Digi (MET garden)**, **AWS Lagoi / Pekan Arba**, **ARG rain gauges** (Tembeling, Setokok, legacy Tanjung Balai Karimun, Bintan Timur, Singkep) | ✅ |
| A3 | Old PRD features | **In MVP:** validity rules engine, manual flagging, metadata & calibration. **Not selected:** SYNOP/ATIS viewer (excluded for now) | ✅ |
| A4 | Codebase | **New repository** in `sistem-monitoring-aloptama/`, porting proven v2 modules. v2 keeps running untouched until cutover | ✅ |
| A5 | Hostname | **New permanent hostname `simola.hilmihanif.my.id`**. The old URL redirects to it after cutover | ✅ |
| B1 | Official SLA definition | **None exists.** SIMOLA's PRD becomes the authoritative definition | ✅ |
| B2 | "CDP up" | Record **both** facts per CDP per minute (ping reachability and "CDP produced AWOS data"). **SLA uses data flow** | ✅ |
| B3 | SLA formula | Show **both views**. Headline **system availability** = minutes where at least one CDP is up. **Per-node uptime** shown alongside | ✅ |
| B4 | Component availability | **Per-component mandatory-field rule** (see B4a) | ✅ |
| B4a | Mandatory fields | ATRH = TEMP+RH · BARO = QNH · ANEM = WS+WD · RVR = RVR · CEL = LR1 · Present Weather = PW · Rain = RA · Solar = SOL · Lightning = LTX. All other fields optional. DCP = any sensor at the site has data. **Admin-editable, with changes logged** | ✅ |
| B5 | CDP data source | **Merge both CDPs per minute.** Record which CDP supplied each minute | ✅ |
| B6 | Reporting periods | **UTC** boundaries, start-inclusive and end-exclusive | ✅ |
| B7 | Thresholds | 99% / 95% colour thresholds are **display only** and Admin-configurable. **No official targets** | ✅ |
| B8 | Jan–Oct 2026 history | **Recompute from CDP log files.** Ping history before go-live cannot be rebuilt and is labelled as such | ✅ |
| B9 | Past figures | **Live recalculation with an audit log** of every change source. Exported reports carry a "generated at" stamp | ✅ |
| B10 | Maintenance exclusions | **Not in MVP.** A later phase adds a maintenance/incident log and an "adjusted" KPI. The data model leaves room for it | ✅ |
| B11 | Validity rule effect | Detections are marked **"suspect"** and count against OLA **only after an Admin confirms** them | ✅ |
| B12 | DCP and validity | **DCP is exempt** from validity rules and manual flags | ✅ |
| C1 | Users | **Station technicians** and the **station head**. Fewer than 10 accounts (PRD review) | ✅ |
| C2 | Public access | Dashboards stay **public**, with **infrastructure details hidden** (IPs, paths, health internals, raw alarm messages). Admin functions need login | ✅ |
| C3 | Roles | **Viewer / Admin.** Viewer = hidden details plus exports, read-only. Admin = everything, including users, rules, flags, metadata, backfill/recompute | ✅ |
| C3a | Role mapping | Technicians = Admin, station head = Viewer (confirmed at PRD review) | ✅ |
| C4 | Sign-in | **Local accounts** (hashed passwords, Admin-created, no self-registration) | ✅ |
| C5 | Language | **Indonesian + English** toggle, Indonesian by default. Technical codes stay as-is | ✅ |
| D1 | Notifications | **Dashboard only for MVP.** Notification channels designed for a later phase | ✅ |
| D2 | AWOS ALARM | **Display only** (active alarms plus history; AWOS's own pending/acknowledged state shown as-is) | ✅ |
| E1 | Retention | **Keep raw 1-minute data and aggregates forever** | ✅ |
| E2 | Existing data | CDP files are **kept indefinitely**, so SIMOLA **re-ingests from source files**. v2's database is not the source of record. v2's live probe samples (from 2026-08-14) are imported as legacy reachability (PRD review) | ✅ |
| E3 | Exports | **Monthly SLA/OLA report as PDF**, plus **CSV export** of availability and raw data for a chosen period | ✅ |
| F1 | Hosting | **This single shared host** under Coolify. Keep the footprint small, with resource limits | ✅ |
| F2 | Backup destination | **Not decided.** Must be free or already owned (PRD review). Design for a pluggable off-host target; backups only on request (Product Owner, 2026-11-04) | ❓ |
| F3 | Staging | **Yes, on this host:** a second Coolify app on its own subdomain, from a staging branch, with its own small DB and read-only CDP mounts | ✅ |
| F4a | AWS/ARG source | BMKG MQTT broker availability **not confirmed** | ❓ |
| F4b | Tambelan source | **Tailscale/VPN to its CDP** (mount or sync its share) | ✅ |
| F5 | Operator | **Only the product owner.** Favour simple, documented, automated procedures | ✅ |
| G1 | Stack | **Keep:** PostgreSQL 16 + TimescaleDB, Python/FastAPI, Vue 3 + Vite + ECharts + Tailwind, Docker Compose on Coolify, Cloudflare Tunnel | ✅ |
| G2 | Frontend language | **TypeScript** | ✅ |
| G3 | Migrations | Plain `.sql` migrations with an improved runner: checksums, advisory lock, transactional apply, separate migrate step (confirmed at PRD review) | ✅ |
| G4 | Multi-system data model | **One wide table per system type** plus a shared registry driving one availability engine | ✅ |
| G5 | DB cutover | **New database, run in parallel** with v2 until SIMOLA's figures are accepted | ✅ |

---

## Implications noted for the PRD

1. **The MVP is now large.** It includes CAT.III corrections, auth, alarms, reports, the validity engine, flagging, metadata/calibration, exports, bilingual UI, staging and backups. The PRD will propose an **internal release order** within the MVP (e.g. foundation and correct KPIs → admin and data-quality features → reports and exports) for approval.
2. **Validity, flagging and live recalculation** (B9, B11) need a recompute job, an audit log, and "suspect → confirmed" states. Confirmed flags and detections must be reproducible: who, when, which rule and which parameters.
3. **Public dashboards with hidden details** (C2) mean the API needs separate public and authenticated response shapes, not just hidden UI elements.
4. **Mandatory fields are Admin-editable** (B4a) and figures are live (B9). Changing a rule therefore recalculates history, and that change must appear in the audit log.
5. **Re-ingestion from files** (B8, E2) makes the 1-minute files the source of record. SIMOLA keeps per-CDP raw facts, so the merge (B5) can always be recomputed.

## PRD review decisions (2026-11-04)

Open items from PRD v0.1 (§18.2), answered in a second walkthrough. They are applied in PRD v0.2.

| PRD item | Decision |
|---|---|
| OPEN-03 | Technicians = Admin, station head = Viewer, fewer than 10 accounts |
| OPEN-04 | Import v2's live probe samples as "legacy (v2)" reachability at cutover (v2 backfill rows excluded) |
| OPEN-05 | Improved plain-SQL migration runner |
| OPEN-06 | A CDP record with all fields missing counts as data flow (SLA up); components count it as missing |
| OPEN-07 | CDP1 preferred when both CDPs have a minute |
| OPEN-08 | Validity rule starting values proposed from historical data, reviewed by the Product Owner before enabling |
| OPEN-09 | Public repository with strict rules (no secrets or internal addresses; blocking secret scan; sensitive documents such as `ASSESSMENT.md` kept out) |
| OPEN-10 | After the MVP: Tambelan CAT.I first, then AWS/ARG |
| OPEN-12 | Mandatory-field changes apply to all history |
| OPEN-13 | Logged-in only: whole alarm viewer (incl. message text), serial/part numbers, suspect detections. Public sees only the active-alarm count |
| OPEN-14 | Targets accepted: freshness ≤ 3 min; fault visible ≤ 5 min; KPI pages ≤ 1 s up to 1 year; availability ≥ 99 %/month; RPO 24 h; RTO 4 h; quarterly restore drills; 7 daily / 4 weekly / 12 monthly backups |
| OPEN-15 | Staging at `simola-staging.hilmihanif.my.id` behind Cloudflare Access |
| OPEN-17 | Component in-service periods (Must) |
| OPEN-18 | Cutover after R1 acceptance, following a one-month parallel run |
| AS-6 | Free or already-owned services only |

## Changes after PRD approval

Decisions the Product Owner made while building and switching over. Each is recorded in the PRD revision history.

| Date | Item | Decision | PRD |
|---|---|---|---|
| 2026-11-04 | OPEN-14, backups | Backups run only on request; no nightly schedule | v1.3 |
| 2026-11-04 | §14.5, v2 figures | The v2 figure comparison is dropped: v2's numbers were not accurate, v2 is a reference only | v1.3 |
| 2026-11-09 | FR-DSH-001 | Dashboard approved from screenshots: a panel per system and cards across systems | v1.2 |
| 2026-11-11 | OPEN-18 | Go for the cutover; the one-month parallel run is waived. Switched on 2026-11-11; v2 stopped (not removed), its auto-deploy off | v1.3, v1.4 |
| 2026-11-11 | U6 | The Product Owner reviews the monthly PDF instead of the station head (no Viewer account on staging) | v1.3 |
| 2026-11-13 | OPEN-13 | The public sees no AWOS alarm information at all, not even the active-alarm count | v1.4 |
| 2026-11-13 | FR-L10N-001 | System, site, sensor and parameter names and aviation weather terms stay in English in the Indonesian interface | v1.4 |

## Still open

| ID | Open item | Needed by |
|---|---|---|
| F2 / OPEN-01 | Which free or already-owned off-host backup destination (Cloudflare R2 free tier, Google Drive, LAN machine) | Deferred by the Product Owner (2026-11-13); before v2 is removed |
| F4a / OPEN-02 | Whether the BMKG MQTT broker (AWS/ARG) is still available, with credentials | AWS/ARG phase |
| OPEN-11 | Verify alarm timestamps are UTC | On site, when convenient |
| OPEN-16 | Monthly PDF layout sign-off | The Product Owner's U6 pass |
| AS-5 | No external system read v2's API | The Product Owner's confirmation (v2 is stopped, so anything that did has stopped working) |
| — | Redirect the old hostname `rhf-monitoring.hilmihanif.my.id` to SIMOLA (it answers 404 since v2 stopped) | Deferred by the Product Owner (2026-11-11) |
