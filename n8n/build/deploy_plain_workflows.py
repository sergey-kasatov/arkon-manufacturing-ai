"""Deploy plain Arkon workflows (no static data, credentials bound by id), run ON THE NAS. Stdlib only.

The recipe the README gives for the status API and the customer status API,
as code: import each tracked file from the bind mount, publish it by the id
the file carries, restart the container once for all of them (the running
process holds its active workflows in memory, so a CLI import does not take
effect without one), wait for healthz, then read the activation lines and the
webhook rows back and refuse to call it done if one is missing. The restart is
placed inside the quiet window after a plant tick for the reason
`deploy_steering_cell.py` gives: the Steering Cell's counter and cache live in
the running row, and a restart that overlaps a tick loses one.

    python3 deploy_plain_workflows.py customer_desk_kb_v1.json customer_desk_v1.json
    python3 deploy_plain_workflows.py customer_desk_v1.json --no-wait     # a stopped plant

Not for the Steering Cell (static data: `deploy_steering_cell.py`) and not for
a live workflow that must keep its row (`deploy_live_patch.py`).
"""

import datetime as dt
import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from deploy_steering_cell import ARKON, CONTAINER_ARKON, DB, docker, sh, wait_for_quiet_window  # noqa: E402


def main():
    files = [arg for arg in sys.argv[1:] if not arg.startswith("--")]
    if not files:
        sys.exit(__doc__)
    workflows = []
    for name in files:
        path = ARKON / "_deploy" / name
        if not path.exists():
            sys.exit("not in the deploy folder: %s" % path)
        doc = json.loads(path.read_text(encoding="utf-8"))
        workflows.append((name, doc["id"], doc["name"], len(doc["nodes"])))
        print("%s: id %s, %d nodes, %s" % (name, doc["id"], len(doc["nodes"]), doc["name"]))

    if "--no-wait" not in sys.argv:
        wait_for_quiet_window()

    for name, workflow_id, _, _ in workflows:
        print(docker("n8n", "import:workflow", "--input=%s/_deploy/%s" % (CONTAINER_ARKON, name)).strip().splitlines()[-1])
        print(docker("n8n", "publish:workflow", "--id=%s" % workflow_id).strip().splitlines()[0])

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
    time.sleep(6)

    logs = sh("docker", "logs", "n8n", "--since", "3m", check=False)
    activated = [line.split("Activated", 1)[1].strip() for line in logs.splitlines() if "Activated workflow" in line]
    print("activated: %s" % ", ".join(activated))
    missing = [workflow_id for _, workflow_id, _, _ in workflows if not any(workflow_id in a for a in activated)]
    if missing:
        sys.exit("not re-activated after the restart: %s" % ", ".join(missing))

    ids = ",".join("'%s'" % workflow_id for _, workflow_id, _, _ in workflows)
    rows = sh("sqlite3", "-readonly", str(DB),
              "select workflowId, method, webhookPath from webhook_entity where workflowId in (%s) order by 1, 3" % ids)
    print("webhook rows:\n" + rows.strip())
    print("done at %s" % dt.datetime.now().strftime("%H:%M:%S"))


if __name__ == "__main__":
    main()
