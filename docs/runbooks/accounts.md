# Runbook: accounts, sign-in and the audit log (R2.1)

PRD FR-AUTH-001…007, FR-AUD-001…002; design in [../design/r2.md](../design/r2.md) §4.1–4.2.

## Roles

| Role | Who | Can |
|---|---|---|
| Public | anyone, no account | dashboards, figures, sensor charts |
| Viewer | the station head | also infrastructure details (system health page) |
| Admin | technicians | also the Admin area: users, audit log (later phases add data quality, records, settings, jobs) |

The server checks the role on every request; the screens only hide what a role cannot use.

## First Admin (once per environment)

There is no self-registration. After the first deploy with R2.1, create the first Admin in the worker container
(Coolify: the application's *Terminal* → `worker`, or on the host `docker exec -it <worker-container> …`):

```bash
simola create-admin --username <name> --display-name "<Full name>"
```

It asks for the password twice (at least 12 characters, not containing the username, not a common password) and
refuses if an active Admin already exists. Everyone else is created in **Admin → Users**.

## Everyday account work (Admin → Users)

- **New user:** username (it cannot change later), full name, optional email, role. SIMOLA shows a **temporary
  password once**; give it to the person in person or by phone. They must choose their own at the first sign-in.
- **Forgotten password:** *Edit* → *Reset password*. This gives a new temporary password and signs the user out
  everywhere.
- **Leaving staff:** untick *Account active*. Accounts are never deleted, so the audit log keeps their history;
  their sessions end at once.
- You cannot demote or deactivate your own account, and SIMOLA always keeps at least one active Admin.

## Locked out

- **5 wrong passwords for a username within 15 minutes lock it for 15 minutes.** The Users page shows "locked
  until". An Admin's reset unlocks it at once. Usernames that do not exist lock the same way, so the sign-in page
  never reveals which accounts exist.
- **20 failed sign-ins from one address within 15 minutes** refuse further attempts from that address until the
  older failures are more than 15 minutes old.
- **Every Admin locked out or the password forgotten:** on the server, in the worker container:
  ```bash
  simola create-admin --username <admin-name> --reset
  ```
  It sets the password you type, unlocks and reactivates that Admin, signs them out everywhere and writes an audit
  entry.

## Sessions

A session ends after 8 hours without use, 7 days after sign-in, at sign-out, when the password changes (other
sessions only), and when an Admin resets the password or deactivates the account. The cookie is HttpOnly, Secure
and SameSite=Lax; the database stores only a hash of it. Every change also needs the CSRF token (double submit).

## Audit log (Admin → Audit log)

Every sign-in (success and failure, with the address), lock, sign-out, password change, account change and reset,
and every audit export. Filter by date, who, action and object; *Export CSV* downloads the filtered entries (cells
that a spreadsheet could run as a formula are prefixed with `'`).

**Nobody can change or delete entries:** the application's database role has no UPDATE, DELETE or TRUNCATE on
`audit_event`, and a trigger refuses them for every role. Removing entries would need the database owner to
disable that trigger by hand, which is outside SIMOLA.

## Cloudflare Access (decision D4)

- **Staging:** the whole hostname stays behind Access (NFR-SEC-008); people pass Access, then sign in to SIMOLA.
- **Production, once R2.1 is there:** drop Access for the Viewer pages (SIMOLA's sign-in protects them) and keep an
  Access policy on `/admin*` and `/api/v1/admin*` as a second lock. Admins then pass an Access email code, then
  sign in to SIMOLA.
- `tools/security_check.py --public …` checks that the Admin area answers with the Access login.

## Checks

```bash
python3 tools/security_check.py --web http://<address>:8080 --public https://<hostname> --containers <app>
```

Its `accounts` and `writes` lines check that, without a session, Viewer and Admin routes answer 401, every write
without a session and CSRF token is refused, and the CSRF cookie is Secure and SameSite=Lax. Browser tests against
a deployed site sign in with `SIMOLA_E2E_USER` and `SIMOLA_E2E_PASSWORD` (a Viewer account made for testing).
