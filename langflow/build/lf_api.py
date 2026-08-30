"""Langflow API helper, run ON THE NAS.

Reads the superuser credentials straight from /volume1/docker/langflow/.env and
logs in, so no secret ever leaves the NAS or appears in a command line. Stdlib
only, because the NAS python has nothing installed.

Usage (over ssh):
    python3 lf_api.py list
    python3 lf_api.py get <flow_id> <outfile.json>
    python3 lf_api.py upsert <flow.json>
    python3 lf_api.py delete <flow_id>
    python3 lf_api.py run <flow_id_or_endpoint> <message> [session_id]
    python3 lf_api.py session <flow_id_or_endpoint> <turns.json> <session_id>
    python3 lf_api.py upload <file>
    python3 lf_api.py components [substring]
    python3 lf_api.py component <type_name>
    python3 lf_api.py raw <METHOD> <path> [json_body_file]
"""

import gzip
import json
import pathlib
import sys
import urllib.error
import urllib.parse
import urllib.request

GZIP_MAGIC = bytes([31, 139])
BASE = "http://localhost:7860"
ENV = "/volume1/docker/langflow/.env"
KEY_FILE = "/home/ResSak/arkon-tmp/.lf_api_key"  # chmod 600, never printed
TOKEN_FILE = "/home/ResSak/arkon-tmp/.lf_token"  # cached login, Langflow rate-limits /login


def credentials():
    user = password = None
    with open(ENV, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line.startswith("LANGFLOW_SUPERUSER="):
                user = line.split("=", 1)[1].strip().strip('"').strip("'")
            elif line.startswith("LANGFLOW_SUPERUSER_PASSWORD="):
                password = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not user or not password:
        sys.exit("superuser credentials not found in " + ENV)
    return user, password


def login(force=False):
    """Log in and cache the token: Langflow returns 429 on repeated logins."""
    cache = pathlib.Path(TOKEN_FILE)
    if not force and cache.exists():
        return cache.read_text(encoding="utf-8").strip()
    user, password = credentials()
    data = urllib.parse.urlencode({"username": user, "password": password}).encode()
    request = urllib.request.Request(
        BASE + "/api/v1/login",
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        token = json.loads(response.read())["access_token"]
    cache.write_text(token, encoding="utf-8")
    cache.chmod(0o600)
    return token


TOKEN = None


def api(method, path, payload=None, raw=False, retried=False):
    global TOKEN
    if TOKEN is None:
        TOKEN = login()
    body = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(
        BASE + path,
        data=body,
        method=method,
        headers={
            "Authorization": "Bearer " + TOKEN,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            payload_bytes = response.read()
            if response.headers.get("Content-Encoding") == "gzip" or payload_bytes[:2] == GZIP_MAGIC:
                payload_bytes = gzip.decompress(payload_bytes)
            text = payload_bytes.decode("utf-8")
            return text if raw else (json.loads(text) if text else None)
    except urllib.error.HTTPError as err:
        detail_bytes = err.read()
        if detail_bytes[:2] == GZIP_MAGIC:
            detail_bytes = gzip.decompress(detail_bytes)
        detail = detail_bytes.decode("utf-8", errors="replace")
        sys.exit("HTTP %s on %s %s\n%s" % (err.code, method, path, detail[:2000]))


def api_key():
    """Return the build API key, creating and storing it once if absent.

    /api/v1/run/ accepts an API key only, not the login bearer token, so a key is
    required to exercise a flow. The value is written to KEY_FILE with mode 600
    and never printed.
    """
    path = pathlib.Path(KEY_FILE)
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    created = api("POST", "/api/v1/api_key/", {"name": "arkon-build-agent"})
    value = created["api_key"]
    path.write_text(value, encoding="utf-8")
    path.chmod(0o600)
    print("created a Langflow API key named arkon-build-agent (value stored in %s, not shown)" % KEY_FILE)
    return value


def run_api(path, payload):
    request = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode(),
        method="POST",
        headers={"x-api-key": api_key(), "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=600) as response:
            body = response.read()
            if body[:2] == GZIP_MAGIC:
                body = gzip.decompress(body)
            return json.loads(body.decode("utf-8"))
    except urllib.error.HTTPError as err:
        detail = err.read()
        if detail[:2] == GZIP_MAGIC:
            detail = gzip.decompress(detail)
        sys.exit("HTTP %s on POST %s\n%s" % (err.code, path, detail.decode("utf-8", errors="replace")[:3000]))


def cmd_list():
    flows = api("GET", "/api/v1/flows/?get_all=true&header_flows=true")
    for flow in flows:
        print(
            "%s  %-42s endpoint=%-28s updated=%s"
            % (
                flow.get("id"),
                (flow.get("name") or "")[:42],
                flow.get("endpoint_name") or "-",
                (flow.get("updated_at") or "")[:19],
            )
        )
    print("%d flows" % len(flows))


def cmd_get(flow_id, outfile):
    flow = api("GET", "/api/v1/flows/" + flow_id)
    with open(outfile, "w", encoding="utf-8") as handle:
        json.dump(flow, handle, indent=2, ensure_ascii=False)
    nodes = flow.get("data", {}).get("nodes", [])
    print("wrote %s: %s, %d nodes, %d edges" % (outfile, flow.get("name"), len(nodes), len(flow.get("data", {}).get("edges", []))))


def cmd_upsert(path):
    with open(path, encoding="utf-8") as handle:
        flow = json.load(handle)
    existing = api("GET", "/api/v1/flows/?get_all=true&header_flows=true")
    match = next((f for f in existing if f.get("name") == flow.get("name")), None)
    payload = {
        "name": flow["name"],
        "description": flow.get("description", ""),
        "data": flow["data"],
        "endpoint_name": flow.get("endpoint_name"),
    }
    if match:
        result = api("PATCH", "/api/v1/flows/" + match["id"], payload)
        print("updated %s  %s" % (result["id"], result["name"]))
    else:
        result = api("POST", "/api/v1/flows/", payload)
        print("created %s  %s" % (result["id"], result["name"]))


def cmd_delete(flow_id):
    api("DELETE", "/api/v1/flows/" + flow_id)
    print("deleted " + flow_id)


def cmd_run(target, message, session_id=None):
    payload = {"input_value": message, "output_type": "chat", "input_type": "chat"}
    if session_id:
        payload["session_id"] = session_id
    result = run_api("/api/v1/run/" + target, payload)
    printed = False
    for output in result.get("outputs", []):
        for item in output.get("outputs", []):
            text = (item.get("results", {}).get("message", {}).get("text")
                    or item.get("outputs", {}).get("message", {}).get("message"))
            if text:
                print(text)
                printed = True
    if not printed:
        print(json.dumps(result)[:4000])


def cmd_session(target, turns_file, session_id):
    """Run a scripted multi-turn session: one JSON list of message strings."""
    with open(turns_file, encoding="utf-8") as handle:
        turns = json.load(handle)
    for index, message in enumerate(turns, start=1):
        print("=" * 78)
        print("TURN %d  >>> %s" % (index, message))
        print("-" * 78)
        cmd_run(target, message, session_id)
        print()


def cmd_upload(path):
    """Upload a file to the user file store and print the stored path it gets.

    The File component takes that stored path, not a local one, so an ingestion
    flow built from a script has to put the document into Langflow first.
    Multipart is hand-built because the NAS python has no requests.
    """
    payload = pathlib.Path(path)
    boundary = "----arkonBuildBoundary"
    crlf = "\r\n"
    head = (
        "--" + boundary + crlf
        + 'Content-Disposition: form-data; name="file"; filename="' + payload.name + '"' + crlf
        + "Content-Type: application/octet-stream" + crlf + crlf
    )
    body = head.encode() + payload.read_bytes() + (crlf + "--" + boundary + "--" + crlf).encode()
    request = urllib.request.Request(
        BASE + "/api/v2/files",
        data=body,
        method="POST",
        headers={
            "Authorization": "Bearer " + login(),
            "Content-Type": "multipart/form-data; boundary=" + boundary,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            print(response.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        sys.exit("HTTP %s on upload" % err.code + chr(10)
                 + err.read().decode("utf-8", "replace")[:2000])


def cmd_components(substring=None):
    catalog = api("GET", "/api/v1/all")
    for category, entries in sorted(catalog.items()):
        for name, spec in sorted(entries.items()):
            label = "%s / %s / %s" % (category, name, (spec or {}).get("display_name", ""))
            if substring is None or substring.lower() in label.lower():
                print(label)


def cmd_component(type_name):
    catalog = api("GET", "/api/v1/all")
    for category, entries in catalog.items():
        for name, spec in entries.items():
            if name == type_name:
                print(json.dumps({"category": category, "name": name, "spec": spec}, indent=1)[:200000])
                return
    sys.exit("component not found: " + type_name)


def cmd_raw(method, path, body_file=None):
    payload = None
    if body_file:
        with open(body_file, encoding="utf-8") as handle:
            payload = json.load(handle)
    print(api(method, path, payload, raw=True)[:200000])


COMMANDS = {
    "list": cmd_list,
    "get": cmd_get,
    "upsert": cmd_upsert,
    "delete": cmd_delete,
    "run": cmd_run,
    "session": cmd_session,
    "upload": cmd_upload,
    "components": cmd_components,
    "component": cmd_component,
    "raw": cmd_raw,
}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        sys.exit(__doc__)
    COMMANDS[sys.argv[1]](*sys.argv[2:])
