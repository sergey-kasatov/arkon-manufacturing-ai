"""Deploy a patch to any LIVE Arkon workflow that carries static data, run ON
THE NAS. Stdlib only.

`deploy_steering_cell.py` is this recipe for one workflow, with the check only
that workflow needs (the incident counter against the store). This is the same
recipe for the others: export the live row, apply the patch module to the
export, assert that nothing but the patch changed (static data byte for byte,
credentials by id), import the result, publish, restart, read the static data
back from the database and compare. The quiet-window wait is shared, because the
transition endpoint's counter moves at the same plant ticks as the Steering
Cell's: the live plant's crew posts its moves right after it raises an incident.

    python3 deploy_live_patch.py --workflow arkonTransit01 --patch add_store_sync --source transition
    python3 deploy_live_patch.py --workflow arkonTransit01 --patch add_store_sync --source transition --no-wait

The patch module must expose `patch_document(doc, source=...) -> bool` and be
importable from this script's directory. Rollback is the pre-deploy export under
`/volume1/docker/arkon/_predeploy_<date>/`, imported the same way.
"""

import argparse
import datetime as dt
import importlib
import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from deploy_steering_cell import ARKON, CONTAINER_ARKON, DB, credential_ids, docker, sh, wait_for_quiet_window  # noqa: E402


def live_static(workflow_id):
    out = sh("sqlite3", "-readonly", str(DB), "select staticData from workflow_entity where id='%s'" % workflow_id)
    return normalise(out.strip() or "{}")


def normalise(static):
    if isinstance(static, str):
        static = json.loads(static or "{}")
    return json.dumps(static or {}, sort_keys=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--workflow", required=True, help="the live workflow id")
    parser.add_argument("--patch", required=True, help="patch module beside this script")
    parser.add_argument("--source", default=None, help="passed to patch_document as source=")
    parser.add_argument("--no-wait", action="store_true", help="skip the plant tick window")
    args = parser.parse_args()

    patch = importlib.import_module(args.patch)
    stamp = dt.datetime.now().strftime("%Y-%m-%d")
    predeploy = ARKON / ("_predeploy_%s" % stamp)
    predeploy.mkdir(exist_ok=True)
    label = "%s_%s" % (args.workflow, args.patch)
    export_host = predeploy / ("%s_%s.json" % (label, dt.datetime.now().strftime("%H%M%S")))
    export_container = "%s/%s/%s" % (CONTAINER_ARKON, predeploy.name, export_host.name)
    deploy_host = ARKON / "_deploy" / ("%s.deploy.json" % label)
    deploy_container = "%s/_deploy/%s" % (CONTAINER_ARKON, deploy_host.name)

    if not args.no_wait:
        wait_for_quiet_window()

    print("exporting the live workflow to %s" % export_host)
    docker("n8n", "export:workflow", "--id=%s" % args.workflow, "--output=%s" % export_container)
    exported = json.loads(export_host.read_text(encoding="utf-8"))
    doc = exported[0] if isinstance(exported, list) else exported
    before_static = normalise(doc.get("staticData"))
    before_creds = credential_ids(doc)
    before_nodes = len(doc["nodes"])
    print("live before: %d nodes, static data %s, credentials %s" % (before_nodes, before_static, before_creds))

    kwargs = {} if args.source is None else {"source": args.source}
    changed = patch.patch_document(doc, **kwargs)
    if not changed:
        sys.exit("the live workflow already carries %s; nothing to deploy" % args.patch)
    if normalise(doc.get("staticData")) != before_static or credential_ids(doc) != before_creds:
        sys.exit("the patch touched static data or credentials; refusing to import")
    print("patched: %d nodes -> %d, static data and credentials untouched" % (before_nodes, len(doc["nodes"])))
    deploy_host.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(docker("n8n", "import:workflow", "--input=%s" % deploy_container).strip().splitlines()[-1])
    print(docker("n8n", "publish:workflow", "--id=%s" % args.workflow).strip().splitlines()[0])
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

    after_static = live_static(args.workflow)
    if after_static != before_static:
        sys.exit("STATIC DATA MOVED across the deploy: %s -> %s. A write landed inside the window; "
                 "compare the counter with the log before trusting the next id." % (before_static, after_static))
    print("live after: static data unchanged, %s" % after_static)
    logs = sh("docker", "logs", "n8n", "--since", "3m", check=False)
    activated = [l.split("Activated", 1)[1].strip() for l in logs.splitlines() if "Activated workflow" in l]
    print("activated: %s" % ", ".join(activated))
    if not any(args.workflow in a for a in activated):
        sys.exit("%s was not re-activated after the restart" % args.workflow)
    print("done: pre-deploy export %s, deploy copy %s" % (export_host, deploy_host))


if __name__ == "__main__":
    main()
