"""Rebuild and measure the Customer Quality Desk's collection, then test retrieval in it.

Measures the collection Qdrant holds rather than trusting the ingest answer:
the created configuration (vector size and distance), the point count, the
chunks per source label, the payload keys the desk's retrieval reads, and,
over every chunk, that nothing a customer may not see was ingested (no
simulated employee name, no superseded value). Then the retrieval suite: a
query, the source expected first, and what no passage may carry, each
expectation written here before the run. Stdlib only.

    python n8n/customer_desk_kb_probe.py --rebuild
    python n8n/customer_desk_kb_probe.py --suite
    python n8n/customer_desk_kb_probe.py --search "What do I have to submit with a complaint?"
    python n8n/customer_desk_kb_probe.py --n8n http://AK2101:5678 --qdrant http://AK2101:6333 --rebuild --suite
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "build"))
from customer_documents import (  # noqa: E402
    CHUNK_SIZE,
    COLLECTION,
    DISTANCE,
    INCLUDED,
    SUPERSEDED_VALUES,
    TOP_K,
    VECTOR_SIZE,
    roster_names,
)

INGEST = "/webhook/arkon-customer-desk-ingest"
SEARCH = "/webhook/arkon-customer-desk-search"

# The retrieval suite. `expect` is the source label the top passage must carry
# (a list means any of them), `forbid` strings no returned passage may contain.
SUITE = [
    {
        "query": "What do I have to submit with a complaint?",
        "expect": ["Complaint_Submission_Checklist"],
        "forbid": [],
    },
    {
        "query": "How quickly does Arkon acknowledge a quality notice?",
        "expect": ["Customer_Complaint_Handling_Guide_2026", "Quality_Commitments_and_Escalation_Contacts"],
        "forbid": SUPERSEDED_VALUES,
    },
    {
        "query": "Who do I escalate to when a commitment date has been missed?",
        "expect": ["Quality_Commitments_and_Escalation_Contacts"],
        "forbid": [],
    },
    {
        "query": "What does the status Containment in place mean and what happens next?",
        "expect": ["Customer_Complaint_Handling_Guide_2026"],
        "forbid": [],
    },
    {
        "query": "Which engineer at Arkon is working on my notice?",
        "expect": ["Customer_Complaint_Handling_Guide_2026", "Quality_Commitments_and_Escalation_Contacts"],
        "forbid": roster_names(),
    },
]

failures = 0


def check(name, condition, detail=""):
    global failures
    if condition:
        print("ok   " + name)
    else:
        failures += 1
        print("FAIL " + name + (" - " + detail if detail else ""))


def request(url, method="GET", body=None, timeout=300):
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    started = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode("utf-8")), time.time() - started
    except urllib.error.HTTPError as error:
        text = error.read().decode("utf-8")
        try:
            return error.code, json.loads(text), time.time() - started
        except ValueError:
            return error.code, {"raw": text}, time.time() - started


def scroll_all(qdrant):
    """Every point of the collection, payload only."""
    points, offset = [], None
    while True:
        body = {"limit": 100, "with_payload": True, "with_vector": False}
        if offset is not None:
            body["offset"] = offset
        status, answer, _ = request("%s/collections/%s/points/scroll" % (qdrant, COLLECTION), "POST", body)
        if status != 200:
            return points, "scroll answered %s: %s" % (status, answer)
        result = answer.get("result", {})
        points.extend(result.get("points", []))
        offset = result.get("next_page_offset")
        if offset is None:
            return points, None


def rebuild(n8n, qdrant):
    print("== rebuild through %s%s" % (n8n, INGEST))
    status, answer, seconds = request(n8n + INGEST, "POST", {"source": "customer_desk_kb_probe"})
    print("ingest answered %s in %.1f s: %s" % (status, seconds, json.dumps(answer)[:400]))
    check("the ingest answers 200 ok", status == 200 and answer.get("status") == "ok")
    check("the ingest names the three documents", sorted(d.get("source") for d in answer.get("documents", []))
          == sorted(e["source"] for e in INCLUDED))
    measure(qdrant)


def measure(qdrant):
    print("== the collection %s at %s" % (COLLECTION, qdrant))
    status, answer, _ = request("%s/collections/%s" % (qdrant, COLLECTION))
    check("the collection exists", status == 200, str(answer)[:200])
    if status != 200:
        return
    config = answer["result"]["config"]["params"]["vectors"]
    vectors = config.get("") if "" in config else config
    check("vector size %d, distance %s" % (VECTOR_SIZE, DISTANCE),
          vectors.get("size") == VECTOR_SIZE and vectors.get("distance") == DISTANCE, json.dumps(vectors))
    points, error = scroll_all(qdrant)
    check("every point read back", error is None, error or "")
    print("points: %d (points_count reported %s)" % (len(points), answer["result"].get("points_count")))
    check("the point count is the reported count", len(points) == answer["result"].get("points_count"))

    per_source, lengths, bad_payload, leaks = {}, [], 0, []
    names = roster_names()
    for point in points:
        payload = point.get("payload", {})
        content = payload.get("content")
        metadata = payload.get("metadata", {})
        if not isinstance(content, str) or not isinstance(metadata, dict) or "source" not in metadata:
            bad_payload += 1
            continue
        per_source[metadata["source"]] = per_source.get(metadata["source"], 0) + 1
        lengths.append(len(content))
        for value in names + SUPERSEDED_VALUES:
            if value in content:
                leaks.append((metadata["source"], value))
    check("every point carries content and metadata.source", bad_payload == 0, "%d points without" % bad_payload)
    for entry in INCLUDED:
        print("  %-48s %4d chunks" % (entry["source"], per_source.get(entry["source"], 0)))
        check("%s is in the store" % entry["source"], per_source.get(entry["source"], 0) > 0)
    check("no source outside the three", set(per_source) <= {e["source"] for e in INCLUDED}, str(set(per_source)))
    if lengths:
        print("chunk length: min %d, median %d, max %d" % (min(lengths), sorted(lengths)[len(lengths) // 2], max(lengths)))
        check("no chunk longer than the chunk size", max(lengths) <= CHUNK_SIZE, "max %d" % max(lengths))
    check("no employee name and no superseded value in any chunk", not leaks, str(leaks[:5]))


def search(n8n, query):
    url = n8n + SEARCH + "?" + urllib.parse.urlencode({"q": query})
    status, answer, seconds = request(url)
    return status, answer, seconds


def run_suite(n8n):
    print("== retrieval suite through %s%s (top %d)" % (n8n, SEARCH, TOP_K))
    for case in SUITE:
        status, answer, seconds = search(n8n, case["query"])
        passages = answer.get("passages", []) if isinstance(answer, dict) else []
        top = passages[0] if passages else {}
        print("\nQ: %s\n   %s in %.2f s, %d passages, top: %s (score %s)\n   %s" % (
            case["query"], status, seconds, len(passages), top.get("source"), top.get("score"),
            (top.get("text") or "").replace("\n", " ")[:160]))
        check("answers 200 with passages", status == 200 and len(passages) > 0)
        check("the top passage is from %s" % " or ".join(case["expect"]), top.get("source") in case["expect"],
              str(top.get("source")))
        hits = [(p.get("source"), value) for p in passages for value in case["forbid"] if value in (p.get("text") or "")]
        check("no passage carries a forbidden value", not hits, str(hits[:3]))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--n8n", default="http://AK2101:5678")
    parser.add_argument("--qdrant", default="http://AK2101:6333")
    parser.add_argument("--rebuild", action="store_true", help="drop, ingest and measure the collection")
    parser.add_argument("--measure", action="store_true", help="measure the collection as it is")
    parser.add_argument("--suite", action="store_true", help="run the retrieval suite")
    parser.add_argument("--search", default=None, help="one retrieval query, printed in full")
    args = parser.parse_args()

    if args.rebuild:
        rebuild(args.n8n, args.qdrant)
    elif args.measure:
        measure(args.qdrant)
    if args.suite:
        run_suite(args.n8n)
    if args.search:
        status, answer, seconds = search(args.n8n, args.search)
        print("%s in %.2f s" % (status, seconds))
        print(json.dumps(answer, indent=2))
    if not (args.rebuild or args.measure or args.suite or args.search):
        parser.print_help()
        return
    print("\n%s" % ("ALL PASS" if failures == 0 else "%d FAILED" % failures))
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
