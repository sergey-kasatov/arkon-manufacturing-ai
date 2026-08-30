"""Fetch component templates from the running Langflow into this directory.

The build scripts instantiate nodes from the same templates the frontend uses,
which means they need a live Langflow. They ran without this file once and the
templates were left behind in a session scratchpad, so the committed pipeline
could not be re-run. This closes that.

Credentials never come to Windows: the fetch is done by lf_api.py on the NAS,
which reads the superuser login out of the compose .env beside the container.

    python langflow/build/fetch_specs.py
    python langflow/build/fetch_specs.py apirequest smartrouter
"""

import json
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).parent
REPO = HERE.parent.parent
HOST = "ResSak@AK2101"
REMOTE = "cd ~/arkon-tmp && python3 lf_api.py"

# slug -> component type name in /api/v1/all
COMPONENTS = {
    "prompttemplate": "Prompt Template",
    "apirequest": "APIRequest",
    "smartrouter": "SmartRouter",
    "humaninput": "HumanInput",
    "runflow": "RunFlow",
    "file": "File",
    "splittext": "SplitText",
    "tableops": "DataFrameOperations",
    "qdrant": "ext:qdrant:QdrantVectorStoreComponent@official",
    "chatoutput": "ChatOutput",
}

# Custom components have no catalog entry: Langflow builds their template from
# the posted source, which is also how the UI does it.
CUSTOM = {"openrouterembeddings": REPO / "langflow" / "components" / "openrouter_embeddings.py"}

# A Run Flow node outside tool mode grows inputs and outputs named after the
# sub-flow's own vertices. Langflow computes them; guessing the convention is how
# an edge ends up present in the file and dead on the canvas.
DERIVED = {"runflow_briefing": ("runflow", "Arkon_Shift_Briefing", "063c6445-ef32-49e5-93a9-dc7764a40a48")}


def ssh(command, stdin=None):
    result = subprocess.run(
        ["ssh", HOST, command], input=stdin, capture_output=True, text=True, encoding="utf-8"
    )
    if result.returncode != 0:
        raise SystemExit("ssh failed: %s\n%s" % (command, result.stderr[-2000:]))
    return result.stdout


def fetch_catalog(slug, type_name):
    payload = json.loads(ssh("%s component '%s'" % (REMOTE, type_name)))
    write(slug, payload["spec"], type_name)


def fetch_custom(slug, source):
    """Ask Langflow to build a node template from custom component source."""
    code = source.read_text(encoding="utf-8")
    ssh("cat > /tmp/cc_body.json", stdin=json.dumps({"code": code}))
    payload = json.loads(ssh("%s raw POST /api/v1/custom_component /tmp/cc_body.json" % REMOTE))
    write(slug, payload["data"], payload["type"])


def fetch_derived(slug, base_slug, flow_name, flow_id):
    """Ask Langflow to populate a Run Flow node for one sub-flow, as the UI does.

    Picking a flow in the dropdown fires update_build_config, which adds an input
    per input vertex of the sub-flow and an output per output vertex, named
    `<vertex-id>~<field>`. Reproducing that naming by hand is how an edge ends up
    present in the JSON and dead on the canvas.
    """
    template = json.loads((HERE / ("spec_%s.json" % base_slug)).read_text(encoding="utf-8"))["spec"]["template"]
    template["flow_name_selected"].update({
        "value": flow_name,
        "options": [flow_name],
        "options_metadata": [{"id": flow_id}],
        "selected_metadata": {"id": flow_id},
    })
    template["flow_id_selected"]["value"] = flow_id
    body = {
        "code": template["code"]["value"],
        "field": "flow_name_selected",
        "field_value": flow_name,
        "template": template,
        "tool_mode": False,
    }
    ssh("cat > /tmp/rf_update.json", stdin=json.dumps(body))
    answer = json.loads(ssh("%s raw POST /api/v1/custom_component/update /tmp/rf_update.json" % REMOTE))
    node = answer.get("data", answer)
    write(slug, node, "RunFlow -> " + flow_name)


def write(slug, spec, label):
    path = HERE / ("spec_%s.json" % slug)
    path.write_text(json.dumps({"name": label, "spec": spec}, indent=1, ensure_ascii=False), encoding="utf-8")
    fields = len(spec.get("template", {}))
    print("  %-22s %-34s %d fields, %d outputs" % (slug, label, fields, len(spec.get("outputs", []))))


wanted = sys.argv[1:] or list(COMPONENTS) + list(CUSTOM) + list(DERIVED)
for slug in wanted:
    if slug in COMPONENTS:
        fetch_catalog(slug, COMPONENTS[slug])
    elif slug in CUSTOM:
        fetch_custom(slug, CUSTOM[slug])
    elif slug in DERIVED:
        fetch_derived(slug, *DERIVED[slug])
    else:
        known = sorted(set(COMPONENTS) | set(CUSTOM) | set(DERIVED))
        raise SystemExit("unknown spec %r, known: %s" % (slug, ", ".join(known)))
