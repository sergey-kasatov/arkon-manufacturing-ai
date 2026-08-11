"""Replay Arkon risk events into the Quality Steering Cell webhook.

Posts each JSONL event to the n8n webhook so the incident flow can be
demonstrated without waiting for a live model run. Stdlib only.

Usage:
    python n8n/replay_events.py http://AK2101:5678/webhook/arkon-event events/out/cmapss_events_FD001.jsonl
    python n8n/replay_events.py <url> <events.jsonl> --priority P1,P2 --limit 10 --delay 1
"""

import argparse
import json
import time
import urllib.request

# Parse arguments
parser = argparse.ArgumentParser(description="Replay Arkon events into n8n")
parser.add_argument("url", help="webhook URL, e.g. http://AK2101:5678/webhook/arkon-event")
parser.add_argument("events", help="path to events JSONL file")
parser.add_argument("--priority", default=None, help="comma-separated filter, e.g. P1,P2")
parser.add_argument("--limit", type=int, default=None, help="send at most N events")
parser.add_argument("--delay", type=float, default=0.5, help="seconds between posts")
args = parser.parse_args()

# Load and filter events
with open(args.events, encoding="utf-8") as f:
    events = [json.loads(line) for line in f if line.strip()]
if args.priority:
    wanted = {p.strip().upper() for p in args.priority.split(",")}
    events = [e for e in events if e["priority"] in wanted]
if args.limit:
    events = events[: args.limit]

# Post one by one
for i, event in enumerate(events, start=1):
    request = urllib.request.Request(
        args.url,
        data=json.dumps(event).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8", errors="replace")[:120]
            print(f"{i}/{len(events)} {event['event_id']} {event['priority']} -> {response.status} {body}")
    except urllib.error.HTTPError as err:
        print(f"{i}/{len(events)} {event['event_id']} {event['priority']} -> HTTP {err.code} {err.read().decode(errors='replace')[:120]}")
    time.sleep(args.delay)
