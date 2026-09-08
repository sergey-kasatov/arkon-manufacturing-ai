# Customer documents: what a customer may read

The documents in this directory are the outward half of the Arkon quality
system: what Arkon tells a customer's quality engineer about how a quality
notice or a complaint is handled, what Arkon commits to at each stage, whom to
escalate to, and what to submit. The rest of `docs/` describes the same system
from inside the plant, for the plant's own people, and none of it is customer
information.

They exist for the Customer Quality Desk, the customer-facing agent built as
the MSIT course project 2A on n8n (the coursework lives outside this
repository; the platform pieces are here). The desk answers from these three
documents, held in the Qdrant collection `arkon-customer-desk`, and from the
customer status endpoint (`n8n/README.md`, "Customer status API"), and from
nothing else. The two stores of the platform are its two trust boundaries:
the operators' assistant reads `arkon-knowledge` (the charter, the SOP, the
model cards), the desk reads `arkon-customer-desk`, and neither can reach the
other's collection even by accident.

Arkon Manufacturing is a fictional company. Every role, address, commitment
and certification claim in these documents belongs to the fictional company,
and each document says so in its header.

## The set, and the decision behind every exclusion

The list is owned by `n8n/build/customer_documents.py`, which the ingestion
workflow generator, the ingestion probe and the tests read; this table
restates it.

| Document | In or out | Reason |
|---|---|---|
| `Customer_Complaint_Handling_Guide_2026.md` | In | Current, approved, the primary document: the reference format, the five stages, the customer status vocabulary and the commitments per stage |
| `Quality_Commitments_and_Escalation_Contacts.md` | In | Approved for customer use: the response commitments, the channels and business hours, the escalation ladder by role, the fictional company's certification claims |
| `Complaint_Submission_Checklist.md` | In | Customer-facing and the most common query type: the twelve items a complaint is submitted with and why each is needed |
| `excluded/Customer_Complaint_Handling_Guide_2025.md` | Out: version conflict | The superseded guide with the old reference format, four stages and the old commitments. Retrieval cannot tell old from current, so a store holding both answers a commitment question with either |
| `excluded/Customer_Letter_Template_DRAFT.md` | Out: not approved | A closure letter template under legal review, carrying an unlimited cost commitment and an employee's name that the reviewers struck |
| `../../events/roster.json` | Out: personal data | The plant's people and shifts. Employee names never leave the plant through a customer channel |
| The incident store on the NAS (`/data/arkon/incidents.jsonl`) | Out: other customers, employee data, internal evidence | Every incident of every customer with its assignee, evidence and priority. The desk reaches one record at a time through the customer status endpoint, which serves eight customer fields and nothing else |
| `../Steering_Cell_SOP.md` and the seven `../Model_Card_*.md` | Out: internal operating instructions and model internals | Approved for the plant's operators and held in their own collection; thresholds, model versions and operating rules are not customer information |

Two of the excluded documents were written to be excluded. A superseded
version and an unapproved draft are the two failure modes a document store has
to be shown to refuse, and a store that was never offered either proves
nothing about them.

## The vocabulary is the endpoint's

The customer status words, the five stage names, the next steps and the
commitment windows in the guide and the commitments document are the ones the
customer status endpoint serves, and both sides read them from
`n8n/build/customer_projection.py`. `tests/test_customer_documents.py` fails
when a document and the projection disagree, so a promise in a document is the
promise the status answer computes, and a changed window has to be changed in
both.

The same test holds the boundary from the other side: no simulated employee
name from the roster and no internal field name appears in an included
document, and none of the superseded guide's values does either.

## Building the collection

`n8n/build/build_customer_desk_kb_workflow.py` generates
`n8n/customer_desk_kb_v1.json`, which carries the three texts verbatim and
ingests them (500-character chunks with a 50 overlap, `gemini-embedding-001`
at 3072 dimensions, Cosine, one `source` label per document) when its ingest
webhook is called, and answers a retrieval query on its search webhook. The
deployment record and the measurements are in `n8n/README.md`, "Customer desk
knowledge base".
