"""The Customer Quality Desk's document set: what a customer may read.

The desk answers a customer's quality engineer from three documents Arkon has
approved for customer use, held in the Qdrant collection `arkon-customer-desk`,
and from nothing else. This file is the one place that says which documents
those are, why every other candidate stays out, and how the collection is
built (the splitter values, the embedding model, the vector size), for the
reason `customer_projection.py` and `lifecycle.py` are one file each: a list
copied into a workflow, a checker, a test and a README is a list that drifts.

Read by the knowledge-base workflow generator (which injects the three texts
verbatim), by the ingestion probe (which measures the collection against
them) and by the tests (which pin the documents to the customer projection's
vocabulary and to the deny list of what must never leave the plant).

The exclusions are a governance decision each, not files planted for an
exercise: two of them are real files of the platform (the roster and the
incident store), two are internal documents the operators' assistant reads
from its own collection, and two were written to be excluded (the superseded
2025 guide and the unapproved draft letter), because a version conflict and an
unapproved draft are the two failure modes a store has to be shown to refuse.
"""

import json
import pathlib
import re

from customer_projection import COMMITMENT_HOURS, CUSTOMER_STAGES, DEFAULT_ACK_HOURS, INTERNAL_NAMES

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
CUSTOMER_DOCS = ROOT / "docs" / "customer"

# The collection and how it is built. Same splitter values as the course
# (500 / 50), the same embedding model the comparison slice queries
# `arkon-knowledge` with, at its native 3072 dimensions with Cosine distance.
COLLECTION = "arkon-customer-desk"
CHUNK_SIZE = 500
CHUNK_OVERLAP = 50
EMBEDDING_MODEL = "models/gemini-embedding-001"
VECTOR_SIZE = 3072
DISTANCE = "Cosine"
TOP_K = 4

# What the desk may read: file, the `source` label every chunk carries, the
# title, and the reason the document is in, in the graders' own categories.
INCLUDED = [
    {
        "file": "Customer_Complaint_Handling_Guide_2026.md",
        "source": "Customer_Complaint_Handling_Guide_2026",
        "title": "Customer Complaint Handling Guide 2026",
        "reason": "Current, approved, the primary document: the reference format, the five stages, "
        "the customer status vocabulary and the commitments per stage",
    },
    {
        "file": "Quality_Commitments_and_Escalation_Contacts.md",
        "source": "Quality_Commitments_and_Escalation_Contacts",
        "title": "Quality Commitments and Escalation Contacts",
        "reason": "Approved for customer use: the response commitments, the channels and business "
        "hours, the escalation ladder by role, the fictional company's certification claims",
    },
    {
        "file": "Complaint_Submission_Checklist.md",
        "source": "Complaint_Submission_Checklist",
        "title": "Complaint Submission Checklist",
        "reason": "Customer-facing and the most common query type: the twelve items a complaint "
        "is submitted with and why each one is needed",
    },
]

# What stays out, and why. `path` is relative to the repository root; the
# store export lives on the NAS and is named for what it is.
EXCLUDED = [
    {
        "path": "docs/customer/excluded/Customer_Complaint_Handling_Guide_2025.md",
        "category": "version conflict",
        "reason": "The superseded 2025 guide with the old reference format, four stages and the old "
        "commitments (48 hours, 5 and 30 working days). Retrieval cannot tell old from current, "
        "so a store holding both answers a commitment question with either",
        "marker": "SUPERSEDED",
    },
    {
        "path": "docs/customer/excluded/Customer_Letter_Template_DRAFT.md",
        "category": "not approved",
        "reason": "A closure letter template under legal review, carrying an unlimited cost "
        "commitment and an employee's name that the reviewers struck; nothing in it may reach a "
        "customer until it is approved",
        "marker": "NOT APPROVED FOR CUSTOMER USE",
    },
    {
        "path": "events/roster.json",
        "category": "personal data",
        "reason": "The plant's people and shifts. Employee names never leave the plant through a "
        "customer channel: a data-protection question and, in a German plant, a works-council one",
        "marker": None,
    },
    {
        "path": "/data/arkon/incidents.jsonl (the incident store on the NAS)",
        "category": "other customers, employee data, internal evidence",
        "reason": "Every incident of every customer with its assignee, its model evidence and its "
        "priority. The desk reaches one record at a time through the customer status endpoint, "
        "which serves the eight customer fields and nothing else",
        "marker": None,
    },
    {
        "path": "docs/Steering_Cell_SOP.md and docs/Model_Card_*.md",
        "category": "internal operating instructions and model internals",
        "reason": "Approved for the plant's operators and held in the operators' own collection "
        "`arkon-knowledge`; thresholds, model versions and operating rules are not customer "
        "information",
        "marker": None,
    },
]

# Values of the superseded guide that must appear in no included document, so
# the version conflict is real: the old reference format and the old windows.
SUPERSEDED_VALUES = ["CQ-2025", "48 hours", "30 working days", "5 working days"]

# The reference format every customer document quotes, as the guide states it
# and as the customer status API accepts it.
REFERENCE_FORMAT = "ARK-INC-#####"
REFERENCE_EXAMPLE = "ARK-INC-00348"


def read_included():
    """The three documents as the ingestion workflow carries them."""
    documents = []
    for entry in INCLUDED:
        text = (CUSTOMER_DOCS / entry["file"]).read_text(encoding="utf-8")
        documents.append({"source": entry["source"], "title": entry["title"], "text": text})
    return documents


def hours_phrase(hours):
    """A commitment window in the words the documents use for it."""
    if hours < 1:
        return "%d minutes" % round(hours * 60)
    if hours == 1:
        return "1 hour"
    return "%d hours" % round(hours)


def commitment_phrases():
    """Every commitment window of the projection, as a phrase the documents must carry.

    Rendered from the numbers rather than written here, so that a changed window
    fails the document test until the documents say the new number.
    """
    phrases = set()
    for status, window in COMMITMENT_HOURS.items():
        if isinstance(window, dict):
            for hours in window.values():
                phrases.add(hours_phrase(hours))
            phrases.add(hours_phrase(DEFAULT_ACK_HOURS))
        else:
            phrases.add(hours_phrase(window))
    return sorted(phrases)


def vocabulary():
    """The customer words of the projection that the guide must state verbatim."""
    words = set()
    for stage in CUSTOMER_STAGES.values():
        words.add(stage["customer_status"])
        words.add(stage["stage_name"])
        if stage["next_step"]:
            words.add(stage["next_step"])
    return sorted(words)


def roster_names():
    """The simulated people of the plant, none of whom may appear in a customer document."""
    roster = json.loads((ROOT / "events" / "roster.json").read_text(encoding="utf-8"))
    names = []
    for role in roster["roles"].values():
        names.extend(role["people"])
    return names


# The plant's own vocabulary that a customer document must not carry: the
# module names of the event contract (the closed enum in the schema) and the
# public datasets behind them. The single English words of INTERNAL_NAMES
# ("evidence", "summary", "note") are field names in the answer node's code and
# ordinary words in prose, so the prose check uses the underscored names only.
DATASET_NAMES = ["CMAPSS", "Scania", "MVTec", "GC10", "NHTSA", "NEU"]


def module_names():
    schema = json.loads((ROOT / "events" / "arkon_event_schema.json").read_text(encoding="utf-8"))
    return list(schema["properties"]["source_module"]["enum"])


def internal_name_hits(text):
    """Internal field names, module names and dataset names found in a customer document."""
    fields = [name for name in INTERNAL_NAMES if "_" in name]
    hits = []
    for token in fields + module_names() + DATASET_NAMES:
        if re.search(r"\b%s\b" % re.escape(token), text):
            hits.append(token)
    return hits


def paragraph_lengths(text):
    """Character length of every paragraph, for the chunk-boundary sanity check."""
    return [len(p) for p in re.split(r"\n\s*\n", text) if p.strip()]
