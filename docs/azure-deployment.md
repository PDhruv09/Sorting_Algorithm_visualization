# Phase 2: Azure SQL deployment

The existing Express Container App stays in `sorting-visualizer-rg`. The new
database is independent of its container filesystem, so replacing an image will
not remove attempts. No Azure resource is created or changed by application startup.

## Current resources

- App: `sorting-visualizer`, environment: `sorting-visualizer-env`
- Database: `sorting-challenge-db`
- Server: `sorting-visualizer-sql-dhp005.database.windows.net`
- User-assigned identity: `sorting-visualizer-db-identity`, already attached to the app
- Identity client ID: copy the **Client ID** from this managed identity's Azure Overview page; configure it in the Container App environment, not this repository.
- Database identity has been created as an external user. CONNECT alone is insufficient.

These identifiers are not passwords. The application uses the attached identity
to obtain tokens. No database password or API key belongs in GitHub, the image,
or browser JavaScript.

## Manual database steps (database administrator)

1. Open `sorting-challenge-db` > Query editor and connect with your Entra account.
2. Run `docs/azure_schema_v1.sql`. It creates four tables in a transaction:
   schema version, authorized students, attempts (including question/choice snapshots),
   and hashed sessions. It refuses to adopt unversioned existing tables.
3. Run `docs/azure_permissions.sql`. It grants this app SELECT on students and
   schema version, SELECT/INSERT/UPDATE on attempts, and SELECT/INSERT/DELETE
   on sessions. Real email addresses are intentionally absent from this script.
4. Add authorized emails privately to `dbo.students` as the administrator. If you
   already ran the earlier demo seed script, that database entry remains; removing
   the address from repository files does not remove it from Azure.
5. Confirm success before changing the application image. These scripts do not
   import the local SQLite database. Existing local attempts remain local.

The app cannot modify the roster or create/drop tables. Add/disable students as
the administrator using parameterized tooling or carefully reviewed SQL; do not
put a class roster into a public repository or container image.

## Network access

The browser's client-IP firewall rule only enables your administrative connection.
It does not establish connectivity from the Container App. Verify the app's actual
outbound networking and allow its applicable outbound addresses on the SQL server.
Do not substitute the app's inbound IP. Outbound addresses can change; confirm
the current values before relying on an allowlist.

The SQL option "Allow Azure services and resources to access this server" permits
network access from other Azure customers too (database authentication still
applies). Prefer narrowly scoped firewall rules. If stable outbound addresses are
unavailable, review the networking options and costs before choosing a broader
exception or adding VNet/NAT/private networking. No broad exception is required
or enabled by these files.

## Image and Container App settings

Local SQLite remains the default. Compose explicitly configures local SQLite and
its named volume. Merely editing `.env` does not forward every variable into Compose.
For Azure, configure these environment variables on the new revision:

| Variable | Value |
| --- | --- |
| `APP_ENV` | `production` |
| `CHALLENGE_PUBLIC_ORIGIN` | `https://sorting-visualizer.graycliff-f74894db.canadacentral.azurecontainerapps.io` (no trailing slash) |
| `CHALLENGE_MODE_ENABLED` | `1` |
| `CHALLENGE_DB_BACKEND` | `azure_sql` |
| `CHALLENGE_SQL_SERVER` | `sorting-visualizer-sql-dhp005.database.windows.net` |
| `CHALLENGE_SQL_DATABASE` | `sorting-challenge-db` |
| `CHALLENGE_SQL_CLIENT_ID` | Your managed identity's **Client ID** from Azure (not its Object/principal ID) |
| `CHALLENGE_TEST_VERSION` | `sorting-15-v3` |
| `CHALLENGE_FEEDBACK_RELEASED` | `0` |
| `CHALLENGE_LOCAL_HTTP` | `0` |
| `CHALLENGE_ACCESS_REQUESTS_PER_MINUTE` | `240` for the classroom profile; default `20` |
| `CHALLENGE_WRITE_REQUESTS_PER_MINUTE` | `2400` for the classroom profile; default `120` |

For the 70-student image/replica/limit update and rollout checks, see
[classroom-rollout.md](classroom-rollout.md). Rate limits are per reported client
IP per application process; they are not per-student quotas.

Use the tested image's immutable commit SHA tag from GHCR, after a successful
package build. The existing workflow runs on `main` pushes or manual dispatch;
a push to `phase-2-challenge-mode` alone is not a deployment. No workflow edits
are needed for the database adapter. Publishing and Azure revision changes remain
manual decisions. Keep the old image tag for code rollback; database data is separate.

In the new revision's container console, run `python3 -m challenge_sql`. This
read-only check validates authentication and schema access and prints the database
and SQL user. It does not prove write permissions or the full student flow.
Then test an unauthorized email, authorized access, save/refresh/resume, all 15
answers, final score, returning to the score, and persistence after a revision
replacement. Inspect the resulting test attempt as administrator. Keep real
students out until these Azure checks pass.

The ordinary `/health` endpoint deliberately does not query the database: frequent
health checks would keep a serverless database awake. The adapter disables pooling
and closes each connection after use. A paused database may take time to wake;
students retain their draft and can retry when a request fails. Writes are not
automatically replayed after an uncertain commit. Login timeout is 60s to allow
serverless resume; query timeout is 15s. Login timeout is passed to the driver,
not included in the connection string. A first connection during resume may
still need to be retried by the user. For database-unavailable error 40613, the
adapter retries login up to four times with delays of 5, 10, 20 and 30 seconds,
before any application SQL runs. A 90-second retry budget bounds whether another
attempt is started, and remaining budget caps the next driver's login timeout
at 60 seconds. Managed-identity timing remains driver-controlled. Other login
failures, queries and commits are not retried. Lock timeout is bounded separately:
lock waits 10s; managed-identity token acquisition has the driver's own timing.

### Investigating intermittent 503 responses

Compare `/health` with the failed `/api/challenge/...` request. A healthy app does
not establish SQL availability, because the health endpoint never queries SQL.
An anonymous `/api/challenge/current` returns 401 without contacting SQL too.

In Container App console logs, look for `Azure SQL failure` at the failure's UTC
time. It records `stage`, `native_code`, `sqlstate` and elapsed seconds, without
the raw driver message, connection string, email or answer. A login retried for
40613 records `Azure SQL login retry`. Unrecognized driver diagnostic formats
produce `None` codes and are not automatically retried.

For error 40613, compare SQL database pause/resume activity with that timestamp;
the code means temporary database unavailability and does not by itself prove
auto-pause. For persistent errors inspect identity, firewall, schema and grants
using the read-only diagnostic above. Preserve the failing request path, HTTP
status and timing. A browser network disconnection and an HTTP 503 are different
failure observations. Do not clear student attempts to troubleshoot either one.

The browser also retries only GET `/current` checks on temporary 503 responses,
with up to four waits of 5, 10, 20 and 30 seconds. It stops scheduling retries
after a 90-second budget; an already running request may finish later. During
recovery it displays a reconnecting message, disables save/navigation controls,
and preserves unsaved choices in the open tab. A confirmed 401 returns to email
entry and keeps the draft for a same-email resume. `/access` checks the roster;
`/current` checks the session. Browser writes are never automatically replayed.

Before student rollout, build the tested commit with the existing manually
dispatched Docker workflow and choose its immutable SHA image tag in Azure.
Preserve all environment variables, managed identity and SQL data. Record the
previous image tag for rollback. Verify the following on the deployed revision:

- An unauthorized email returns 403 from `/access`; anonymous `/current` returns 401.
- An authorized tester can save, refresh and resume the same saved attempt.
- After natural SQL auto-pause, returning to a tab or reloading recovers without
  repeated manual refreshes. Watch console diagnostics during the test.
- Unsaved choices survive temporary failures in the open tab. After confirmed
  session expiry, same-email reentry restores the in-tab draft. Closing the tab
  can still discard unsaved choices.
- Several authorized testers can use distinct sessions concurrently; one
  student's answers never appear under another student's email.
- Final submission persists and remains available after refresh.

Check the SQL free allowance and exhaustion behavior before changing availability
settings. The free tier has no SLA and an exhausted allowance can pause the
database until the next month. Moving to paid usage or disabling supported
auto-pause settings is a separate billing decision, not part of this code patch.

## Grading, versions, and release

Version `sorting-15-v3` uses 15 questions and four reasoning choices per question,
covering only insertion, selection, quick and merge sort.
Both question order and choice order are randomized and saved with the attempt.
Each question earns one visible point only when both parts are correct, otherwise
zero: 15 total. The feedback JSON stores internal half-point credit for each
correct part, but `internal_score` and `internal_points` are withheld from all
student APIs, even after explanations are released. The database score column
stays an integer. No SQL schema migration is required. Saved choice IDs are
validated against that exact question, and out-of-scope algorithm answers are rejected.
Until release, submitted APIs contain only the total score and completion metadata;
they never send individual correctness or the answer key. Before submission,
even the total score is absent.

After the PA, change `CHALLENGE_FEEDBACK_RELEASED` to `1` in a new revision to
release detailed feedback. Students use the same email to return. There is no
automatic date: staff control release. Setting it back to `0` hides future API
responses, but cannot retract answers students have already seen.

Version `sorting-15-v1` text attempts retain their original 15-point identification
score; `sorting-15-v2` attempts retain their original six-sort questions and
30-point scores. Switching to v3 creates a separate attempt per email. Existing
cookies for earlier versions receive 401 and must re-enter email, preventing old
questions from appearing in the active PA. Old drafts are not applied to a new
attempt. Earlier records are not deleted or regraded. The app does not
offer repeated attempts within a version. Do not change version names to reset
attempts casually, and do not delete real submissions for testing.

For this release, update the image and `CHALLENGE_TEST_VERSION=sorting-15-v3`
together. Leaving Azure's existing v2 environment variable in place keeps the
old challenge active despite deploying the new code. Keep classroom limits,
SQL identity/configuration and the disabled SQL auto-pause setting unchanged.

## Docker impact and alternatives

`mssql-python==1.16.0` installs the Microsoft SQL driver and authentication
dependencies. Ubuntu also installs `libltdl7`, `libkrb5-3`, and
`libgssapi-krb5-2`. The image is larger and contains additional packages to keep
patched, but uses the same non-root user, port and Java runner. SQL uses encrypted
connections with certificate validation and parameter binding. No new Azure
resources or charges are triggered by building the image. Actual database use
consumes the existing free allowance. The operator has subsequently selected
`BillOverUsage` and disabled idle auto-pause for student availability; compute
continues consuming allowance while idle and can incur overage charges. Confirm
the saved Azure settings and cost estimate before deployment.

Alternatives: keep SQLite for local-only work (no cloud durability); use pyodbc
with a separately installed Microsoft ODBC driver (more image setup); or use SQL
password authentication (requires changing Entra-only configuration and managing
secrets/rotation). Managed identity fits the current setup without passwords.

References:
- https://learn.microsoft.com/sql/connect/python/mssql-python/installation
- https://learn.microsoft.com/sql/connect/python/mssql-python/entra-authentication
- https://learn.microsoft.com/sql/connect/python/mssql-python/connection-pooling
