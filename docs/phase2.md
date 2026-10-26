# Phase 2: local Challenge Mode

## Student flow

Open the visualizer and select **Challenge Mode**, or visit `/challenge`.
Enter an authorized UCSD email to start or resume the challenge. No password,
email verification, SSO, or approval workflow is used.

The challenge contains 15 identification-and-reasoning questions: three each
for insertion, selection, and merge sort; two each for quick, counting, and
bucket sort. Heap and bubble sort are excluded. The order is shuffled once per
attempt and persisted. Inputs and algorithm assignments are also persisted,
so a resume does not create a different challenge.

Only main-array frames are sent to the browser. No algorithm-specific labels,
source code, bucket containers, or count tables are shown.
The algorithm and reasoning choices are public; the correct choice
is kept on the server. Hidden auxiliary state can make traces ambiguous, so
this question bank should receive instructor review before use for grading.
These are controlled Python-generated traces, not executions of student Java.

Each **Save & next** saves both fields before advancing. **Previous** allows
review of earlier answers; it warns before discarding unsaved edits. Reloading
resumes at the furthest unlocked question. Typing alone is not autosaved.
The final **Submit challenge** first saves question 15, then atomically marks
the whole attempt submitted and stores the score and feedback. A failed final
submission can be retried without duplicating the attempt. Students see their
total score after submission or signing in again. Individual correctness and
explanations are withheld by the API until `CHALLENGE_FEEDBACK_RELEASED=1`.

Version 2 awards one point for identification and one for a selected reasoning
choice per question (30 total). Version 1 written responses remain preserved
with their original identification-only score. Choice order is saved per attempt.
Conceptual questions are intentionally absent from this version.

## Current attempt policy

One attempt per email per test version. Entering the email again resumes that
attempt or shows its score; it does not grant a retry. A new login
invalidates the older session for that attempt. The schema has an attempt number
for a later instructor-approved repeat policy, but no repeat controls exist yet.
There is no staff UI or role-based behavior. The students table reserves a role
column, defaulting to `student`.

## Local setup (Ubuntu / WSL)

The existing Phase 1 runner imports Linux's `resource` module. Run the integrated
server in Ubuntu/WSL, not native Windows Python; do not remove its resource limits.
From the repository in Ubuntu, using the existing environment:

```bash
.venv/bin/python challenge_roster.py student@ucsd.edu
CHALLENGE_MODE_ENABLED=1 .venv/bin/python -m uvicorn server:app --host 127.0.0.1 --port 8010
```

The first command is an example: replace the address with the approved student.
The local allowlist is a database table, not a CSV file. No real student emails
are included in tracked source files. To revoke access:

```bash
.venv/bin/python challenge_roster.py student@ucsd.edu --disable
```

Revocation applies to existing sessions as well as new logins. Manage the roster
with this local maintenance command; there is no public roster-editing endpoint.

| Setting | Default | Purpose |
| --- | --- | --- |
| `CHALLENGE_MODE_ENABLED` | `0` | Set to `1` to register the challenge APIs. |
| `CHALLENGE_DB_PATH` | `secrets/challenge.sqlite3` beside the source | Private SQLite database; must be outside `static`. |
| `APP_ENV` | `development` | `production` makes session cookies HTTPS-only. |
| `CHALLENGE_LOCAL_HTTP` | `0` | Local Compose sets `1` to allow HTTP cookies only for localhost/loopback hostnames. |

Set environment variables in the shell when launching. This app does not load
`.env` automatically. With the feature disabled, the entry page explains that
Challenge Mode is unavailable; Phase 1 continues to work.

`secrets/` is already excluded from both Git and Docker build context. It holds
the allowlist, saved answers, and session hashes. Do not commit, publish, or bake
the database into an image. Back up the database using SQLite's backup API or
while the server is stopped. Restrict filesystem access to the application owner.

## Security controls and boundaries

- SQL values use parameter bindings. Email is normalized and checked against a
  constrained UCSD-address format; unknown emails are denied.
- Identification accepts only the six declared algorithm identifiers. Reasoning
  must contain 1–4000 characters of text; unexpected fields are rejected.
- Reasoning is data, never executed. The UI renders it with `textContent`, not
  HTML. Quotes, SQL fragments, and markup can be stored without becoming code.
- The browser cannot choose an email, attempt ID, score, or answer key during
  save/submit. The server resolves identity from a random session cookie.
- Cookies are HttpOnly, SameSite=Strict, restricted to `/api/challenge`, expire
  after eight hours, and are Secure in production. Only token hashes are stored.
- Mutations require a custom request header, reject cross-site browser requests
  and foreign origins, and accept JSON. No permissive CORS is configured.
- Actual request bodies are capped at 20 KB, including chunked requests. Access
  requests are limited to 20 per minute per direct client IP; answer mutations
  to 120. These limits are in-process and need deployment review behind proxies
  or with multiple replicas. Forwarded IP headers are not blindly trusted here.
- Protected responses are not cached, and the challenge route has a restrictive
  script policy. Database failures return a retry message without internal details.
- Transactions prevent partial final submission and duplicate attempts. Revision
  checks reject conflicting edits from stale tabs; an identical save retry is safe.

Entering an allowed email still does not prove ownership. This is the explicitly
chosen pilot access model, not verified authentication. SQLite is not encrypted
by this application. The database/storage layer and Java execution sandbox need
their own production deployment review.

## Tests

Install the shared application and test dependencies in a development environment.
HTTPX is included in this file for the API tests; the application does not use it
to call an external service:

```bash
python -m pip install -r requirements.txt
python -m unittest test_challenge -v
node --test test_challenge_ui.cjs
```

Run the existing Phase 1 regression test in Ubuntu/WSL:

```bash
.venv/bin/python smoke_test.py
```

Tests use temporary databases, not the actual allowlist. They cover every trace,
all 15 submissions, correct/incorrect grading, save/resume, session revocation and
expiry, one-attempt concurrency, SQL injection payloads, validation, CSRF, body
limits, rate limits, secure cookies, database errors, and repeat submissions.

For browser testing, use a separate database via `CHALLENGE_DB_PATH`. Verify
denial, start confirmation, animation controls, progress, reload/resume, final
submission confirmation, and literal rendering of markup in reasoning. Do not consume a student's
real attempt as a test. Responsive styles are included; mobile device testing is
a separate check, not implied by API tests.

## Local Docker testing

The Dockerfile includes the four challenge backend modules without copying any
private database or roster. Compose enables Challenge Mode, keeps `APP_ENV=production`,
and mounts the `challenge-data` named volume at `/var/lib/sortviz`. The database
is `/var/lib/sortviz/challenge.sqlite3`. This is separate from the WSL/host database.
The volume is initialized with directory permissions `0700` and ownership
`999:999`, matching the fixed non-root application user. The application filesystem
remains read-only; the existing dropped capabilities, no-new-privileges, and
resource limits remain in place.

From the repository, start the app and then add an approved email to the container's
database (replace the sample address):

```bash
docker compose up --build -d
docker compose exec sorting-visualizer python3 challenge_roster.py student@ucsd.edu
```

Open `http://localhost:8000/challenge`. Unknown emails remain denied. The allowlist
starts empty in a new volume; rebuilding the image does not seed or reset it.
The same roster command with `--disable` revokes access. It runs as the non-root
application user; no root initialization container is needed.

To test another host port in Windows PowerShell:

```powershell
$env:HOST_PORT = "8010"
docker compose up --build -d
```

Then open `http://localhost:8010/challenge`. In Windows Command Prompt, use
`set HOST_PORT=8010` before the Compose command. Alternatively, set `HOST_PORT`
in a local `.env` file for Compose. The internal server port stays 8000; changing
`EXPOSE` alone does not change the published host port. Ports bind only to
`127.0.0.1`, so this configuration does not publish the app to other machines.

Compose sets `CHALLENGE_LOCAL_HTTP=1` for local HTTP testing. In production mode,
only requests with an HTTP URL whose hostname is `localhost`, `127.0.0.1`, or
`::1` receive a cookie without the Secure flag. HTTPS and other hostnames still
receive Secure cookies. HttpOnly, SameSite, expiry, and request-origin checks stay
enabled. Keep the local-HTTP setting unset for Azure, and use HTTPS there.

`docker compose stop` stops the app. `docker compose down` removes containers but
keeps the named volume; rebuilding/recreating containers preserves saved data.
**Do not use `docker compose down -v` unless you intend to delete the database.**
A volume is persistence, not a backup. The container's Java runner and backend
still share an OS user; this change does not create isolation between them.

`test_challenge_docker.py` provides a two-stage HTTP/persistence regression check.
Run it inside the container with `prepare`, recreate the container without removing
the volume, then run it with `finish --email <generated-email> --attempt-id <saved-id>`
using the identifiers printed by the first stage. It generates its own test account,
saves a response, verifies resume, completes all 15 questions, and disables that
account. The disabled test account and attempt remain in the local test database;
it never uses a real student's attempt. The script is not copied into the image;
it can be passed to `docker compose exec -T sorting-visualizer python3 -` through
standard input, as with the other development tests.

If the page loads but initially says `Not found` and email submission says
`Method Not Allowed`, an older frontend is calling a server whose challenge
routes are disabled. This is a route/packaging issue, not a SQLite query error.
The updated disabled-mode API returns an explicit `challenge_unavailable`
response; the updated page explains unavailability and disables the email form.
It also handles older servers that return 404/405. Rebuild and recreate the local
container with the updated Compose settings to include and enable Phase 2.

## Azure boundary (not deployed)

These Docker changes are for local testing. No image has been pushed, no GitHub
workflow has changed, and no Azure resources have been modified. The Docker image
contains the challenge code, but enabling it on Azure still requires explicit
configuration and appropriate persistent database storage. Do not deploy the local
Compose settings as an Azure security or persistence plan.

Storage access is isolated in `ChallengeStore`; the Azure SQL adapter is selected
with `CHALLENGE_DB_BACKEND=azure_sql`. Follow [the deployment guide](azure-deployment.md)
for manual schema, grants, network checks and configuration. If a local-data migration
is later required, export students and attempts with
their identifiers, question snapshots, answers, versions, and timestamps; validate
counts and scores during migration. Sessions should be reissued after migration.
The SQLite schema is versioned with `PRAGMA user_version = 1`; it is not itself an
Azure SQL migration. No cloud database, credentials, or infrastructure is created
by these files. Agree on the Azure target, database, costs, migration, backup, and
rollback plan before changing deployment configuration.
