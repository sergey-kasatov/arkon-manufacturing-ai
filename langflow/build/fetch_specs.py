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


def write(slug, spec, label):
    path = HERE / ("spec_%s.json" % slug)
    path.write_text(json.dumps({"name": label, "spec": spec}, indent=1, ensure_ascii=False), encoding="utf-8")
    fields = len(spec.get("template", {}))
    print("  %-22s %-34s %d fields, %d outputs" % (slug, label, fields, len(spec.get("outputs", []))))


wanted = sys.argv[1:] or list(COMPONENTS) + list(CUSTOM)
for slug in wanted:
    if slug in COMPONENTS:
        fetch_catalog(slug, COMPONENTS[slug])
    elif slug in CUSTOM:
        fetch_custom(slug, CUSTOM[slug])
    else:
        raise SystemExit("unknown spec %r, known: %s" % (slug, ", ".join(sorted(set(COMPONENTS) | set(CUSTOM)))))
