# Challenge Mode: 70-student rollout

This profile targets Challenge Mode. It is not a measured guarantee of Azure
capacity, nor a profile for 70 simultaneous Java compilations. Java execution
uses the separate MAX_CONCURRENT_EXECUTIONS setting; keep its existing value
until that workload is measured.

## Configuration

| Setting | Classroom starting value |
| --- | --- |
| SQL idle auto-pause | Disabled (`autoPauseDelay: -1`) |
| SQL free-limit behavior | `BillOverUsage`, explicitly selected by the operator |
| SQL vCores | Existing minimum 0.5, maximum 2; increase only after measuring |
| App minimum replicas | 2 (additional running/idle replica cost) |
| App maximum replicas | 6 |
| HTTP scaling target | Existing 3 |
| `CHALLENGE_ACCESS_REQUESTS_PER_MINUTE` | `240` |
| `CHALLENGE_WRITE_REQUESTS_PER_MINUTE` | `2400` |

Limits are per reported client IP, per process, over a sliding 60-second window.
An ingress proxy or campus network can give many students the same reported IP.
The old access default of 20 could reject a classroom login burst. The new
variables keep the old defaults for unconfigured installations and let Azure
use a higher shared-IP budget: 240 entries/minute and 2400 writes/minute. Limits
still reject excess traffic; these are not student quotas or distributed limits.
Increasing them also increases the permitted abuse load per IP. Existing origin,
body-size, roster, session and answer validation still apply.

`/access` checks the roster and creates/replaces a session; `/current` checks an
existing session. An unauthorized email returns 403 at `/access`. A missing or
ended session returns 401 at `/current`. Temporary persistence failures return
503. A 401 does not mean a student's email has been removed from the roster.

## Build and deploy

1. Push the tested commit to `phase-2-challenge-mode`.
2. In GitHub Actions, select **Build Docker Image**, choose **Run workflow**, and
   select `phase-2-challenge-mode`. A push to this branch alone does not build.
3. Wait for success. Use that run's full commit SHA as the GHCR image tag.
4. Record the current Azure image and scale settings for rollback:

```bash
az containerapp show \
  --name sorting-visualizer \
  --resource-group sorting-visualizer-rg \
  --query '{images:properties.template.containers[].image,scale:properties.template.scale}' \
  --output json
```

5. Replace `COMMIT_SHA` below with the successful workflow's full SHA. Run this
   once to update the image, classroom limits and replica range together:

```bash
az containerapp update \
  --name sorting-visualizer \
  --resource-group sorting-visualizer-rg \
  --image ghcr.io/pdhruv09/sorting-algorithm-visualization:COMMIT_SHA \
  --min-replicas 2 \
  --max-replicas 6 \
  --set-env-vars CHALLENGE_ACCESS_REQUESTS_PER_MINUTE=240 CHALLENGE_WRITE_REQUESTS_PER_MINUTE=2400 \
  --output none
```

Use `--set-env-vars`, not `--replace-env-vars`: the SQL, identity, origin,
feedback and test-version settings must remain configured. No roster changes,
schema migration, new database or attempt reset is required. The existing HTTP
scaling rule is retained. Container App configuration updates can create a new
revision; watch deployment health before testing. Record the new revision and
confirm its image and environment variables in the portal.

Rollback: update back to the recorded previous immutable image. Restore the
recorded replica settings if needed. SQL data is independent of the image; never
delete the database or attempts to roll back application code. The new rate-limit
variables are ignored by older code, which restores that code's lower limits.

## Verification before student use

Run `python3 -m challenge_sql` in the new container's console to validate SQL
identity and schema access. Then verify denied email, authorized entry, save,
refresh/resume, 401 reentry, and final submission with a designated tester.
Preexisting attempts retain their saved questions; new reasoning wording applies
only to newly created attempts.

Local regression:

```text
python -m unittest test_challenge test_challenge_sql.AzureStoreTests test_challenge_classroom
node --test test_challenge_ui.cjs
```

The classroom test runs 70 independent cookie sessions against one app process,
all using the same proxy IP. It interleaves the sessions but serializes database
requests to avoid SQLite writer-lock starvation. A separate middleware-only test
checks a 70-request simultaneous login burst, without database operations.
Every session completes 15 saves and
submission, verifies resume, and checks persisted attempt isolation. It uses a
temporary SQLite test database and synthetic emails. It never contacts Azure and
does not measure cloud SQL, managed identity, ingress or replica performance.

Before the full class, run the same representative flow in a staging deployment
with 70 distinct synthetic, allowlisted test emails and isolated test data.
Include a synchronized login burst and save burst. Do not reuse real students'
emails, which would replace their sessions and affect their actual attempts.
Observe HTTP 429/5xx, request latency, SQL CPU/workers/sessions and app CPU/memory
and restarts. Suggested acceptance targets are zero unexpected 429/5xx, correct
saved progress for all 70 sessions, and warm save latency below 3 seconds at the
95th percentile. These are rollout targets, not measured results.

If the targets fail, inspect diagnostics to distinguish CPU pressure, login
latency, locks and app capacity before changing vCores. Configure an Azure cost
budget/alert for always-on SQL and additional replicas. Do not re-enable idle
auto-pause as a performance fix.
