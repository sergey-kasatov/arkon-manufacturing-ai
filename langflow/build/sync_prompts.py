"""Write the repository prompt blocks into the existing canvas, and change nothing else.

The build claims the documents and the canvas cannot drift, because the sprint
scripts read the fenced blocks out of the repository prompt files. That is true at
build time and only then: editing a prompt afterwards meant re-running the whole
sprint chain, and the retrieval script is not idempotent, so a re-run would add
the store nodes a second time.

This script closes that gap. It reads every `### BLOCK: name` from `langflow/prompts/`
documents, matches each to the node it belongs to, and rewrites exactly those
fields in `arkon_quality_assistant.json`. No node is added, removed or moved. It
prints what changed and refuses to touch a node it cannot find, so a rename in
either place is an error rather than a silent no-op.

Run it from the repository root, then upsert the flow:

    python langflow/build/sync_prompts.py
    python langflow/build/sync_prompts.py --deploy
"""

import json
import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import prompts

HERE = pathlib.Path(__file__).parent
REPO = HERE.parent.parent
FLOW = REPO / "langflow" / "arkon_quality_assistant.json"
HOST = "ResSak@AK2101"
REMOTE = "cd ~/arkon-tmp && python3 lf_api.py"

# block name -> (node display name, template field). The block itself is looked
# up by name across `langflow/prompts/`, so which file holds it is not encoded
# here and a block can be moved between files without touching this table.
BINDINGS = {
    # The four agents. Every one of them carries a system prompt that this
    # script is the only supported way to change.
    "procedure_v2": ("Procedure Specialist", "system_prompt"),
    "incident": ("Incident Specialist", "system_prompt"),
    "escalation_v2": ("Escalation Specialist", "system_prompt"),
    "declined": ("Escalation Declined", "system_prompt"),
    # All six route descriptions, so the router's own definition of a route
    # cannot drift from the document either.
    "route_procedure": ("Intent Router", "routes:Quality procedure"),
    "route_incident_v2": ("Intent Router", "routes:Incident status"),
    "route_escalation": ("Intent Router", "routes:Escalation request"),
    "route_out_of_scope": ("Intent Router", "routes:Out of scope"),
    "route_briefing": ("Intent Router", "routes:Shift briefing"),
    "route_unclear": ("Intent Router", "routes:Unclear request"),
    "router_instructions_v3": ("Intent Router", "custom_prompt"),
    # A route can carry a fixed message that reaches its output with no model
    # call. Two of the six do, and they are prompts like any other.
    "unclear_message": ("Intent Router", "routes:Unclear request:output_value"),
    "scope_out_message": ("Intent Router", "routes:Out of scope:output_value"),
}

# Every prompt field on the canvas is listed above. That matters more than it
# looks: this table is the whole scope of the "no drift" claim, and until
# 2026-08-31 it held seven of the fourteen. The missing seven were not reported
# as unsynced, because a block the table never mentions is a block the script
# never looks at - so "the local flow already matches the documents" was a
# statement about the listed fields and nothing more. Add the binding whenever a
# prompt field is added to the canvas.


def node_by_name(flow, display_name):
    for node in flow["data"]["nodes"]:
        if node["data"]["node"].get("display_name") == display_name:
            return node
    raise SystemExit("no node named %r on the canvas" % display_name)


def main():
    flow = json.loads(FLOW.read_text(encoding="utf-8"))
    changed = 0

    for block_name, (display_name, field) in BINDINGS.items():
        wanted = prompts.block(block_name)
        node = node_by_name(flow, display_name)
        template = node["data"]["node"]["template"]

        if field.startswith("routes:"):
            parts = field.split(":")
            category, key = parts[1], (parts[2] if len(parts) > 2 else "route_description")
            routes = template["routes"]["value"]
            row = next((r for r in routes if r.get("route_category") == category), None)
            if row is None:
                raise SystemExit("no route %r on %s" % (category, display_name))
            if (row.get(key) or "").strip() != wanted:
                row[key] = wanted
                changed += 1
                print("  updated route %-18s %s" % (category, key))
            continue

        if (template[field].get("value") or "").strip() != wanted:
            template[field]["value"] = wanted
            changed += 1
            print("  updated %-14s on %s (%d characters)" % (field, display_name, len(wanted)))

    if changed:
        FLOW.write_text(json.dumps(flow, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print("wrote %s, %d field(s) changed" % (FLOW.name, changed))
    else:
        print("the local flow already matches the documents")

    # --deploy pushes whether or not the local file changed. The local file being
    # in sync says nothing about the running instance, and an early return here
    # made the first --deploy of this script a silent no-op.
    if "--deploy" in sys.argv:
        subprocess.run(["ssh", HOST, "cat > /tmp/arkon_flow.json"],
                       input=FLOW.read_bytes(), check=True)
        result = subprocess.run(["ssh", HOST, "%s upsert /tmp/arkon_flow.json" % REMOTE],
                                capture_output=True, check=True)
        print(result.stdout.decode("utf-8", "replace").strip())


if __name__ == "__main__":
    main()
