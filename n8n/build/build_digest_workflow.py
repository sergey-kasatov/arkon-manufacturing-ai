"""Build the Arkon Daily Digest n8n workflow JSON.

The digest half of charter 7.4: once a day, at 07:05 plant time, one card to the
alert group with what is open, what is overdue, how fast the cell has been
responding, and the P3 queue that step 4 of `docs/Incident_Process.md` promises
to the daily review. Like the overdue timer it is a scheduled reader: it answers
nobody and writes one file.

Four decisions are worth reading before the code.

Three reads of the status API, one per open lifecycle state, rather than one read
of the whole store. `status` takes a single value, and an unfiltered read is
ranked by recency and capped at 500, so on a store the live plant grows by about
144 incidents a day it would start dropping the oldest incidents within days: the
very P3s that have waited longest, which the queue exists to surface. A state is
bounded by how fast the crew works it, every incident is in exactly one, and
`tableau/build_extracts.py` already sweeps the store the same way. A page that
truncates is recorded on the digest rather than fixed here.

Nothing is decided here that the API already decides. `overdue` is the API's flag
from the charter 7.1 windows in `lifecycle.py`, the response-time medians are the
API's own summary, and this workflow counts, sorts and formats.

The record goes into `/data/arkon/incident_notifications.jsonl`, the log the
overdue timer writes, under `trigger: daily_digest` and with no incident id.
`docs/Incident_Process.md` promises one log of every notification sent, and a
second file would be a second place to look for who was told what, when. The two
writers cannot confuse each other: the timer's dedup is keyed on `incident_id`,
which a digest record does not carry, and both take the next `ARK-NTF` number
from the highest in the log, so the sequence is shared. They never write in the
same minute: the timer fires on the quarter hour, the digest at five past.

The card is sent before the record is written, and the record carries Telegram's
own `message_id` and `date`, for the reason the timer's first run made plain: a
record written from the request rather than the reply claims a notification that
may not have arrived.

07:05 Europe/Berlin is pinned in the workflow settings. The container runs in UTC
and n8n's own default timezone, with GENERIC_TIMEZONE unset, is America/New_York
(read out of `@n8n/config` in the running image), so an unpinned "07:05" would
fire at 13:05 plant time.
"""

import json
import pathlib

OUT = pathlib.Path(__file__).resolve().parent.parent / "daily_digest_v1.json"

NOTIFICATION_STORE = "/data/arkon/incident_notifications.jsonl"

# Loopback, not the tailnet name in WEBHOOK_URL and not `localhost`, for the
# reasons measured in build_overdue_workflow.py.
STATUS_API = "http://127.0.0.1:5678/webhook/arkon-incident-status"

# Plant time. The digest fires at 07:05 so that it never shares a minute with
# the overdue timer's quarter-hour run; both append to the same log.
TIMEZONE = "Europe/Berlin"
TRIGGER_HOUR = 7
TRIGGER_MINUTE = 5

# The open lifecycle states, one read each. Must agree with OPEN_STATUSES in
# lifecycle.py; check_digest_js.py asserts that they do.
OPEN_STATES = [
    ("new", "Read New Incidents"),
    ("acknowledged", "Read Acknowledged Incidents"),
    ("in_containment", "Read In-Containment Incidents"),
]
PAGE_LIMIT = 500

# How many rows the card lists before it says "and N more". The queue count is
# always stated in full; the rows are the oldest waits.
P3_ROWS = 10
OVERDUE_ROWS = 5

# The alert group, the same chat the intake workflow and the timer post to.
CHAT_ID = "-5481573875"

COMPOSE = r"""// Arkon Daily Digest - compose.
// Three status API pages, one per open lifecycle state, plus the notification
// log for the next ARK-NTF number. Counts, sorts and formats; decides nothing the
// API already decides: `overdue` is the API's flag, the medians are its summary.
const P3_ROWS = __P3_ROWS__;
const OVERDUE_ROWS = __OVERDUE_ROWS__;
const MAX_TEXT = 3900; // Telegram rejects a message over 4096 characters
const TIMEZONE = "__TIMEZONE__";

const pages = {
  new: $('Read New Incidents').first().json,
  acknowledged: $('Read Acknowledged Incidents').first().json,
  in_containment: $('Read In-Containment Incidents').first().json,
};
const logText = $input.first().json.notifications_text ?? "";

// A page that is not a straight answer to the question asked stops the run. A
// digest composed from a rejected or foreign page would be wrong with
// confidence, and a failed execution is visible where a wrong card is not.
for (const [state, page] of Object.entries(pages)) {
  const answer = page ? page.status : undefined;
  const asked = page && page.query ? page.query.status : undefined;
  if ((answer !== "ok" && answer !== "no_match") || asked !== state) {
    throw new Error("status API page for " + state + " is not usable: status=" + answer + ", query.status=" + asked);
  }
}

// The next notification number is shared with the overdue timer: the highest
// in the log plus one, whichever workflow wrote it. A damaged line may hide the
// highest id, so it is counted onto the record rather than passed over.
let nextId = 1;
let unreadableLines = 0;
for (const line of logText.split("\n")) {
  const trimmed = line.trim();
  if (!trimmed) continue;
  let record;
  try {
    record = JSON.parse(trimmed);
  } catch (error) {
    unreadableLines += 1;
    continue;
  }
  const digits = String(record.notification_id ?? "").replace(/[^0-9]/g, "");
  if (digits) nextId = Math.max(nextId, parseInt(digits, 10) + 1);
}
const notificationId = "ARK-NTF-" + String(nextId).padStart(5, "0");

const incidentsOf = (page) => (Array.isArray(page.incidents) ? page.incidents : []);
const countByPriority = (list) => {
  const out = { P1: 0, P2: 0, P3: 0 };
  for (const incident of list) {
    const priority = String(incident.priority ?? "");
    out[priority] = (out[priority] ?? 0) + 1;
  }
  return out;
};

// Per state the count is the page's match_count, which is right even when the
// page is short; the split by priority and the two lists come from the returned
// incidents, so a truncated page makes them short, and the record says so.
const openByStatus = {};
let pagesTruncated = false;
for (const [state, page] of Object.entries(pages)) {
  openByStatus[state] = page.match_count ?? 0;
  if ((page.match_count ?? 0) > (page.returned ?? 0)) pagesTruncated = true;
}
const openIncidents = Object.values(openByStatus).reduce((a, b) => a + b, 0);
const allOpen = [].concat(incidentsOf(pages.new), incidentsOf(pages.acknowledged), incidentsOf(pages.in_containment));
const openByPriority = countByPriority(allOpen);

// The store summary rides on every page and is computed over the whole store;
// the three copies agree unless the plant moved between the reads, which is why
// the record keeps the summary's open count beside the page sum.
const summary = pages.new.store ?? {};
const responseTimes = pages.new.response_times ?? {};

// Overdue is the API's flag and it only ever applies to `new`: an acknowledged
// incident has met its window by definition.
const overdue = incidentsOf(pages.new).filter((incident) => incident.overdue === true);
overdue.sort((a, b) => (b.age_minutes ?? 0) - (a.age_minutes ?? 0));
const overdueByPriority = countByPriority(overdue);

// P3 has no push alert and no window; what is queued is what is still `new`.
const p3Queue = incidentsOf(pages.new).filter((incident) => String(incident.priority) === "P3");
p3Queue.sort((a, b) => (b.age_minutes ?? 0) - (a.age_minutes ?? 0));

// Telegram parses the body, so every value out of an incident is escaped before
// it meets the markup. HTML rather than Markdown, as on every other card here.
const esc = (value) => String(value === null || value === undefined ? "" : value)
  .replace(/&/g, "&amp;")
  .replace(/</g, "&lt;")
  .replace(/>/g, "&gt;");
const age = (minutes) => {
  if (minutes === null || minutes === undefined) return "?";
  const m = Math.round(minutes);
  if (m < 60) return m + " min";
  const h = Math.floor(m / 60);
  if (h < 24) return h + " h " + (m % 60) + " min";
  return Math.floor(h / 24) + " d " + (h % 24) + " h";
};
const clip = (text, max) => {
  const s = String(text ?? "");
  return s.length > max ? s.slice(0, max - 3) + "..." : s;
};
const num = (value) => (value === null || value === undefined ? "n/a" : String(value));

const now = new Date();
const parts = new Intl.DateTimeFormat("en-GB", {
  timeZone: TIMEZONE, year: "numeric", month: "2-digit", day: "2-digit",
  hour: "2-digit", minute: "2-digit", hourCycle: "h23",
}).formatToParts(now);
const part = (type) => (parts.find((p) => p.type === type) || {}).value ?? "";
const localStamp = part("year") + "-" + part("month") + "-" + part("day") + " " + part("hour") + ":" + part("minute");

const compose = (p3Rows, overdueRows) => {
  const lines = [
    "\u{1F4CB} <b>Arkon: daily digest</b>, " + esc(localStamp) + " (" + esc(TIMEZONE) + ")",
    "",
    "<b>Open: " + openIncidents + "</b> (P1 " + openByPriority.P1 + ", P2 " + openByPriority.P2 + ", P3 " + openByPriority.P3 + ")",
    "new " + openByStatus.new + ", acknowledged " + openByStatus.acknowledged + ", in containment " + openByStatus.in_containment,
    "<b>Overdue: " + num(summary.overdue_incidents) + "</b> unacknowledged past the window (P1 " + overdueByPriority.P1 + ", P2 " + overdueByPriority.P2 + ")",
  ];
  for (const incident of overdue.slice(0, overdueRows)) {
    lines.push("- " + esc(incident.incident_id) + " " + esc(incident.priority) + ", waiting " + age(incident.age_minutes) + ", " + esc(incident.assigned_role));
  }
  if (overdue.length > overdueRows) lines.push("  and " + (overdue.length - overdueRows) + " more");
  lines.push("");
  lines.push(
    "<b>Response times, all incidents to date:</b> " + num(responseTimes.acknowledged_incidents)
      + " acknowledged, median " + num(responseTimes.median_minutes_to_acknowledge) + " min ("
      + num(responseTimes.acknowledged_within_window) + " within the window, "
      + num(responseTimes.acknowledged_late) + " late); " + num(responseTimes.closed_incidents)
      + " closed, median " + num(responseTimes.median_minutes_to_close) + " min"
  );
  lines.push("");
  lines.push("<b>P3 queue for today's review: " + p3Queue.length + "</b>" + (p3Queue.length ? ", oldest first" : ""));
  for (const incident of p3Queue.slice(0, p3Rows)) {
    lines.push("- " + esc(incident.incident_id) + " " + esc(incident.source_module) + ", " + age(incident.age_minutes) + ": " + esc(clip(incident.summary, 90)));
  }
  if (p3Queue.length > p3Rows) lines.push("  and " + (p3Queue.length - p3Rows) + " more");
  if (pagesTruncated) {
    lines.push("");
    lines.push("Note: a state exceeded the status API page of " + __PAGE_LIMIT__ + ", so the priority split and the lists above are short; the state counts are the API's own.");
  }
  lines.push("");
  lines.push("Digest: <code>" + esc(notificationId) + "</code>");
  return lines.join("\n");
};

// Shed overdue rows first, then queue rows, until the card fits Telegram's cap:
// every overdue incident already has its own card from the timer, the P3 queue
// has nothing else. The counts stay; only the rows go.
let p3Rows = P3_ROWS;
let overdueRows = OVERDUE_ROWS;
let text = compose(p3Rows, overdueRows);
while (text.length > MAX_TEXT && (p3Rows > 0 || overdueRows > 0)) {
  if (overdueRows > 0) overdueRows -= 1;
  else p3Rows -= 1;
  text = compose(p3Rows, overdueRows);
}

return [
  {
    json: {
      digest_text: text,
      notification: {
        notification_id: notificationId,
        sent_at: null,
        incident_id: null,
        trigger: "daily_digest",
        notified_role: "Quality Steering Cell",
        channel: "telegram",
        telegram_chat_id: "__CHAT_ID__",
        telegram_message_id: null,
        run_at: now.toISOString(),
        as_of: pages.new.as_of ?? null,
        open_incidents: openIncidents,
        store_open_incidents: summary.open_incidents ?? null,
        open_by_priority: openByPriority,
        open_by_status: openByStatus,
        overdue_incidents: summary.overdue_incidents ?? null,
        overdue_by_priority: overdueByPriority,
        overdue_listed: Math.min(overdue.length, overdueRows),
        response_times: responseTimes,
        p3_queue: p3Queue.length,
        p3_listed: Math.min(p3Queue.length, p3Rows),
        pages_truncated: pagesTruncated,
        log_unreadable_lines: unreadableLines,
        // The people behind the roles are simulated under charter section 5.
        // The counts, the timestamps and the delivery are not.
        context_origin: "simulated",
      },
    },
  },
];
"""

RECORD = r"""// Arkon Daily Digest - the record, written after the card was sent.
// The Telegram node returns the Bot API envelope, `{ ok, result }`, with
// `message_id`, `chat` and `date` inside `result`; execution 7800 of the overdue
// timer on 2026-09-06 is why this unwraps the envelope rather than reading it. A
// reply that already is the result object still reads.
const raw = ($input.first() || {}).json ?? {};
const reply = raw.result && typeof raw.result === "object" ? raw.result : raw;
const record = { ...$('Compose Digest').first().json.notification };
record.telegram_message_id = reply.message_id ?? null;
record.telegram_chat_id = String((reply.chat || {}).id ?? record.telegram_chat_id);
record.sent_at = reply.date ? new Date(reply.date * 1000).toISOString() : new Date().toISOString();

return [{ json: { notifications_jsonl: JSON.stringify(record) + "\n", notified: 1 } }];
"""


def http_read(node_id, name, position, state):
    # A 503 from the status API must stop the run, never read as "nothing is
    # open". Same separation the API draws, on the consuming side.
    return {
        "id": node_id,
        "name": name,
        "type": "n8n-nodes-base.httpRequest",
        "typeVersion": 4.2,
        "position": position,
        "onError": "continueErrorOutput",
        "parameters": {
            "url": STATUS_API,
            "sendQuery": True,
            "queryParameters": {
                "parameters": [
                    {"name": "status", "value": state},
                    {"name": "limit", "value": str(PAGE_LIMIT)},
                ]
            },
            "options": {"timeout": 20000},
        },
    }


read_nodes = [
    http_read("d1000000-0000-4000-8000-00000000000%d" % (index + 2), name, [-880 + 224 * (index + 1), 0], state)
    for index, (state, name) in enumerate(OPEN_STATES)
]

compose_js = (
    COMPOSE.replace("__P3_ROWS__", str(P3_ROWS))
    .replace("__OVERDUE_ROWS__", str(OVERDUE_ROWS))
    .replace("__TIMEZONE__", TIMEZONE)
    .replace("__PAGE_LIMIT__", str(PAGE_LIMIT))
    .replace("__CHAT_ID__", CHAT_ID)
)

workflow = {
    "id": "arkonDigest001",
    "name": "Arkon Daily Digest v1",
    "nodes": [
        {
            "id": "d1000000-0000-4000-8000-000000000001",
            "name": "Digest Timer",
            "type": "n8n-nodes-base.scheduleTrigger",
            "typeVersion": 1.2,
            "position": [-880, 0],
            # Once a day at a fixed clock time in the workflow's timezone, which the
            # settings below pin to plant time. Without triggerAtHour and
            # triggerAtMinute the node picks a stable random time of its own.
            "parameters": {
                "rule": {
                    "interval": [
                        {
                            "field": "days",
                            "daysInterval": 1,
                            "triggerAtHour": TRIGGER_HOUR,
                            "triggerAtMinute": TRIGGER_MINUTE,
                        }
                    ]
                }
            },
        },
        *read_nodes,
        {
            "id": "d1000000-0000-4000-8000-000000000005",
            "name": "Halt: Status API Unavailable",
            "type": "n8n-nodes-base.noOp",
            "typeVersion": 1,
            "position": [-208, 208],
            "parameters": {},
        },
        {
            "id": "d1000000-0000-4000-8000-000000000006",
            "name": "Read Notification Log",
            "type": "n8n-nodes-base.readWriteFile",
            "typeVersion": 1.1,
            "position": [16, -32],
            # An unreadable log read as empty would restart the ARK-NTF numbering
            # inside a log that already holds higher ids. Doing nothing is the only
            # safe answer, so the error branch ends the run.
            "onError": "continueErrorOutput",
            "parameters": {"operation": "read", "fileSelector": NOTIFICATION_STORE, "options": {}},
        },
        {
            "id": "d1000000-0000-4000-8000-000000000007",
            "name": "Halt: Notification Log Unreadable",
            "type": "n8n-nodes-base.noOp",
            "typeVersion": 1,
            "position": [240, 208],
            "parameters": {},
        },
        {
            "id": "d1000000-0000-4000-8000-000000000008",
            "name": "Extract Notification Log",
            "type": "n8n-nodes-base.extractFromFile",
            "typeVersion": 1.1,
            "position": [240, -32],
            "parameters": {
                "operation": "text",
                "binaryPropertyName": "data",
                "destinationKey": "notifications_text",
                "options": {},
            },
        },
        {
            "id": "d1000000-0000-4000-8000-000000000009",
            "name": "Compose Digest",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [464, -32],
            # Always exactly one item: a quiet plant is a digest too. A page that
            # cannot be trusted throws, so the execution fails rather than sends.
            "parameters": {"jsCode": compose_js},
        },
        {
            "id": "d1000000-0000-4000-8000-00000000000a",
            "name": "Send Digest",
            "type": "n8n-nodes-base.telegram",
            "typeVersion": 1.2,
            "position": [688, -32],
            "parameters": {
                "chatId": CHAT_ID,
                "text": "={{ $json.digest_text }}",
                "additionalFields": {"appendAttribution": False, "parse_mode": "HTML"},
            },
            "credentials": {"telegramApi": {"name": "Arkon Telegram Bot"}},
        },
        {
            "id": "d1000000-0000-4000-8000-00000000000b",
            "name": "Build Digest Record",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [912, -32],
            "parameters": {"jsCode": RECORD},
        },
        {
            "id": "d1000000-0000-4000-8000-00000000000c",
            "name": "Build Digest Line",
            "type": "n8n-nodes-base.convertToFile",
            "typeVersion": 1.1,
            "position": [1136, -32],
            "parameters": {
                "operation": "toText",
                "sourceProperty": "notifications_jsonl",
                "options": {},
            },
        },
        {
            "id": "d1000000-0000-4000-8000-00000000000d",
            "name": "Append Notification Log",
            "type": "n8n-nodes-base.readWriteFile",
            "typeVersion": 1.1,
            "position": [1360, -32],
            "parameters": {
                "operation": "write",
                "fileName": NOTIFICATION_STORE,
                "options": {"append": True},
            },
        },
    ],
    "connections": {
        "Digest Timer": {"main": [[{"node": "Read New Incidents", "type": "main", "index": 0}]]},
        "Read New Incidents": {
            "main": [
                [{"node": "Read Acknowledged Incidents", "type": "main", "index": 0}],
                [{"node": "Halt: Status API Unavailable", "type": "main", "index": 0}],
            ]
        },
        "Read Acknowledged Incidents": {
            "main": [
                [{"node": "Read In-Containment Incidents", "type": "main", "index": 0}],
                [{"node": "Halt: Status API Unavailable", "type": "main", "index": 0}],
            ]
        },
        "Read In-Containment Incidents": {
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
        "Extract Notification Log": {"main": [[{"node": "Compose Digest", "type": "main", "index": 0}]]},
        "Compose Digest": {"main": [[{"node": "Send Digest", "type": "main", "index": 0}]]},
        "Send Digest": {"main": [[{"node": "Build Digest Record", "type": "main", "index": 0}]]},
        "Build Digest Record": {"main": [[{"node": "Build Digest Line", "type": "main", "index": 0}]]},
        "Build Digest Line": {"main": [[{"node": "Append Notification Log", "type": "main", "index": 0}]]},
    },
    # `timezone` is what the Schedule Trigger reads; see the module docstring.
    "settings": {
        "executionOrder": "v1",
        "binaryMode": "separate",
        "availableInMCP": False,
        "timezone": TIMEZONE,
    },
    "pinData": {},
}

OUT.write_text(json.dumps(workflow, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
print("written", OUT, OUT.stat().st_size, "bytes")
