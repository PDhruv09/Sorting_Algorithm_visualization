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
| `CHALLENGE_TEST_VERSION` | `sorting-15-v2` |
| `CHALLENGE_FEEDBACK_RELEASED` | `0` |
| `CHALLENGE_LOCAL_HTTP` | `0` |

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
still need to be retried by the user. Lock timeout is bounded separately:
lock waits 10s; managed-identity token acquisition has the driver's own timing.

## Grading, versions, and release

Version `sorting-15-v2` uses 15 questions and six reasoning choices per question.
Both question order and choice order are randomized and saved with the attempt.
Each correct identification earns one point and each correct reason earns one
point: 30 total. Saved choice IDs are validated against that exact question.
Until release, submitted APIs contain only the total score and completion metadata;
they never send individual correctness or the answer key. Before submission,
even the total score is absent.

After the PA, change `CHALLENGE_FEEDBACK_RELEASED` to `1` in a new revision to
release detailed feedback. Students use the same email to return. There is no
automatic date: staff control release. Setting it back to `0` hides future API
responses, but cannot retract answers students have already seen.

Version `sorting-15-v1` text attempts are preserved and retain their original
15-point identification score. They are not regraded as multiple choice. Moving
to v2 permits a separate attempt per email for this new version. The app does not
offer repeated attempts within a version. Do not change version names to reset
attempts casually, and do not delete real submissions for testing.

## Docker impact and alternatives

`mssql-python==1.16.0` installs the Microsoft SQL driver and authentication
dependencies. Ubuntu also installs `libltdl7`, `libkrb5-3`, and
`libgssapi-krb5-2`. The image is larger and contains additional packages to keep
patched, but uses the same non-root user, port and Java runner. SQL uses encrypted
connections with certificate validation and parameter binding. No new Azure
resources or charges are triggered by building the image. Actual database use
consumes the existing free allowance; keep overage billing disabled as selected.

Alternatives: keep SQLite for local-only work (no cloud durability); use pyodbc
with a separately installed Microsoft ODBC driver (more image setup); or use SQL
password authentication (requires changing Entra-only configuration and managing
secrets/rotation). Managed identity fits the current setup without passwords.

References:
- https://learn.microsoft.com/sql/connect/python/mssql-python/installation
- https://learn.microsoft.com/sql/connect/python/mssql-python/entra-authentication
- https://learn.microsoft.com/sql/connect/python/mssql-python/connection-pooling
