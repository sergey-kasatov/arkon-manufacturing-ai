# n8n Quality Steering Cell

First workflow of the Arkon platform: event intake to incident and alert.
Process owner: `docs/Project_Charter.md` sections 7 and 8. Runs on the
self-hosted n8n instance on the NAS (pinned image, see the vault runbook
`100 Personal/n8n_NAS_Runbook.md`).

## Flow

```
POST /webhook/arkon-event
  -> Validate against the event contract     (400 on contract violation)
  -> Dedup: record_id + priority, 24 h       (duplicate suppressed, no 2nd incident)
  -> Append incident record (JSONL store)
  -> P1/P2 -> Telegram incident card + respond
  -> P3/P4 -> respond (recorded, no push alert)
```

Incident numbering (`ARK-INC-00001`) and the dedup cache live in n8n
workflow static data. Static data persists for production executions of an
active workflow, not for editor test runs - activate the workflow before
demoing dedup.

## Files

| File | Purpose |
|---|---|
| `quality_steering_cell_v1.json` | Importable workflow draft |
| `replay_events.py` | Posts an events JSONL to the webhook for demos |

## Deployment steps (interactive, with Sergey)

1. **Telegram bot** (Sergey himself): create a bot via BotFather, note the
   token; create a group or chat for alerts and get its chat id. The token
   is entered only in the n8n credentials UI, never stored in this repo.
2. **NAS compose** (decide the exact share during deployment):
   - Bind-mount an incidents folder, e.g. `/volume1/<share>/arkon:/data/arkon`,
     so the laptop sees the store as a normal NAS path.
   - Add env vars: `ARKON_INCIDENTS_PATH=/data/arkon/incidents.jsonl`,
     `ARKON_TELEGRAM_CHAT_ID=<chat id>`.
   - `docker compose up -d` per the runbook.
3. **Import**: n8n UI -> Workflows -> Import from File ->
   `quality_steering_cell_v1.json`. Attach the Telegram credential named
   "Arkon Telegram Bot" to the Telegram node. Activate the workflow.
4. **Smoke test** from the laptop:

```bash
python n8n/replay_events.py http://AK2101:5678/webhook/arkon-event events/out/cmapss_events_FD001.jsonl --priority P1,P2 --limit 5 --delay 1
```

Expected: HTTP 200 per event, `ARK-INC-*` ids in responses, Telegram cards
for P1/P2, lines appended to the incidents JSONL. Re-running the same
events within 24 h must answer `duplicate_suppressed`.

## Known boundaries of v1

- The workflow JSON is hand-authored for the pinned n8n version. If import
  complains about a node version, rebuild that node from the Flow section
  above - the graph is small on purpose.
- Acknowledge/close buttons and the escalation timer are the next
  iteration: they need a Telegram Trigger node for callback handling and a
  Wait-based escalation branch (charter 7.4). v1 demonstrates intake,
  validation, dedup, incident record, and the priority-routed alert.
- The incident store is append-only JSONL in v1. Moving it to SQLite (the
  charter 7.5 target) happens when the Streamlit cockpit starts reading
  incidents.
