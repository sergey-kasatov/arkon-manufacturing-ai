"""Write every intake outcome down: charter 7.6, in any copy of the workflow.

Every event that reaches the Steering Cell webhook has exactly one of three
outcomes: recorded as an incident, rejected against the section 6 contract, or
suppressed as a duplicate inside the 24-hour window. Until 2026-09-06 only the
first was written anywhere, so duplicate suppression could not be counted and a
validation regression looked exactly like a quiet plant (charter 7.6). This patch
adds one Code node that runs once per event on every branch and two plumbing
nodes that append its line to `/data/arkon/intake_outcomes.jsonl`.

The node hangs off the four Respond nodes rather than off the branches before
them, for two reasons. The caller is answered first, so the log can never delay
or fail an intake; and on the alert branch it runs after the Telegram node has
answered, so the line for an alerted incident carries Telegram's own
`message_id`, which the platform had never recorded for an intake card. An alert
that fails loses the line and never the incident: the store already has it, and
the failed execution is the trace.

Like `add_card_link.py`, this is a script because the same change goes into two
documents: the tracked `n8n/quality_steering_cell_v1.json` and the LIVE workflow,
which is deployed by exporting it, patching the export and importing that back,
because the running row carries `staticData` (the incident counter and the dedup
cache) and a credential bound by internal id (`n8n/README.md`, "the deploy is not
a plain import"). The patch is idempotent and asserts its anchors: it refuses to
write when the four Respond nodes are not there exactly once each or already
continue somewhere.

Usage:

    py n8n/build/add_intake_outcomes.py n8n/quality_steering_cell_v1.json
    py n8n/build/add_intake_outcomes.py /tmp/exp.json --out /tmp/patched.json
"""

import argparse
import json
import pathlib
import sys

INTAKE_LOG = "/data/arkon/intake_outcomes.jsonl"

NODE_NAME = "Build Intake Outcome"
LINE_NODE_NAME = "Build Intake Outcome Line"
APPEND_NODE_NAME = "Append Intake Log"

# The four ends of the intake, one per outcome the caller can be told.
SOURCES = ["Respond Invalid", "Respond Duplicate", "Respond Recorded", "Respond Alerted"]

OUTCOME_JS = r"""// Arkon Quality Steering Cell - intake outcome, charter 7.6.
// Every event that reaches the webhook has exactly one of three outcomes:
// recorded as an incident, rejected against the contract, or suppressed as a
// duplicate inside the 24-hour window. Until 2026-09-06 only the first was
// written anywhere, so suppression could not be counted and a validation
// regression was indistinguishable from a quiet plant. This node sits after all
// four Respond nodes, so it runs once per event whatever happened, after the
// caller was answered, and writes one line to /data/arkon/intake_outcomes.jsonl.
const verdict = $('Validate + Dedup + Incident').first().json;
const raw = $('Event Intake').first().json;
const event = raw && raw.body && typeof raw.body === "object" ? raw.body : (raw && typeof raw === "object" ? raw : {});
const evidence = event.evidence && typeof event.evidence === "object" ? event.evidence : {};
const context = event.operational_context && typeof event.operational_context === "object" ? event.operational_context : {};

let outcome;
let reason = null;
if (verdict.valid === false) {
  outcome = "rejected";
  reason = Array.isArray(verdict.errors) && verdict.errors.length ? verdict.errors.join("; ") : "contract violation";
} else if (verdict.duplicate === true) {
  outcome = "duplicate_suppressed";
  reason = "same record_id and priority inside the 24 h window";
} else {
  outcome = "recorded";
}

// On the alert branch this node runs after the Telegram node answered, so the
// reply is real evidence of the card; read it the way the overdue timer does
// (the Bot API envelope, or the bare result), and never fail the line over it.
let telegramMessageId = null;
if (outcome === "recorded" && verdict.alert === true) {
  try {
    const sent = $('Telegram Alert').first().json ?? {};
    const reply = sent.result && typeof sent.result === "object" ? sent.result : sent;
    telegramMessageId = reply.message_id ?? null;
  } catch (error) {
    telegramMessageId = null;
  }
}

const recordId = evidence.record_id ?? null;
const priority = event.priority ?? null;
let executionId = null;
try {
  executionId = typeof $execution !== "undefined" && $execution && $execution.id ? String($execution.id) : null;
} catch (error) {
  executionId = null;
}

const line = {
  received_at: new Date().toISOString(),
  execution_id: executionId,
  outcome: outcome,
  reason: reason,
  event_id: event.event_id ?? null,
  record_id: recordId,
  priority: priority,
  source_module: event.source_module ?? null,
  business_domain: event.business_domain ?? null,
  dedup_key: recordId !== null && priority !== null ? String(recordId) + "|" + String(priority) : null,
  incident_id: outcome === "recorded" && verdict.incident ? (verdict.incident.incident_id ?? null) : null,
  alert_branch: outcome === "recorded" && verdict.alert === true,
  telegram_message_id: telegramMessageId,
  errors: outcome === "rejected" && Array.isArray(verdict.errors) ? verdict.errors : [],
  emitter: context.emitter ?? null,
  context_origin: context.context_origin ?? event.context_origin ?? null,
};

return [{ json: { intake_outcome_jsonl: JSON.stringify(line) + "\n" } }];
"""

NEW_NODES = [
    {
        "parameters": {"jsCode": OUTCOME_JS},
        "id": "f1000000-0000-4000-8000-000000000001",
        "name": NODE_NAME,
        "type": "n8n-nodes-base.code",
        "typeVersion": 2,
        "position": [448, 240],
    },
    {
        "parameters": {"operation": "toText", "sourceProperty": "intake_outcome_jsonl", "options": {}},
        "id": "f1000000-0000-4000-8000-000000000002",
        "name": LINE_NODE_NAME,
        "type": "n8n-nodes-base.convertToFile",
        "typeVersion": 1.1,
        "position": [672, 240],
    },
    {
        "parameters": {"operation": "write", "fileName": INTAKE_LOG, "options": {"append": True}},
        "id": "f1000000-0000-4000-8000-000000000003",
        "name": APPEND_NODE_NAME,
        "type": "n8n-nodes-base.readWriteFile",
        "typeVersion": 1.1,
        "position": [896, 240],
    },
]


def patch_document(doc):
    """Patch one workflow document in place. Returns True when changed.

    `n8n export:workflow` writes a one-element ARRAY even for a single id, while
    the tracked file is a bare object. Both shapes arrive here.
    """
    if isinstance(doc, list):
        if len(doc) != 1:
            raise SystemExit("expected one workflow in the export, found %d" % len(doc))
        doc = doc[0]

    nodes = doc.get("nodes") or []
    names = [n.get("name") for n in nodes]
    if NODE_NAME in names:
        return False

    for source in SOURCES:
        if names.count(source) != 1:
            raise SystemExit("expected exactly one node named %r, found %d" % (source, names.count(source)))
    for name in (LINE_NODE_NAME, APPEND_NODE_NAME):
        if name in names:
            raise SystemExit("node %r exists without %r: the workflow has drifted, read it before patching" % (name, NODE_NAME))

    connections = doc.setdefault("connections", {})
    for source in SOURCES:
        outs = connections.get(source, {}).get("main", [])
        if any(outs):
            raise SystemExit(
                "%r already continues to %s; this patch expects the Respond nodes to end their branches"
                % (source, [t.get("node") for out in outs for t in out])
            )

    for node in NEW_NODES:
        nodes.append(json.loads(json.dumps(node)))
    for source in SOURCES:
        connections[source] = {"main": [[{"node": NODE_NAME, "type": "main", "index": 0}]]}
    connections[NODE_NAME] = {"main": [[{"node": LINE_NODE_NAME, "type": "main", "index": 0}]]}
    connections[LINE_NODE_NAME] = {"main": [[{"node": APPEND_NODE_NAME, "type": "main", "index": 0}]]}
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workflow", help="workflow JSON to patch")
    parser.add_argument("--out", help="write here instead of in place")
    args = parser.parse_args()

    path = pathlib.Path(args.workflow)
    doc = json.loads(path.read_text(encoding="utf-8"))
    changed = patch_document(doc)

    out = pathlib.Path(args.out) if args.out else path
    if not changed and args.out is None:
        print("already patched, nothing written: %s" % path)
        return 0

    out.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("%s: %s" % ("patched" if changed else "already patched, copied", out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
