"""Deploy a patch to the LIVE Steering Cell, run ON THE NAS. Stdlib only.

The Steering Cell cannot be updated by importing the tracked file: the running
row carries `staticData` (the incident counter and the 24-hour dedup cache) and
a Telegram credential bound by internal id, and `import:workflow` rewrites the
whole row (`n8n/README.md`, "the deploy is not a plain import"). So a change goes
in the other way round: export the live workflow, apply the patch to that export,
assert that nothing but the patch changed, import the result, publish, restart.
This script is that recipe as code, with the two checks it needs and one it
gained on 2026-09-06.

The new check is a race. The live plant raises an incident every ten minutes or
so, and every one advances the counter and the cache in the running row. An
export taken before a tick and imported after it rewinds both by one, silently:
the next incident would reuse an id the store already holds. So the script reads
the plant's ledger, waits until a tick has just happened, and does the whole
export-to-restart inside the quiet minutes after it; afterwards it reads the live
counter back and compares it with the highest id in the store.

    python3 deploy_steering_cell.py add_intake_outcomes            # patch module beside this file
    python3 deploy_steering_cell.py add_intake_outcomes --no-wait  # skip the tick window (a stopped plant)

The patch module must expose `patch_document(doc) -> bool` and be importable from
this script's directory. Rollback is the pre-deploy export under
`/volume1/docker/arkon/_predeploy_<date>/`, imported the same way.
"""

import datetime as dt
import importlib
import json
import os
import pathlib
import subprocess
import sys
import time

WORKFLOW_ID = "o0vXtlRWIs9yFrUJ"
ARKON = pathlib.Path("/volume1/docker/arkon")           # host side of the bind mount
CONTAINER_ARKON = "/data/arkon"                          # the same directory inside n8n
LEDGER = ARKON / "live_plant" / "emitted.jsonl"
STORE = ARKON / "incidents.jsonl"
DB = pathlib.Path("/volume1/docker/n8n/n8n_data/database.sqlite")

# A tick is "fresh" for this long after it; the deploy takes well under a minute.
FRESH_SECONDS = 150
# If the last tick is older than this, the next one is due: wait for it instead.
STALE_SECONDS = 420
WAIT_LIMIT_SECONDS = 900


def sh(*args, check=True):
    result = subprocess.run(list(args), capture_output=True, text=True)
    if check and result.returncode != 0:
        sys.exit("command failed: %s\n%s%s" % (" ".join(args), result.stdout, result.stderr))
    return result.stdout


def docker(*args, check=True):
    return sh("docker", "exec", "n8n", *args, check=check)


def last_tick_age():
    if not LEDGER.exists():
        return None
    last = None
    with open(LEDGER, encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                last = line
    if not last:
        return None
    at = json.loads(last)["at"]
    when = dt.datetime.strptime(at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    return (dt.datetime.now(dt.timezone.utc) - when).total_seconds()


def wait_for_quiet_window():
    age = last_tick_age()
    if age is None:
        print("no plant ledger: not waiting")
        return
    if age <= FRESH_SECONDS:
        print("last plant tick %d s ago: inside the quiet window" % age)
        return
    if age < STALE_SECONDS:
        print("last plant tick %d s ago: the next one is not due yet, proceeding" % age)
        return
    print("last plant tick %d s ago: waiting for the next one before touching the row" % age)
    started = time.time()
    lines = sum(1 for _ in open(LEDGER, encoding="utf-8"))
    while time.time() - started < WAIT_LIMIT_SECONDS:
        time.sleep(5)
        now_lines = sum(1 for _ in open(LEDGER, encoding="utf-8"))
        if now_lines > lines:
            print("tick observed after %d s; proceeding" % (time.time() - started))
            time.sleep(3)
            return
    sys.exit("no plant tick inside %d s; is the plant running? use --no-wait if it is stopped" % WAIT_LIMIT_SECONDS)


def static_of(doc):
    data = doc.get("staticData") or {}
    if isinstance(data, str):
        data = json.loads(data)
    global_ = data.get("global", data)
    return global_.get("counter"), len(global_.get("seen") or {})


def credential_ids(doc):
    ids = []
    for node in doc.get("nodes", []):
        for cred in (node.get("credentials") or {}).values():
            ids.append((node["name"], cred.get("id")))
    return sorted(ids)


def live_static():
    out = sh("sqlite3", "-readonly", str(DB), "select staticData from workflow_entity where id='%s'" % WORKFLOW_ID)
    return static_of({"staticData": out.strip() or "{}"})


def store_max_id():
    last = None
    with open(STORE, encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                last = line
    return json.loads(last)["incident_id"] if last else None


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    patch_name = sys.argv[1]
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    patch = importlib.import_module(patch_name)

    stamp = dt.datetime.now().strftime("%Y-%m-%d")
    predeploy = ARKON / ("_predeploy_%s" % stamp)
    predeploy.mkdir(exist_ok=True)
    export_host = predeploy / ("steering_cell_%s_%s.json" % (patch_name, dt.datetime.now().strftime("%H%M%S")))
    export_container = "%s/%s/%s" % (CONTAINER_ARKON, predeploy.name, export_host.name)
    deploy_host = ARKON / "_deploy" / ("steering_cell_%s.deploy.json" % patch_name)
    deploy_container = "%s/_deploy/%s" % (CONTAINER_ARKON, deploy_host.name)

    if "--no-wait" not in sys.argv:
        wait_for_quiet_window()

    print("exporting the live workflow to %s" % export_host)
    docker("n8n", "export:workflow", "--id=%s" % WORKFLOW_ID, "--output=%s" % export_container)
    exported = json.loads(export_host.read_text(encoding="utf-8"))
    doc = exported[0] if isinstance(exported, list) else exported
    before_static = static_of(doc)
    before_creds = credential_ids(doc)
    before_nodes = len(doc["nodes"])
    print("live before: counter %s, seen %s entries, %d nodes, credentials %s" % (before_static + (before_nodes, before_creds)))

    changed = patch.patch_document(doc)
    if not changed:
        sys.exit("the live workflow already carries %s; nothing to deploy" % patch_name)
    after_static = static_of(doc)
    after_creds = credential_ids(doc)
    if after_static != before_static or after_creds != before_creds:
        sys.exit("the patch touched static data or credentials: %s -> %s, %s -> %s"
                 % (before_static, after_static, before_creds, after_creds))
    print("patched: %d nodes -> %d, static data and credentials untouched" % (before_nodes, len(doc["nodes"])))
    deploy_host.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # The append node cannot create a file (n8n 2.x, O_APPEND alone), so every
    # log the patch writes to is created here, as the container user.
    for node in doc["nodes"]:
        params = node.get("parameters") or {}
        if node.get("type") == "n8n-nodes-base.readWriteFile" and params.get("operation") == "write":
            docker("touch", params["fileName"])
            print("touched %s" % params["fileName"])

    print(docker("n8n", "import:workflow", "--input=%s" % deploy_container).strip().splitlines()[-1])
    print(docker("n8n", "publish:workflow", "--id=%s" % WORKFLOW_ID).strip().splitlines()[0])
    print("restarting n8n at %s" % dt.datetime.now().strftime("%H:%M:%S"))
    sh("docker", "restart", "n8n")
    for second in range(1, 91):
        health = sh("curl", "-s", "-m", "2", "http://localhost:5678/healthz", check=False)
        if '"ok"' in health:
            print("healthz ok after %d s" % second)
            break
        time.sleep(1)
    else:
        sys.exit("n8n did not come back inside 90 s")
    time.sleep(4)

    counter, seen = live_static()
    highest = store_max_id()
    print("live after: counter %s, seen %s entries; highest id in the store %s" % (counter, seen, highest))
    if (counter, seen) != before_static:
        sys.exit("STATIC DATA MOVED across the deploy: %s -> %s. Read the ledger: a plant tick landed inside the window."
                 % (before_static, (counter, seen)))
    if highest and int(highest.rsplit("-", 1)[1]) != counter:
        sys.exit("counter %s does not match the highest id in the store %s" % (counter, highest))
    logs = sh("docker", "logs", "n8n", "--since", "3m", check=False)
    activated = [l.split("Activated", 1)[1].strip() for l in logs.splitlines() if "Activated workflow" in l]
    print("activated: %s" % ", ".join(activated))
    if not any(WORKFLOW_ID in a for a in activated):
        sys.exit("the Steering Cell was not re-activated after the restart")
    print("done: pre-deploy export %s, deploy copy %s" % (export_host, deploy_host))


if __name__ == "__main__":
    main()
