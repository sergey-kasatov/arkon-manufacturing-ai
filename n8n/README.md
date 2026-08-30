# n8n Quality Steering Cell

First workflow of the Arkon platform: event intake to incident and alert.
Process owner: `docs/Project_Charter.md` sections 7 and 8. Runs on the
self-hosted n8n instance on the NAS (pinned image, see the vault runbook
`100 Personal/n8n_NAS_Runbook.md`).

**Status: deployed and verified 2026-08-30** on n8n 2.29.9. Sixteen incidents
created from replayed CMAPSS events, dedup confirmed across production runs,
Telegram cards delivered to the alert group.

## Flow

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

## Files

| File | Purpose |
|---|---|
| `quality_steering_cell_v1.json` | The workflow, importable into n8n |
| `replay_events.py` | Posts an events JSONL to the webhook for demos |

Events come from `events/out/cmapss_events_full_fleet.jsonl` (707 events: 49 P1,
87 P2, 90 P3, 481 P4). The earlier `cmapss_events_FD001.jsonl` is kept because it
is what the first deployment was verified against; it comes from the superseded
FD001-only model and should not be used for new demos.

## Deployment steps (interactive, with Sergey)

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

## n8n 2.0 traps met during this deployment

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

## Known boundaries of v1

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
