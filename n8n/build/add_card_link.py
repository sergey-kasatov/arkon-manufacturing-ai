"""Put the operator surface's link on the Telegram card, in any copy of the workflow.

The card is step 4 of `docs/Incident_Process.md` and the operator's controls are
step 5, and until now nothing joined them: a person who received a card had to
know the cockpit exists, find it, and search the queue for the incident they had
just been told about. One link closes that gap in a tap.

This is a script rather than an edit because the same change has to be made
twice, to two documents that are not the same file. `n8n/quality_steering_cell_v1.json`
is the tracked source; the LIVE workflow is deployed by exporting it, patching
the export and importing that back, because the running row carries `staticData`
(the incident counter and the dedup cache) and a credential bound by internal id,
neither of which survives an import of the tracked file. The reasoning is in
`n8n/README.md`, "the deploy is not a plain import". Doing the edit by hand on
the export is precisely the step that invites a typo into a running system.

The patch is idempotent and asserts its anchors: it refuses to write when the
code it expects is not there in exactly one place, so a workflow that has drifted
fails loudly instead of getting a second copy of the link.

Usage:

    py n8n/build/add_card_link.py n8n/quality_steering_cell_v1.json
    py n8n/build/add_card_link.py /tmp/exp.json --out /tmp/patched.json
"""

import argparse
import json
import pathlib
import sys

# The base of the link. It is an ADDRESS and not the NAS host name on purpose:
# the phone that receives the card is on the house LAN and does not resolve the
# NetBIOS name `AK2101`, and it is not on the tailnet either (checked 2026-09-05,
# `tailscale status` lists the iPhone offline for 91 days), so neither of the two
# names this project normally uses would open. Overridable at run time through
# `ARKON_COCKPIT_URL` in n8n's environment.
COCKPIT_BASE = "http://192.168.178.100:8303"

NODE_NAME = "Validate + Dedup + Incident"

# Inserted before the alert body is assembled.
LINK_HELPER = '''// The card is step 4 of the process and the operator's controls are step 5, so the
// card carries a link that opens the cockpit's Steering Cell page on this one
// incident. The base is an address rather than a host name because the phone that
// receives the card resolves neither `AK2101` nor the tailnet name; set
// ARKON_COCKPIT_URL in n8n's environment to point it somewhere else.
let cockpitBase = "%s";
try {
  if (typeof $env !== "undefined" && $env.ARKON_COCKPIT_URL) {
    cockpitBase = String($env.ARKON_COCKPIT_URL);
  }
} catch (err) {
  // Env access is blocked in some n8n configurations. The default above stands.
}
cockpitBase = cockpitBase.replace(/\\/+$/, "");
const cockpitLink = (incidentId) =>
  cockpitBase + "/steering_cell?incident=" + encodeURIComponent(incidentId);

''' % COCKPIT_BASE

ANCHOR_HELPER = "let alertText = null;\n"

ANCHOR_LINE = '    "Event: <code>" + esc(event.event_id) + "</code>",\n  ].join("\\n");'

REPLACEMENT_LINE = (
    '    "Event: <code>" + esc(event.event_id) + "</code>",\n'
    '    "",\n'
    '    \'<a href="\' + cockpitLink(incident.incident_id) + \'">Open in the Steering Cell</a>\',\n'
    '  ].join("\\n");'
)

MARKER = "cockpitLink"


def patch_code(code):
    """Return the patched Code-node body, or None when it is already patched."""
    if MARKER in code:
        return None

    for anchor, what in ((ANCHOR_HELPER, "alert body start"), (ANCHOR_LINE, "last card line")):
        found = code.count(anchor)
        if found != 1:
            raise SystemExit(
                "anchor '%s' appears %d times, expected exactly 1. The workflow has "
                "drifted from what this patch was written against; read the Code node "
                "and update this script rather than forcing the edit." % (what, found)
            )

    code = code.replace(ANCHOR_HELPER, LINK_HELPER + ANCHOR_HELPER)
    code = code.replace(ANCHOR_LINE, REPLACEMENT_LINE)
    return code


def patch_document(doc):
    """Patch the one Code node in a workflow document. Returns True when changed.

    `n8n export:workflow` writes a one-element ARRAY even for a single id, while
    the tracked file is a bare object. Both shapes arrive here, and the one this
    script is handed is the one it writes back.
    """
    if isinstance(doc, list):
        if len(doc) != 1:
            raise SystemExit("expected one workflow in the export, found %d" % len(doc))
        doc = doc[0]

    nodes = doc.get("nodes") or []
    targets = [n for n in nodes if n.get("name") == NODE_NAME]
    if len(targets) != 1:
        raise SystemExit(
            "expected exactly one node named %r, found %d" % (NODE_NAME, len(targets))
        )

    node = targets[0]
    code = node["parameters"]["jsCode"]
    patched = patch_code(code)
    if patched is None:
        return False
    node["parameters"]["jsCode"] = patched
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
