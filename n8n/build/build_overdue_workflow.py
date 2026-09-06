"""Build the Arkon Overdue Escalation n8n workflow JSON.

The escalation half of charter 7.4: a P1 or P2 incident that is still
unacknowledged past its charter 7.1 window notifies the Quality Manager. It is a
scheduled reader, not an endpoint, so it answers nobody and writes one file.

Three decisions are worth reading before the code.

The overdue decision is not made here. `GET /webhook/arkon-incident-status`
already computes it from the windows in `lifecycle.py` and returns `overdue` on
every incident, so this workflow reads that field. A fourth copy of the rule is
exactly what `lifecycle.py` exists to prevent, and a timer that disagreed with
the API about what is overdue would be the worse kind of wrong: both numbers
would look reasonable.

Dedup comes from the notification log rather than from workflow static data.
Static data is rewritten by `import:workflow`, and both counters this project
already keeps there have had to be carried across a deploy by hand. A log that is
read back cannot be rewound by a deploy, and it is also the evidence.

The card is sent before the record is written, and the record carries Telegram's
own `message_id`. The other order would claim a notification that may not have
arrived, which is the separation this project has already had to make once
between a workflow reporting that it sent a card and the card being delivered.
"""

import json
import pathlib

OUT = pathlib.Path(__file__).resolve().parent.parent / "overdue_escalation_v1.json"

NOTIFICATION_STORE = "/data/arkon/incident_notifications.jsonl"

# Read over the loopback address, not over the tailnet name in WEBHOOK_URL: that
# name resolves through MagicDNS only and the container is not on the tailnet.
# `localhost` is not the same thing here either - it resolves to ::1 in this
# image and n8n binds IPv4, so the call is refused. Measured 2026-09-05.
STATUS_API = "http://127.0.0.1:5678/webhook/arkon-incident-status"

# One run may send this many cards. The alert group is a real chat and the store
# can hold a backlog of never-acknowledged incidents, so a run works through it
# rather than emptying it in one burst. Same discipline as replaying a slice of
# an event batch instead of the batch.
MAX_PER_RUN = 3

# The alert group, the same chat the intake workflow posts to.
CHAT_ID = "-5481573875"

SELECT = r"""// Arkon Overdue Escalation - selection.
// What is overdue is NOT decided here. The status API computes it from the
// charter 7.1 windows held in lifecycle.py and returns `overdue` on every
// incident, so this reads that flag. This node decides only two further things:
// whether the incident has been notified before, and how many cards one run may
// send.
const MAX_PER_RUN = __MAX_PER_RUN__;

const api = $('Read Alerting Incidents').first().json;
const logText = $input.first().json.notifications_text ?? "";

// The notification log is the dedup state, deliberately rather than workflow
// static data: an import rewrites staticData, and the two counters this project
// keeps there have both had to be carried across a deploy by hand. Reading the
// log back costs one file read and cannot be rewound by a deploy.
const notified = new Set();
let nextId = 1;
let unreadableLines = 0;
for (const line of logText.split("\n")) {
  const trimmed = line.trim();
  if (!trimmed) continue;
  let record;
  try {
    record = JSON.parse(trimmed);
  } catch (error) {
    // A damaged line loses one dedup entry and possibly the highest id, so it is
    // counted onto every record this run writes rather than passed over.
    unreadableLines += 1;
    continue;
  }
  if (record.incident_id) notified.add(record.incident_id);
  const digits = String(record.notification_id ?? "").replace(/[^0-9]/g, "");
  if (digits) nextId = Math.max(nextId, parseInt(digits, 10) + 1);
}

const incidents = Array.isArray(api.incidents) ? api.incidents : [];
const overdue = incidents.filter((i) => i.overdue === true && !notified.has(i.incident_id));

// Oldest first. The subject of the notification is the wait, so when a run is
// capped the longest wait is the one that goes out.
overdue.sort((a, b) => (b.age_minutes ?? 0) - (a.age_minutes ?? 0));
const selected = overdue.slice(0, MAX_PER_RUN);

// The API pages at 50 and ranks by recency, so a store with more than 50 open
// alerting incidents would hide the oldest ones - the very ones this workflow
// exists to surface. It cannot be fixed from this side, so it is recorded on
// every record written by a truncated run instead of being left silent.
const selectionTruncated = (api.match_count ?? 0) > (api.returned ?? 0);

// Telegram parses the message body, so every value out of an incident is escaped
// before it meets the markup. HTML rather than Markdown for the reason the intake
// workflow records: an underscore in a record id made Telegram reject a whole
// message after the incident had already been written.
const esc = (value) => String(value === null || value === undefined ? "" : value)
  .replace(/&/g, "&amp;")
  .replace(/</g, "&lt;")
  .replace(/>/g, "&gt;");

const runAt = new Date().toISOString();

return selected.map((incident, index) => {
  const window = incident.acknowledge_due_minutes ?? null;
  const age = incident.age_minutes ?? null;
  const overdueBy = window === null || age === null ? null : Math.round((age - window) * 10) / 10;
  const notificationId = "ARK-NTF-" + String(nextId + index).padStart(5, "0");

  const alertText = [
    "\u{23F0} <b>Arkon: unacknowledged incident</b>",
    "<b>" + esc(incident.priority) + "</b> incident <b>" + esc(incident.incident_id) + "</b>"
      + " has not been acknowledged.",
    "",
    esc(incident.summary),
    "",
    "Raised: " + esc(incident.created_at),
    "Acknowledge window: " + esc(window) + " min, overdue by " + esc(overdueBy) + " min",
    "Assigned: " + esc(incident.assigned_to) + " (" + esc(incident.assigned_role) + ")",
    "Escalation contact: " + esc(incident.escalation_contact),
    "Notification: <code>" + esc(notificationId) + "</code>",
  ].join("\n");

  return {
    json: {
      alert_text: alertText,
      notification: {
        notification_id: notificationId,
        sent_at: null,
        incident_id: incident.incident_id,
        incident_priority: incident.priority,
        incident_created_at: incident.created_at,
        incident_status: incident.status,
        minutes_unacknowledged: age,
        acknowledge_window_minutes: window,
        minutes_overdue: overdueBy,
        notified_role: "Quality Manager",
        escalation_contact: incident.escalation_contact ?? null,
        trigger: "unacknowledged_window_elapsed",
        channel: "telegram",
        telegram_chat_id: "__CHAT_ID__",
        telegram_message_id: null,
        run_at: runAt,
        candidates_overdue: overdue.length,
        selection_capped: overdue.length > MAX_PER_RUN,
        selection_truncated: selectionTruncated,
        log_unreadable_lines: unreadableLines,
        // The person is simulated under charter section 5. The timestamps, the
        // window and the delivery are not.
        context_origin: "simulated",
      },
    },
  };
});
"""

RECORD = r"""// Arkon Overdue Escalation - the record, written after the card was sent.
// The Telegram node returns the Bot API envelope as the item, `{ ok, result }`,
// with `message_id`, `chat` and `date` inside `result`. Measured on execution
// 7800 of 2026-09-06, the first live run: its three records carried
// `telegram_message_id: null` because this code read the fields off the
// envelope. Recording the id is what makes this log evidence that a card exists
// rather than a note that one was composed, so the envelope is unwrapped here; a
// reply that already is the result object still reads.
const sent = $input.all();
const selected = $('Select Overdue Incidents').all();

const lines = [];
for (let i = 0; i < selected.length; i += 1) {
  const record = { ...selected[i].json.notification };
  const raw = sent[i]?.json ?? {};
  const reply = raw.result && typeof raw.result === "object" ? raw.result : raw;
  record.telegram_message_id = reply.message_id ?? null;
  record.telegram_chat_id = String(reply.chat?.id ?? record.telegram_chat_id);
  record.sent_at = reply.date ? new Date(reply.date * 1000).toISOString() : new Date().toISOString();
  lines.push(JSON.stringify(record));
}

return [
  {
    json: {
      notifications_jsonl: lines.length ? lines.join("\n") + "\n" : "",
      notified: lines.length,
    },
  },
];
"""


workflow = {
    "id": "arkonOverdue01",
    "name": "Arkon Overdue Escalation v1",
    "nodes": [
        {
            "id": "c1000000-0000-4000-8000-000000000001",
            "name": "Overdue Timer",
            "type": "n8n-nodes-base.scheduleTrigger",
            "typeVersion": 1.2,
            "position": [-880, 0],
            # Fifteen minutes is the P1 window of charter 7.1, so a P1 is never
            # more than one interval late in being escalated.
            "parameters": {
                "rule": {"interval": [{"field": "minutes", "minutesInterval": 15}]}
            },
        },
        {
            "id": "c1000000-0000-4000-8000-000000000002",
            "name": "Read Alerting Incidents",
            "type": "n8n-nodes-base.httpRequest",
            "typeVersion": 4.2,
            "position": [-656, 0],
            # A 503 from the status API must stop the run, never read as "nothing
            # is overdue". That is the no_match / unavailable separation the API
            # draws, on the consuming side.
            "onError": "continueErrorOutput",
            "parameters": {
                "url": STATUS_API,
                "sendQuery": True,
                "queryParameters": {
                    "parameters": [
                        {"name": "status", "value": "new"},
                        {"name": "priority", "value": "P1,P2"},
                        {"name": "limit", "value": "50"},
                    ]
                },
                "options": {"timeout": 20000},
            },
        },
        {
            "id": "c1000000-0000-4000-8000-000000000003",
            "name": "Halt: Status API Unavailable",
            "type": "n8n-nodes-base.noOp",
            "typeVersion": 1,
            "position": [-432, 176],
            "parameters": {},
        },
        {
            "id": "c1000000-0000-4000-8000-000000000004",
            "name": "Read Notification Log",
            "type": "n8n-nodes-base.readWriteFile",
            "typeVersion": 1.1,
            "position": [-432, -32],
            # An unreadable log read as empty would re-notify every overdue
            # incident in the store, into a real chat. Doing nothing is the only
            # safe answer, so the error branch ends the run.
            "onError": "continueErrorOutput",
            "parameters": {"operation": "read", "fileSelector": NOTIFICATION_STORE, "options": {}},
        },
        {
            "id": "c1000000-0000-4000-8000-000000000005",
            "name": "Halt: Notification Log Unreadable",
            "type": "n8n-nodes-base.noOp",
            "typeVersion": 1,
            "position": [-208, 176],
            "parameters": {},
        },
        {
            "id": "c1000000-0000-4000-8000-000000000006",
            "name": "Extract Notification Log",
            "type": "n8n-nodes-base.extractFromFile",
            "typeVersion": 1.1,
            "position": [-208, -32],
            "parameters": {
                "operation": "text",
                "binaryPropertyName": "data",
                "destinationKey": "notifications_text",
                "options": {},
            },
        },
        {
            "id": "c1000000-0000-4000-8000-000000000007",
            "name": "Select Overdue Incidents",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [16, -32],
            # No items out means nothing is overdue and nothing downstream runs,
            # which is the whole of the "nothing to do" path. The execution record
            # is the trace.
            "parameters": {
                "jsCode": SELECT.replace("__MAX_PER_RUN__", str(MAX_PER_RUN)).replace(
                    "__CHAT_ID__", CHAT_ID
                )
            },
        },
        {
            "id": "c1000000-0000-4000-8000-000000000008",
            "name": "Notify Quality Manager",
            "type": "n8n-nodes-base.telegram",
            "typeVersion": 1.2,
            "position": [240, -32],
            "parameters": {
                "chatId": CHAT_ID,
                "text": "={{ $json.alert_text }}",
                "additionalFields": {"appendAttribution": False, "parse_mode": "HTML"},
            },
            "credentials": {"telegramApi": {"name": "Arkon Telegram Bot"}},
        },
        {
            "id": "c1000000-0000-4000-8000-000000000009",
            "name": "Build Notification Records",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [464, -32],
            "parameters": {"jsCode": RECORD},
        },
        {
            "id": "c1000000-0000-4000-8000-00000000000a",
            "name": "Build Notification Lines",
            "type": "n8n-nodes-base.convertToFile",
            "typeVersion": 1.1,
            "position": [688, -32],
            "parameters": {
                "operation": "toText",
                "sourceProperty": "notifications_jsonl",
                "options": {},
            },
        },
        {
            "id": "c1000000-0000-4000-8000-00000000000b",
            "name": "Append Notification Log",
            "type": "n8n-nodes-base.readWriteFile",
            "typeVersion": 1.1,
            "position": [912, -32],
            "parameters": {
                "operation": "write",
                "fileName": NOTIFICATION_STORE,
                "options": {"append": True},
            },
        },
    ],
    "connections": {
        "Overdue Timer": {"main": [[{"node": "Read Alerting Incidents", "type": "main", "index": 0}]]},
        "Read Alerting Incidents": {
            "main": [
                [{"node": "Read Notification Log", "type": "main", "index": 0}],
                [{"node": "Halt: Status API Unavailable", "type": "main", "index": 0}],
            ]
        },
        "Read Notification Log": {
            "main": [
                [{"node": "Extract Notification Log", "type": "main", "index": 0}],
                [{"node": "Halt: Notification Log Unreadable", "type": "main", "index": 0}],
            ]
        },
        "Extract Notification Log": {
            "main": [[{"node": "Select Overdue Incidents", "type": "main", "index": 0}]]
        },
        "Select Overdue Incidents": {
            "main": [[{"node": "Notify Quality Manager", "type": "main", "index": 0}]]
        },
        "Notify Quality Manager": {
            "main": [[{"node": "Build Notification Records", "type": "main", "index": 0}]]
        },
        "Build Notification Records": {
            "main": [[{"node": "Build Notification Lines", "type": "main", "index": 0}]]
        },
        "Build Notification Lines": {
            "main": [[{"node": "Append Notification Log", "type": "main", "index": 0}]]
        },
    },
    "settings": {"executionOrder": "v1", "binaryMode": "separate", "availableInMCP": False},
    "pinData": {},
}

OUT.write_text(json.dumps(workflow, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
print("written", OUT, OUT.stat().st_size, "bytes")
