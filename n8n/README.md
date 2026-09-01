# n8n Quality Steering Cell

Operational layer of the Arkon platform: one workflow writes incidents and
alerts, a second one answers questions about them. Process owner:
`docs/Project_Charter.md` sections 7 and 8. Both run on a self-hosted n8n
instance, pinned to `n8nio/n8n:2.29.9`.

| Workflow | Direction | Endpoint | Deployed |
|---|---|---|---|
| `quality_steering_cell_v1.json` | write | `POST /webhook/arkon-event` | 2026-08-30 |
| `incident_status_api_v1.json` | read | `GET /webhook/arkon-incident-status` | 2026-08-30 |
| `escalation_record_v1.json` | write | `POST /webhook/arkon-escalation` | 2026-08-30 |
| `comparison_slice_v1.json` | read | `POST /webhook/arkon-slice` | 2026-08-30 |

**Module-agnostic as of 2026-08-30, and now measured.** The first Scania APS
event was posted to the intake webhook and created `ARK-INC-00017` with no
change to any workflow: intake validates a contract rather than a domain, and it
takes the assignee from the event's own `operational_context`. The status API
did need one fix, and it was not cosmetic. Its projection filled `predicted_rul`
from `evidence.prediction` whatever the module was, so a Scania failure
probability of 0.0373 was served as a remaining useful life of 0.0373 cycles and
the assistant read it out as one. The projection now returns the `evidence`
object as published and keeps the CMAPSS aliases only for record ids carrying
the `FD<n>-Unit-` marker. Three filters were added at the same time -
`record_id`, `source_module`, `business_domain` - because every module carries
those by contract, while `unit` only means something for CMAPSS.

## Workflow ids, and the one that is not readable

Every workflow file carries a fixed `id`, so `n8n import:workflow` updates the
existing workflow instead of creating another copy. Three of them read like
names. The fourth does not, and the reason is worth keeping:

| File | id |
|---|---|
| `incident_status_api_v1.json` | `arkonStatusApi1` |
| `escalation_record_v1.json` | `arkonEscalate01` |
| `comparison_slice_v1.json` | `arkonSlice001` |
| `quality_steering_cell_v1.json` | **`o0vXtlRWIs9yFrUJ`** |

**The steering cell keeps the id n8n generated for it, because that row is where
the incident counter lives.** `$getWorkflowStaticData("global")` on this workflow
holds `counter`, which produces the `ARK-INC-*` numbering, and `seen`, the 24-hour
duplicate-suppression window. Giving the file a readable id would mean importing
under a new id, which creates a **new** workflow with empty static data: the next
incident would be `ARK-INC-00001` against a store that already holds eighteen, and
the dedup memory would be gone. The n8n CLI has `import`, `export`, `update` and
`unpublish` but **no delete**, so the old row could not be cleaned up afterwards
either, and the rename would leave exactly the extra copy the fixed id exists to
prevent.

So the identity of this workflow is not a string in a file, it is the row that
holds the counter, and the file points at it. Verified 2026-08-31: imported twice
in a row, no third workflow appeared, `counter` stayed at 18, and a replayed event
came back `duplicate_suppressed` with the incident store unchanged at 8 lines.

**One archived duplicate remains and is inert.** `ZdLNgYq3bDTxQswJ`, the first
import from before the id was fixed: inactive, `isArchived = 1`, no static data,
and no row in `webhook_entity`, so it cannot fire. Permanently removing it needs
the UI (Workflows, Archived, delete) or the public API, and no API key exists on
this instance. It is left rather than deleted through the database, because
`workflow_entity` is referenced by executions, history and sharing rows and that
is not a trade worth making for a hidden row.

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

### Deployment steps (interactive)

Two of these need a human at a keyboard and cannot be scripted from here.

1. **Telegram bot** (manual): create a bot via BotFather, note the
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
answered. Read the execution in the n8n UI. Reading the SQLite database directly means
copying `database.sqlite-wal` too, since n8n runs it in WAL mode and the main
file alone can be a month stale.

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

## Escalation record (write path, guarded)

Third workflow, `escalation_record_v1.json`, built 2026-08-30, workflow id
`arkonEscalate01`. It records that a human approved the escalation of an existing
incident. It is the action the Langflow assistant's approval gate guards, and it
is the only write the assistant can perform.

```text
POST /webhook/arkon-escalation
  -> Validate the request               (400, one reason per bad parameter)
  -> Read /data/arkon/incidents.jsonl   (503 on an unreadable store)
  -> Incident exists?                   (404 if not; nothing is recorded)
  -> Append the escalation record       (200 with the new ARK-ESC id)
```

| Parameter | Required | Notes |
|---|---|---|
| `incident_id` | yes | `ARK-INC-00014`, or a plain number |
| `reason` | yes | 5 to 500 characters |
| `requested_by` | no | defaults to `arkon-quality-assistant` |
| `approved_by` | no | defaults to `human approval gate` |

Parameters are read from the JSON body **or the query string**, and that is not
a convenience. Langflow's API Request component, in tool mode, exposes only the
URL to the model: its `body` field is not tool-mode capable, and `curl_input` is
parsed at design time by `update_build_config` while `make_api_request` reads
`url_input`, `method`, `headers` and `body` from the component and never looks at
it. So an agent cannot compose a request body at all. Turning this endpoint into
a GET would also have solved it and was rejected, because a GET that writes an
audit record lies about what it does. The method stays POST, fixed on the canvas
where the model cannot change it.

The escalation record captures the incident's priority, status and summary at the
moment of escalation, so the audit entry still reads correctly after the incident
moves on. Escalation ids come from workflow static data, the same mechanism the
intake workflow uses, so the same publish-before-you-test rule applies. Ids
`ARK-ESC-00001` to `00004` were consumed by the contract test and by the
query-string check on 2026-08-30; the store was emptied afterwards, so the log
starts at `00005`.

### The simulate_failure affordance, and why it arrived late

`simulate_failure=1` (also `true`, `yes`) returns the 503 path without opening
the store and without consuming an escalation id. It is read after validation and
before anything else, so a malformed request still gets its 400: the parameter
buys a failure, not a way past the contract. Same parameter, same accepted values
and same response shape as the status API, on purpose - two failure switches with
two spellings would be a third thing to remember.

It was added on 2026-08-31, and the reason is worth keeping. The status API had
this affordance from the start, so its 503 branch was exercised in the routing
validation. **The escalation endpoint did not, so its 503 branch could only be
reached by moving the incident store aside on the NAS - and therefore nobody
reached it.** The agent prompt for that branch had been dictating the status
API's sentence, telling the operator that a *lookup* had failed on the one path
where a *write* silently does not happen. It survived because the path was
untestable, not because it was subtle. The untestable path is the one that rots.

```bash
python n8n/escalation_probe.py
```

Thirteen cases, and every one of them is a case that must not reach the store:
the three spellings of the simulated failure, validation beating it, the
malformed forms, id normalisation checked against an absent incident, and the
unknown-incident refusal. The suite asserts that no answer ever carries an
`escalation_id`, so it is safe to re-run. The success path is deliberately absent:
it appends a record and consumes an id, and a test that changes the thing it
measures is not worth keeping. That path belongs to a human at the approval gate,
which is also the only way it is reached in normal use.

### Re-importing this workflow can reset the escalation counter

`n8n import:workflow` rewrites the whole workflow row, and the escalation ids
live in that row's `staticData`. Import the tracked file as-is and the counter
goes back to zero, so the next escalation is `ARK-ESC-00001` against a store that
already contains one. Read the live value first and carry it into the document
being imported:

```bash
docker exec n8n n8n export:workflow --id=arkonEscalate01 --output=/tmp/exp.json
```

Take `staticData` from that export, put it on the patched workflow JSON, and
import the result. Do not put the counter in the tracked file: it is runtime
state, and a file that carries it would silently rewind the counter on every
future deploy. Verified on 2026-08-31: carried forward as
`{"global": {"nextEscalationId": 12}}`, and the next real escalation came out as
`ARK-ESC-00013`.

### Known boundaries of the escalation record

- **It notifies nobody.** `notification_channel` is always `none`. The Telegram
  card to the Quality Manager is the obvious next step and is deliberately not
  wired: a test run of an approval gate should not put messages in front of a
  real person.
- **It cannot verify the approval.** The endpoint records the `approved_by` value
  its caller sends. The gate is enforced on the Langflow canvas, not on the wire.
  In production the gate would hand the agent a signed, single-use token that this
  endpoint checks.
- **It does not change the incident.** The incident's own lifecycle transition
  belongs with the move to a queryable store, per charter 7.2 and 7.5.


## Comparison slice (evaluation artifact, not Arkon infrastructure)

`comparison_slice_v1.json`, workflow id `arkonSlice001`,
`POST /webhook/arkon-slice`. Twelve nodes: a webhook, a Text Classifier that
routes by meaning, a Qdrant retrieval over `arkon-knowledge`, one HTTP call to
the incident status API, and three response nodes.

**It exists for one reason and it is not an Arkon feature.** Choosing a visual
agent platform means defending the choice, and a defence read off vendor pages is
worth nothing. This is the same three capabilities as the Langflow assistant,
built once on n8n, so the comparison is first-hand. It answers from the same collection and calls the
same API, which is what makes it a comparison rather than a second demo. It has
no memory, no approval gate, no sub-flow and no model-composed tool call, and it
is deliberately not grown.

Three things it established that are worth keeping whatever happens to the
slice:

- **n8n has a one-node semantic router.** `Text Classifier` takes a language
  model as a sub-node, N named categories with descriptions, and creates one
  output branch per category, plus an optional `Other` branch and a multi-class
  switch. The published platform comparison this slice was built to test says n8n
  has no equivalent of Flowise's Condition Agent; on 2.29.9 that is not true.
- **A collection written by Langflow is readable from n8n.** The store was
  embedded with `google/gemini-embedding-001` through OpenRouter and is queried
  here with the stock Google Gemini embeddings node calling the same model
  directly. Retrieval returns the right passages. The two routes to one model
  land in the same vector space.
- **The content payload key is not the default.** Langflow's Qdrant component
  stores chunk text under `page_content`; n8n's node defaults to `content` and
  would retrieve empty passages **without failing**. It is set explicitly in the
  node's options.

### Rebuilding and deploying it

```bash
python n8n/build/build_comparison_slice.py
```

Then, on the NAS: `n8n import:workflow --input=<file>`,
`n8n publish:workflow --id=arkonSlice001`, and **restart the container** - the
running process holds its active workflows in memory, so a CLI import does not
take effect without one. It needs a `qdrantApi` credential named
`Arkon Qdrant (local)` pointing at `http://qdrant:6333`; it was created with
`n8n import:credentials`, which writes an encrypted credential with no UI step.

### What was measured

| Check | Result |
|---|---|
| Router, 4 questions x 3 repeats | 12 of 12 to the intended branch |
| Retrieval on a Langflow-built collection | 4 passages, correct answer on P1 and its 15-minute window |
| Underspecified question | `Other` branch, 3 of 3 |
| Live lookup | 200, 6 incidents, 3 P1 and 3 P2, matching the store |
