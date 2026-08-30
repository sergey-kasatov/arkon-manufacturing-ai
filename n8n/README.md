# n8n Quality Steering Cell

Operational layer of the Arkon platform: one workflow writes incidents and
alerts, a second one answers questions about them. Process owner:
`docs/Project_Charter.md` sections 7 and 8. Both run on the self-hosted n8n
instance on the NAS (pinned image, see the vault runbook
`100 Personal/n8n_NAS_Runbook.md`).

| Workflow | Direction | Endpoint | Deployed |
|---|---|---|---|
| `quality_steering_cell_v1.json` | write | `POST /webhook/arkon-event` | 2026-08-30 |
| `incident_status_api_v1.json` | read | `GET /webhook/arkon-incident-status` | 2026-08-30 |

## Event intake (write path)

**Status: deployed and verified 2026-08-30** on n8n 2.29.9. Sixteen incidents
created from replayed CMAPSS events, dedup confirmed across production runs,
Telegram cards delivered to the alert group.

### Flow

```
POST /webhook/arkon-event
  -> Validate against the event contract     (400 on contract violation)
  -> Dedup: record_id + priority, 24 h       (duplicate suppressed, no 2nd incident)
  -> Build incident line -> append to the JSONL store
  -> P1/P2 -> Telegram incident card + respond
  -> P3/P4 -> respond (recorded, no push alert)
```

Incident numbering (`ARK-INC-00001`) and the dedup cache live in n8n workflow
static data. Static data persists for production executions of a published
workflow, not for editor test runs, so the workflow must be published before
dedup can be demonstrated. Observed during deployment: static data is written
even when a later node in the same execution fails, so a failed run still
consumes its dedup key.

The dedup cache prunes entries older than the 24 h window on every run, so
workflow static data does not grow without bound.

### Files

| File | Purpose |
|---|---|
| `quality_steering_cell_v1.json` | The intake workflow, importable into n8n |
| `incident_status_api_v1.json` | The status API workflow, importable into n8n |
| `replay_events.py` | Posts an events JSONL to the webhook for demos |
| `incident_status_probe.py` | Contract test for the status API |

Events come from `events/out/cmapss_events_full_fleet.jsonl` (707 events: 49 P1,
87 P2, 90 P3, 481 P4). The earlier `cmapss_events_FD001.jsonl` is kept because it
is what the first deployment was verified against; it comes from the superseded
FD001-only model and should not be used for new demos.

### Deployment steps (interactive, with Sergey)

1. **Telegram bot** (Sergey himself): create a bot via BotFather, note the
   token; create a group for alerts, add the bot to it, and read the chat id
   from `https://api.telegram.org/bot<TOKEN>/getUpdates`. The token is entered
   only in the n8n credentials UI, never stored in this repo. Name the
   credential `Arkon Telegram Bot`.
2. **NAS compose** (`/volume1/docker/n8n/docker-compose.yml`), three additions:
   - Bind-mount the incident store: `/volume1/docker/arkon:/data/arkon`.
   - `N8N_RESTRICT_FILE_ACCESS_TO=~/.n8n-files;/data/arkon` - **required**, see
     the traps below.
   - Attach the container to the `msit-flowise_msit` network as well, so the
     agent front-end can reach n8n by name at `http://n8n:5678`.
   - Then `docker compose up -d` per the runbook. Back up `n8n_data` first.
3. **Create the store file**: `docker exec n8n touch /data/arkon/incidents.jsonl`.
   The file node cannot create it, see the traps below.
4. **Import**: n8n UI -> Create workflow -> the `...` menu -> Import from File
   -> `quality_steering_cell_v1.json`. Select the `Arkon Telegram Bot`
   credential on the Telegram node; import does not bind it automatically,
   because credentials are matched by internal id and not by name. Save, then
   **Publish** (n8n 2.x renamed the activation control).
5. **Smoke test** from the laptop, starting with a deliberate contract
   violation so the rejection path is exercised without consuming an incident
   id, then the real events:

```bash
python n8n/replay_events.py http://AK2101:5678/webhook/arkon-event events/out/cmapss_events_full_fleet.jsonl --priority P1,P2 --limit 5 --delay 1
```

Expected: HTTP 200 per event, `ARK-INC-*` ids in the response bodies, Telegram
cards for P1 and P2, one appended line per incident in the JSONL store.
Re-running the same events within 24 h must answer `duplicate_suppressed` and
must not create new ids.

An empty 200 response body means the workflow failed after the webhook was
answered. Read the execution in the n8n UI, or see the note on reading the n8n
database in the vault runbook.

### n8n 2.0 traps met during this deployment

All three are default changes between n8n 1.x and 2.x. Each one presents badly,
so they are recorded with their real cause.

1. **`ExecuteCommand` is disabled by default.** n8n 2.0 ships a
   `disabled-nodes` rule listing `n8n-nodes-base.executeCommand` and
   `n8n-nodes-base.localFileTrigger`. An imported workflow using either renders
   the node with a `?` icon and no explanation. The v1 draft appended the
   incident with a shell command and hit this. It was **not** re-enabled through
   `NODES_EXCLUDE`: the append was rebuilt from `Convert to File` (toText) plus
   `Read/Write Files from Disk` (write, append). That also removed a shell
   injection: the draft interpolated raw incident JSON inside a single-quoted
   shell string, so an apostrophe in an event summary broke the command.
2. **`N8N_RESTRICT_FILE_ACCESS_TO` now defaults to `~/.n8n-files`.** In 1.x the
   default was empty, meaning unrestricted. File nodes writing anywhere else
   fail with `The file "..." is not writable.`, which is misleading: filesystem
   permissions are irrelevant, the path is simply outside the allowlist. The
   entry in the compose file above is what makes the incident store work. The
   value is semicolon-separated, so the n8n default is kept as the first entry.
3. **The write node in append mode does not create the file.** In the node
   source the flag is `O_APPEND` alone for append, while the overwrite branch
   uses `O_WRONLY | O_CREAT | O_TRUNC`. A missing file therefore fails, again
   reported as "not writable". Create the file once at deployment (step 3).

### Known boundaries of v1

- Acknowledge and close buttons and the escalation timer are the next
  iteration: they need a Telegram Trigger node for callback handling and a
  Wait-based escalation branch (charter 7.4). v1 demonstrates intake,
  validation, dedup, incident record, and the priority-routed alert.
- The incident store is append-only JSONL in v1. Moving it to the n8n Data
  Table node (the charter 7.5 target, and now available natively with insert,
  get, update and upsert operations) happens when the Streamlit cockpit starts
  reading incidents, together with the incident lifecycle from charter 7.2.
- The alert group is a Telegram `group`, not a `supergroup`. If Telegram
  upgrades it, the chat id changes from `-548...` to a `-100...` form and
  alerts stop arriving silently. The chat id lives in the Telegram node.
- Operational context in the events (shift, assignee, escalation contact) is
  simulated and labelled `context_origin: simulated` per the charter.

## Incident status API (read path)

Second workflow, `incident_status_api_v1.json`, built 2026-08-30. It answers
questions about incidents that already exist, so an assistant can report live
status instead of guessing it. It is the missing half of the last open MVP
criterion of charter section 10: this endpoint makes incident state available,
and the assistant that consumes it becomes the operational interface.

**Status: deployed and verified 2026-08-30** on n8n 2.29.9, workflow id
`arkonStatusApi1`. Twenty-four contract cases pass, plus the two the probe
cannot cover by itself: an unreadable store answers 503, and the endpoint is
reachable from the agent container by name.

```text
GET /webhook/arkon-incident-status
  -> Parse and validate the query        (400, one reason per bad parameter)
  -> Simulated failure requested?        (503, test affordance)
  -> Read /data/arkon/incidents.jsonl    (503 on an unreadable store)
  -> Filter, rank, project               (200, status ok or no_match)
```

### Query contract

All parameters are optional. With none, the endpoint returns the five most
recent incidents plus the store summary.

| Parameter | Accepts | Notes |
|---|---|---|
| `incident_id` | `ARK-INC-00014`, `ark-inc-14`, `14` | normalised to the padded form |
| `unit` | `92`, `092`, `FD001-Unit-092`, `ATTRTEST` | matched against the unit token of `event.evidence.record_id` |
| `priority` | `P1`, `p1`, `P1,P2` | charter 7.1 levels |
| `status` | charter 7.2 lifecycle value | new, acknowledged, in_containment, resolved, closed, false_positive |
| `limit` | 1 to 50, default 5 | bounds the returned page, not `match_count` |
| `simulate_failure` | `true`, `1`, `yes` | test affordance, see below |

Four answers, deliberately distinct, so the caller can tell them apart:

| Situation | HTTP | `status` |
|---|---|---|
| query understood, at least one match | 200 | `ok` |
| query understood, nothing matches | 200 | `no_match` |
| query not understood | 400 | `rejected`, one `errors` entry per bad parameter |
| store unreadable, or failure simulated | 503 | `unavailable` |

The separation is the point. A `no_match` is a fact about the store and may be
reported as one; a 503 means the lookup itself failed and nothing about incident
state may be inferred from it. Collapsing the two into one empty result is what
makes an assistant invent a status.

Each incident is projected to a flat object rather than returned as stored: the
identifiers, summary and recommended action, the assignment and escalation
contact, the model evidence (`predicted_rul`, `priority_threshold`, `risk_score`,
`model_version`), and both origin labels. `operational_context_origin` rides on
every record so a simulated assignee can never be presented as real, per charter
section 5.

The response also carries a store summary computed over all incidents, not just
the returned page: counts per priority, open incidents, and `overdue_incidents`
measured against the charter 7.1 acknowledgement windows (P1 fifteen minutes, P2
one hour). That answers "is anything overdue" in a single call.

### The simulate_failure affordance

`simulate_failure=true` returns the 503 path without touching the store. It
exists because the assistant's failure behaviour has to be demonstrable on
demand, and unpublishing the workflow mid-demo is slow and indistinguishable
from a real outage. A production deployment removes the parameter or puts it
behind an operator role; that trade belongs in the readiness account rather than
being left as an oversight.

### Deploying it

The workflow needs no credentials, so it can go in from the command line:

```bash
docker cp incident_status_api_v1.json n8n:/tmp/w.json && docker exec n8n n8n import:workflow --input=/tmp/w.json && docker exec n8n n8n publish:workflow --id=arkonStatusApi1 && docker restart n8n
```

Two things make that work. The JSON carries a fixed workflow `id`, so a
re-import updates the workflow instead of adding another copy - the steering
cell was imported twice through the UI and left a duplicate behind. And the
restart is not optional: `publish:workflow` writes the database and says so
itself, "changes will not take effect if n8n is running", because the running
process holds its active workflows in memory. `--activeState=fromJson` on the
import is not an alternative; it refuses outside queue or multi-main mode.
Importing through the UI and pressing Publish achieves the same without a
restart, and is the route to use on a fresh instance.

### Testing it

```bash
python n8n/incident_status_probe.py http://AK2101:5678/webhook/arkon-incident-status
```

The probe asserts invariants rather than a snapshot of the store: `returned`
never exceeds `limit` or `match_count`, every returned incident satisfies the
filter it was asked for, no incident loses its simulated-context label, and the
rejection message for a bad status still lists the charter 7.2 lifecycle. It
stays valid as incidents accumulate.

The two cases the probe cannot assert on its own were checked by hand on
2026-08-30. Moving the store aside answered 503 `unavailable`, and the file came
back byte-identical (same SHA-256, six lines). From inside the Langflow
container, `http://n8n:5678/webhook/arkon-incident-status?priority=P1&limit=2`
answered 200 with two P1 incidents.

### Reaching it from the agent

The n8n container is attached to `msit-flowise_msit` and carries the network
alias `n8n.arkon.internal` there. The laptop and the LAN use `AK2101` instead.

```text
http://n8n.arkon.internal:5678/webhook/arkon-incident-status?priority=P1&limit=3
http://AK2101:5678/webhook/arkon-incident-status?priority=P1&limit=3
```

**The dotted alias is required, not decoration.** Langflow's API Request
component validates its URL with `validators.url()`, which rejects any hostname
containing no dot, so `http://n8n:5678/...` fails as "Invalid URL provided"
before a request is made. That reads like a network fault and is not one:
verified inside the container, `n8n` and `AK2101` are both rejected while an IP
literal or any dotted name passes. The alias lives in the n8n compose file so it
survives a recreate, and it keeps the call inside the container network. The
caller also has to be allowed to make it: Langflow blocks outbound requests into
private IP ranges by default and needs
`LANGFLOW_SSRF_ALLOWED_HOSTS=n8n.arkon.internal`.

### Known boundaries of the status API

- Read-only. Acknowledging, escalating or closing an incident is a write and
  belongs to the lifecycle work of charter 7.2, together with the move off JSONL.
- The whole store is parsed on every call. That is correct at demo scale and
  wrong at plant scale; the fix is the same move to a queryable store, not a
  smarter parser.
- No authentication. The endpoint sits on the LAN and the Tailscale network
  only. Anything beyond the demo needs at least a header credential, and that is
  a stated item in the readiness account.
