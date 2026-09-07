"""Make a write path call the store sync: one Execute Sub-workflow node, in any
copy of the workflow.

Charter 7.5's projection (`build_store_sync_workflow.py`) is only current if a
sync follows every write, so the two workflows that append to the logs call
`arkonStoreSync1` right after their append node: the Steering Cell after
`Append Incident Record`, the transition endpoint after `Append Transition
Record`. The call does not wait for the sub-workflow and never fails the caller
(`onError: continueRegularOutput`), so an intake or a transition is never slowed
or refused by its own projection; a sync that did not happen is redone by the
next one, because every sync starts from the counters in the summary row.

Like `add_intake_outcomes.py`, this is a script because the same change goes
into two documents: the tracked JSON and the LIVE workflow, which is deployed by
exporting it, patching the export and importing that back, because both running
rows carry `staticData` (the incident counter and the dedup cache; the
transition counter). The transition generator imports `sync_node()` from here so
its tracked file and this patch cannot produce different nodes. The patch is
idempotent and asserts its anchor: it refuses to write when the anchor node is
not there exactly once or already continues to a Sync Store node.

Usage:

    py n8n/build/add_store_sync.py n8n/quality_steering_cell_v1.json --anchor "Append Incident Record" --source steering_cell
    py n8n/build/add_store_sync.py /tmp/exp.json --anchor "Append Transition Record" --source transition --out /tmp/patched.json
"""

import argparse
import json
import pathlib
import sys

SYNC_WORKFLOW_ID = "arkonStoreSync1"
NODE_NAME = "Sync Store"

# Where the node sits, per caller: the anchor it follows, the input it declares.
CALLERS = {
    "steering_cell": {"anchor": "Append Incident Record", "id": "e1000000-0000-4000-8000-000000000051", "offset": [224, 224]},
    "transition": {"anchor": "Append Transition Record", "id": "e1000000-0000-4000-8000-000000000052", "offset": [224, -176]},
}


def sync_node(source, position):
    """The Execute Sub-workflow node that starts one store sync and moves on."""
    return {
        "id": CALLERS[source]["id"],
        "name": NODE_NAME,
        "type": "n8n-nodes-base.executeWorkflow",
        "typeVersion": 1.3,
        "position": list(position),
        # A sync that cannot be started must not fail the write that triggered it.
        "onError": "continueRegularOutput",
        "parameters": {
            "workflowId": {"__rl": True, "mode": "id", "value": SYNC_WORKFLOW_ID},
            "workflowInputs": {
                "mappingMode": "defineBelow",
                "value": {"source": source, "rebuild": False},
                "matchingColumns": [],
                "schema": [
                    {"id": "source", "displayName": "source", "required": False, "defaultMatch": False,
                     "display": True, "type": "string", "canBeUsedToMatch": True, "removed": False},
                    {"id": "rebuild", "displayName": "rebuild", "required": False, "defaultMatch": False,
                     "display": True, "type": "boolean", "canBeUsedToMatch": True, "removed": False},
                ],
                "attemptToConvertTypes": False,
                "convertFieldsToString": False,
            },
            "mode": "once",
            "options": {"waitForSubWorkflow": False},
        },
    }


def node_named(doc, name):
    hits = [n for n in doc["nodes"] if n["name"] == name]
    if len(hits) != 1:
        raise SystemExit("expected one node named %r, found %d" % (name, len(hits)))
    return hits[0]


def patch_document(doc, source="steering_cell", anchor=None):
    """Add the Sync Store node after the anchor. Returns False when already there."""
    anchor = anchor or CALLERS[source]["anchor"]
    anchor_node = node_named(doc, anchor)
    outs = doc.setdefault("connections", {}).setdefault(anchor, {}).setdefault("main", [[]])
    if not outs:
        outs.append([])
    targets = [t["node"] for t in outs[0]]
    present = [n for n in doc["nodes"] if n["name"] == NODE_NAME]
    if present and NODE_NAME in targets:
        return False
    if present or NODE_NAME in targets:
        raise SystemExit("a half-applied Sync Store patch is in the document; refusing to write")
    position = [anchor_node["position"][0] + CALLERS[source]["offset"][0],
                anchor_node["position"][1] + CALLERS[source]["offset"][1]]
    doc["nodes"].append(sync_node(source, position))
    outs[0].append({"node": NODE_NAME, "type": "main", "index": 0})
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("workflow", help="workflow JSON: the tracked file or a live export")
    parser.add_argument("--source", choices=sorted(CALLERS), default="steering_cell")
    parser.add_argument("--anchor", default=None, help="node whose output gains the sync call")
    parser.add_argument("--out", default=None, help="write here instead of in place")
    args = parser.parse_args()

    path = pathlib.Path(args.workflow)
    text = path.read_text(encoding="utf-8")
    loaded = json.loads(text)
    doc = loaded[0] if isinstance(loaded, list) else loaded

    if not patch_document(doc, args.source, args.anchor):
        print("already patched, nothing written")
        return 0
    out = pathlib.Path(args.out) if args.out else path
    newline = "\r\n" if "\r\n" in text else "\n"
    body = json.dumps(loaded, indent=2, ensure_ascii=True) + "\n"
    out.write_text(body.replace("\n", newline), encoding="utf-8", newline="")
    print("written %s: %s after %s" % (out, NODE_NAME, args.anchor or CALLERS[args.source]["anchor"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
